"""Core PCA / reconstruction-error logic. The notebook and the CLI both call these functions.

Notation (matches the chat):  x ~= mu + sigma * (z @ W.T)
  x     : one row of raw descriptors (original units)
  mu    : per-descriptor baseline mean
  sigma : per-descriptor baseline std (floored, so near-constant metrics don't explode)
  W     : loadings matrix, shape (n_descriptors, k), columns are the principal axes
  z     : PC scores, shape (k,)
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd
from sklearn.decomposition import PCA

from . import prom, synthetic


# --------------------------------------------------------------------------- loading
def load_metrics(
    source: str = "auto",
    minutes: float = 60,
    step: str = "15s",
    prom_url: str | None = None,
) -> tuple[pd.DataFrame, pd.DataFrame, str]:
    """Return (metrics, fault_flags, source_used). source: 'auto' | 'prometheus' | 'synthetic'."""
    url = prom_url or prom.PROM_URL
    if source in ("auto", "prometheus"):
        if prom.is_up(url):
            df, faults = prom.fetch_metrics(minutes=minutes, step=step, url=url)
            if df.dropna(how="all").shape[0] >= 20:
                return df, faults, "prometheus"
            if source == "prometheus":
                raise RuntimeError(
                    f"Prometheus at {url} returned too little data ({len(df)} rows). "
                    "Is the stack up and has load been running for a few minutes?"
                )
        elif source == "prometheus":
            raise RuntimeError(f"Prometheus not reachable at {url}")
        print(f"[sre_pca] Prometheus unavailable or empty at {url} -> using synthetic data")
    df, faults = synthetic.make_synthetic()
    return df, faults, "synthetic"


# --------------------------------------------------------------------------- preprocessing
def preprocess(df: pd.DataFrame, min_coverage: float = 0.8) -> pd.DataFrame:
    """Align and clean: drop sparse columns, fill short gaps, drop leading/trailing empty rows."""
    df = df.sort_index().replace([np.inf, -np.inf], np.nan)
    keep = df.columns[df.notna().mean() >= min_coverage]
    dropped = sorted(set(df.columns) - set(keep))
    if dropped:
        print(f"[sre_pca] dropping sparse columns (<{min_coverage:.0%} coverage): {dropped}")
    df = df[keep].ffill(limit=4).bfill(limit=4)
    return df.dropna(how="any")


def remove_seasonality(df: pd.DataFrame, period: int, method: str = "stl") -> pd.DataFrame:
    """Remove a repeating cycle (daily/weekly in real systems; the k6 wave in this lab).

    period is in samples, e.g. 1 day at 15 s step = 5760; the default k6 wave (300 s) = 20.
    method='stl'     : STL decomposition per column, returns trend + residual (season removed)
    method='profile' : subtract the mean of each phase position (cheap, no statsmodels needed)
    """
    if period < 2 or len(df) < 2 * period:
        print(f"[sre_pca] not enough data for period={period}; skipping seasonality removal")
        return df
    out = df.copy()
    if method == "stl":
        from statsmodels.tsa.seasonal import STL

        for c in df.columns:
            res = STL(df[c].to_numpy(), period=period, robust=True).fit()
            out[c] = df[c].to_numpy() - res.seasonal
    elif method == "profile":
        phase = np.arange(len(df)) % period
        for c in df.columns:
            prof = df[c].groupby(phase).transform("mean") - df[c].mean()
            out[c] = df[c] - prof.to_numpy()
    else:
        raise ValueError(f"unknown method {method!r}")
    return out


def choose_baseline(
    df: pd.DataFrame,
    faults: pd.DataFrame | None = None,
    baseline_minutes: float | None = None,
    frac: float = 0.4,
    margin_samples: int = 8,
) -> pd.Series:
    """Boolean mask of 'known normal' rows used to fit PCA.

    Priority: explicit baseline_minutes from the start of the window
              -> everything before the first injected fault (minus a margin)
              -> the first `frac` of the window."""
    mask = pd.Series(False, index=df.index)
    if baseline_minutes:
        mask[df.index < df.index[0] + pd.Timedelta(minutes=baseline_minutes)] = True
    elif faults is not None and faults.reindex(df.index).fillna(0).to_numpy().any():
        any_fault = faults.reindex(df.index).fillna(0).max(axis=1).to_numpy() > 0
        first = int(np.argmax(any_fault))
        mask.iloc[: max(0, first - margin_samples)] = True
    if mask.sum() < 20:
        mask[:] = False
        mask.iloc[: max(20, int(len(df) * frac))] = True
    if faults is not None:  # never train on a labelled fault sample
        f = faults.reindex(df.index).fillna(0).max(axis=1) > 0
        mask &= ~f
    return mask


# --------------------------------------------------------------------------- model
@dataclass
class PCAModel:
    columns: list[str]
    mu: pd.Series
    sigma: pd.Series
    pca: PCA  # fitted on ALL components (for the scree plot)
    k: int  # number of components kept for reconstruction
    threshold: float = np.nan
    threshold_quantile: float = 0.99
    meta: dict = field(default_factory=dict)

    @property
    def W(self) -> np.ndarray:  # (n_descriptors, k)
        return self.pca.components_[: self.k].T

    @property
    def explained(self) -> np.ndarray:
        return self.pca.explained_variance_ratio_

    def standardize(self, df: pd.DataFrame) -> np.ndarray:
        return ((df[self.columns] - self.mu) / self.sigma).to_numpy()

    def transform(self, df: pd.DataFrame) -> pd.DataFrame:
        z = self.standardize(df) @ self.W
        return pd.DataFrame(z, index=df.index, columns=[f"PC{i + 1}" for i in range(self.k)])

    def loadings(self) -> pd.DataFrame:
        return pd.DataFrame(self.W, index=self.columns, columns=[f"PC{i + 1}" for i in range(self.k)])


def fit_pca(
    df_baseline: pd.DataFrame,
    var_target: float = 0.90,
    n_components: int | None = None,
    threshold_quantile: float = 0.99,
    rel_std_floor: float = 0.02,
    abs_std_floor: float = 1e-3,
) -> PCAModel:
    """Standardize on the baseline and fit PCA; keep k PCs reaching var_target (or n_components)."""
    mu = df_baseline.mean()
    sd = df_baseline.std(ddof=0)
    # Floor sigma so a metric that is ~constant in baseline (e.g. error_ratio ~ 0) doesn't get a
    # near-zero std, which would turn tiny noise into huge z-scores.
    sigma = np.maximum(sd, np.maximum(rel_std_floor * mu.abs(), abs_std_floor))
    Z = ((df_baseline - mu) / sigma).to_numpy()
    pca = PCA().fit(Z)
    if n_components is None:
        cum = np.cumsum(pca.explained_variance_ratio_)
        k = int(np.searchsorted(cum, var_target) + 1)
    else:
        k = n_components
    k = max(1, min(k, Z.shape[1] - 1))  # keep >=1 residual dimension or recon error is always 0
    model = PCAModel(list(df_baseline.columns), mu, sigma, pca, k, threshold_quantile=threshold_quantile)
    base_err = score(model, df_baseline)["recon_error"]
    model.threshold = float(base_err.quantile(threshold_quantile))
    model.meta["n_baseline"] = len(df_baseline)
    return model


def score(model: PCAModel, df: pd.DataFrame) -> pd.DataFrame:
    """Per-row reconstruction error (SPE / Q statistic in standardized space) + top contributor."""
    Z = model.standardize(df)
    Zhat = (Z @ model.W) @ model.W.T
    resid = Z - Zhat
    err = (resid**2).sum(axis=1)
    contrib = pd.DataFrame(resid**2, index=df.index, columns=model.columns)
    out = pd.DataFrame({"recon_error": err}, index=df.index)
    out["top_contributor"] = contrib.idxmax(axis=1)
    out["anomaly"] = out["recon_error"] > model.threshold if np.isfinite(model.threshold) else False
    return out


def inverse_from_pcs(model: PCAModel, z: list[float] | np.ndarray) -> pd.Series:
    """Back-calculate descriptor values (original units) from a point in PC space.

    x = mu + sigma * (z @ W.T). PCs not given (beyond len(z)) are set to 0 (= baseline average)."""
    z = np.asarray(z, dtype=float)
    if len(z) > model.k:
        raise ValueError(f"model keeps {model.k} PCs; got {len(z)} values")
    zfull = np.zeros(model.k)
    zfull[: len(z)] = z
    x = model.mu.to_numpy() + model.sigma.to_numpy() * (zfull @ model.W.T)
    return pd.Series(x, index=model.columns, name="back_calculated")


def evaluate(scores: pd.DataFrame, faults: pd.DataFrame, baseline_mask: pd.Series, lag_samples: int = 4) -> pd.DataFrame:
    """Detection rate per fault type and false-positive rate on non-fault, non-baseline rows.

    lag_samples dilates each fault window forward to account for rate()[1m] smearing."""
    f = faults.reindex(scores.index).fillna(0).astype(bool)
    f_dil = f.rolling(lag_samples + 1, min_periods=1).max().astype(bool)
    rows = []
    for c in f.columns:
        sel = f[c].to_numpy()
        if sel.any():
            rows.append({"window": c, "samples": int(sel.sum()), "flagged_frac": float(scores["anomaly"][sel].mean())})
    any_f = f_dil.any(axis=1).to_numpy()
    normal = (~any_f) & (~baseline_mask.reindex(scores.index).fillna(False).to_numpy())
    if normal.any():
        rows.append({"window": "normal (held-out)", "samples": int(normal.sum()), "flagged_frac": float(scores["anomaly"][normal].mean())})
    base = baseline_mask.reindex(scores.index).fillna(False).to_numpy()
    rows.append({"window": "baseline (train)", "samples": int(base.sum()), "flagged_frac": float(scores["anomaly"][base].mean())})
    return pd.DataFrame(rows)
