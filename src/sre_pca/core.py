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
from datetime import datetime

import numpy as np
import pandas as pd
from sklearn.decomposition import PCA

from . import prom, synthetic

_BASELINE_MARGIN = pd.Timedelta(minutes=2)


# --------------------------------------------------------------------------- loading
def load_metrics(
    source: str = "auto",
    minutes: float = 60,
    step: str = "15s",
    prom_url: str | None = None,
    start: datetime | None = None,
    end: datetime | None = None,
) -> tuple[pd.DataFrame, pd.DataFrame, str]:
    """Return (metrics, fault_flags, source_used). source: 'auto' | 'prometheus' | 'synthetic'.

    ``start`` and ``end`` bound the Prometheus query. With ``start`` omitted, the query is the
    ``minutes`` before ``end`` (default: now). Synthetic data ignores both.
    """
    url = prom_url or prom.PROM_URL
    if source in ("auto", "prometheus"):
        if prom.is_up(url):
            df, faults = prom.fetch_metrics(minutes=minutes, step=step, url=url, start=start, end=end)
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


def _utc_timestamp(value: datetime | pd.Timestamp, index: pd.DatetimeIndex) -> pd.Timestamp:
    stamp = pd.Timestamp(value)
    if stamp.tzinfo is None:
        stamp = stamp.tz_localize("UTC")
    else:
        stamp = stamp.tz_convert("UTC")
    if index.tz is None:
        return stamp.tz_localize(None)
    return stamp.tz_convert(index.tz)


def _iso(value: pd.Timestamp) -> str:
    stamp = pd.Timestamp(value)
    if stamp.tzinfo is None:
        stamp = stamp.tz_localize("UTC")
    else:
        stamp = stamp.tz_convert("UTC")
    return stamp.isoformat(timespec="seconds")


def choose_baseline(
    df: pd.DataFrame,
    faults: pd.DataFrame | None = None,
    baseline_minutes: float | None = None,
    frac: float = 0.4,
    margin_samples: int = 8,
    baseline_start: datetime | pd.Timestamp | None = None,
    baseline_end: datetime | pd.Timestamp | None = None,
    margin: pd.Timedelta | None = None,
) -> pd.Series:
    """Boolean mask of 'known normal' rows used to fit PCA.

    Priority: explicit baseline_minutes from the start of the pulled window
              -> [baseline_start, baseline_end - margin) from a run manifest
              -> everything before the first injected fault (minus margin_samples)
              -> the first `frac` of the window.

    The returned series has ``attrs["baseline_rule"]`` set to ``baseline_minutes``,
    ``manifest``, ``first_fault``, or ``first_fraction``.
    """
    if margin is None:
        margin = _BASELINE_MARGIN
    mask = pd.Series(False, index=df.index)
    rule = "first_fraction"
    if baseline_minutes:
        mask[df.index < df.index[0] + pd.Timedelta(minutes=baseline_minutes)] = True
        rule = "baseline_minutes"
    elif baseline_end is not None:
        start = _utc_timestamp(baseline_start, df.index) if baseline_start is not None else df.index[0]
        end = _utc_timestamp(baseline_end, df.index) - margin
        mask[(df.index >= start) & (df.index < end)] = True
        rule = "manifest"
    elif faults is not None and faults.reindex(df.index).fillna(0).to_numpy().any():
        any_fault = faults.reindex(df.index).fillna(0).max(axis=1).to_numpy() > 0
        first = int(np.argmax(any_fault))
        mask.iloc[: max(0, first - margin_samples)] = True
        rule = "first_fault"
    if mask.sum() < 20:
        mask[:] = False
        mask.iloc[: max(20, int(len(df) * frac))] = True
        rule = "first_fraction"
    if faults is not None:  # never train on a labelled fault sample
        f = faults.reindex(df.index).fillna(0).max(axis=1) > 0
        mask = mask & ~f
    mask.attrs["baseline_rule"] = rule
    return mask


def fault_intervals(faults: pd.DataFrame) -> list[dict]:
    """Contiguous stretches where a fault gauge is on. ``end`` is the last on-sample."""
    intervals = []
    for column in faults.columns:
        on = faults[column].fillna(0).to_numpy() > 0
        if not on.any():
            continue
        kind = column.removeprefix("fault_")
        start_at = None
        for pos, flag in enumerate(on):
            if flag and start_at is None:
                start_at = pos
            elif not flag and start_at is not None:
                intervals.append({
                    "type": kind,
                    "start": _iso(faults.index[start_at]),
                    "end": _iso(faults.index[pos - 1]),
                })
                start_at = None
        if start_at is not None:
            intervals.append({
                "type": kind,
                "start": _iso(faults.index[start_at]),
                "end": _iso(faults.index[len(on) - 1]),
            })
    return intervals


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


def evaluate(
    scores: pd.DataFrame,
    faults: pd.DataFrame,
    baseline_mask: pd.Series,
    lag_samples: int = 4,
    run_end: datetime | pd.Timestamp | None = None,
) -> pd.DataFrame:
    """Detection rate per fault type and false-positive rate on non-fault, non-baseline rows.

    lag_samples dilates each fault window forward to account for rate()[1m] smearing.
    Rows after ``run_end`` are reported as ``after_run`` and stay out of the held-out normal row.
    """
    f = faults.reindex(scores.index).fillna(0).astype(bool)
    f_dil = f.rolling(lag_samples + 1, min_periods=1).max().astype(bool)
    rows = []
    for c in f.columns:
        sel = f[c].to_numpy()
        if sel.any():
            rows.append({"window": c, "samples": int(sel.sum()), "flagged_frac": float(scores["anomaly"][sel].mean())})
    any_f = f_dil.any(axis=1).to_numpy()
    labelled = f.any(axis=1).to_numpy()
    after = np.zeros(len(scores), dtype=bool)
    if run_end is not None:
        after = np.asarray(scores.index > _utc_timestamp(run_end, scores.index))
    base = baseline_mask.reindex(scores.index).fillna(False).to_numpy()
    normal = (~any_f) & (~base) & (~after)
    if normal.any():
        rows.append({"window": "normal (held-out)", "samples": int(normal.sum()), "flagged_frac": float(scores["anomaly"][normal].mean())})
    after_rows = after & (~labelled)
    if after_rows.any():
        rows.append({"window": "after_run", "samples": int(after_rows.sum()), "flagged_frac": float(scores["anomaly"][after_rows].mean())})
    rows.append({"window": "baseline (train)", "samples": int(base.sum()), "flagged_frac": float(scores["anomaly"][base].mean())})
    return pd.DataFrame(rows)


def chapter_report(scores: pd.DataFrame, chapters: list[dict]) -> list[dict]:
    """Score each manifest chapter on ``[start, end)``.

    ``seconds_to_first_flag`` is measured from the chapter start. Contributors are listed in the
    order they first appear among flagged rows in that chapter.
    """
    report = []
    for chapter in chapters:
        if not chapter.get("start") or not chapter.get("end"):
            continue
        start = _utc_timestamp(chapter["start"], scores.index)
        end = _utc_timestamp(chapter["end"], scores.index)
        window = scores[(scores.index >= start) & (scores.index < end)]
        flagged = window[window["anomaly"]] if len(window) else window
        contributors: list[dict] = []
        seen: dict[str, int] = {}
        for name in flagged["top_contributor"] if len(flagged) else []:
            if name not in seen:
                contributors.append({"name": str(name), "flagged_samples": 0})
                seen[name] = len(contributors) - 1
            contributors[seen[name]]["flagged_samples"] += 1
        seconds = None
        if len(flagged):
            seconds = float((flagged.index[0] - start).total_seconds())
        report.append({
            "name": chapter.get("name"),
            "role": chapter.get("role"),
            "start": _iso(start),
            "end": _iso(end),
            "samples": int(len(window)),
            "flagged_frac": float(flagged.shape[0] / len(window)) if len(window) else None,
            "seconds_to_first_flag": seconds,
            "contributors": contributors,
        })
    return report
