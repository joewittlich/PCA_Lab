"""Offline comparison of per-metric bounds and PCA on a request-rate/CPU relationship fault."""

import pandas as pd

from . import core, synthetic


def make_relationship_windows() -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """Return chronological training, held-out healthy, and CPU replay windows."""
    samples_per_minute = 4
    raw, _ = synthetic.make_synthetic(minutes=110, step_s=15, seed=7, faults=[])
    metrics = raw[["req_rate", "app_cpu"]].reset_index(drop=True)
    baseline = metrics.iloc[:60 * samples_per_minute]
    normal = metrics.iloc[60 * samples_per_minute:105 * samples_per_minute]
    fault = metrics.iloc[105 * samples_per_minute:].copy()
    # Replay healthy peak-load CPU while the later window's traffic is falling.
    peak = baseline.iloc[5 * samples_per_minute:10 * samples_per_minute]
    fault["app_cpu"] = peak["app_cpu"].to_numpy()
    return baseline, normal, fault


def compare_detectors(baseline: pd.DataFrame, normal: pd.DataFrame, fault: pd.DataFrame) -> pd.DataFrame:
    """Fit once on shared baseline rows and count row-level alarms in each evaluation window."""
    lower, upper = baseline.min(), baseline.max()
    model = core.fit_pca(baseline, n_components=1, threshold_quantile=1.0)
    rows = []
    for window, data in (("held-out normal", normal), ("relationship fault", fault)):
        outside_bounds = ((data < lower) | (data > upper)).any(axis=1)
        for detector, alerts in (("per-metric bounds", outside_bounds), ("PCA", core.score(model, data)["anomaly"])):
            rows.append({
                "window": window,
                "detector": detector,
                "samples": len(data),
                "flagged": int(alerts.sum()),
                "flagged_frac": float(alerts.mean()),
            })
    return pd.DataFrame(rows)


if __name__ == "__main__":
    results = compare_detectors(*make_relationship_windows())
    print(results.to_string(index=False, formatters={"flagged_frac": "{:.1%}".format}))
