"""Reproduce the three synthetic cases in the offline on-call lesson.

Run from the repository root: uv run python -m sre_pca.prediction_exercises
The CPU and request-rate data come from the fixed-seed relationship benchmark.
"""

import numpy as np
import pandas as pd

from . import benchmark, core


def equal_distance_points(model: core.PCAModel) -> pd.DataFrame:
    """Move 2.6 standardized units along and across the two-feature training line."""
    along = model.W[:, 0].copy()
    if along[0] < 0:  # Pick the direction of increasing request rate; PCA axis signs are arbitrary.
        along *= -1
    across = np.array([-along[1], along[0]])
    points = model.mu.to_numpy() + 2.6 * np.stack([along, across]) * model.sigma.to_numpy()
    return pd.DataFrame(points, columns=model.columns, index=["along", "across"])


def run_exercises() -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    baseline, healthy, replay = benchmark.make_relationship_windows()
    # Match the benchmark's zero training flags and use a separate evaluation period.
    clean = core.fit_pca(baseline, n_components=1, threshold_quantile=1.0)
    points = equal_distance_points(clean)
    geometry = points.join(core.score(clean, points)[["recon_error", "anomaly"]])
    geometry["threshold"] = clean.threshold
    geometry["training_max_req_rate"] = baseline["req_rate"].max()

    altered = baseline.copy()
    altered.loc[altered.index[::10], "app_cpu"] += 0.28
    refitted = core.fit_pca(altered, n_components=1, threshold_quantile=1.0)
    comparisons = []
    for label, model in (("original", clean), ("altered", refitted)):
        for window, rows in (("healthy", healthy), ("replay", replay)):
            flagged = core.score(model, rows)["anomaly"]
            comparisons.append((label, model.threshold, window, len(rows), int(flagged.sum())))
    training = pd.DataFrame(comparisons, columns=["baseline", "threshold", "window", "samples", "flagged"])

    # Successive observations get new collection times while their values stay fixed.
    frozen = pd.concat([healthy.iloc[[0]]] * 20, ignore_index=True)
    frozen.index = pd.date_range("2020-01-01", periods=len(frozen), freq="15s", tz="UTC")
    return geometry, training, frozen.join(core.score(clean, frozen)[["recon_error", "anomaly"]])


if __name__ == "__main__":
    geometry, training, frozen = run_exercises()
    print("Equal distance from the training mean (scores and readings rounded)")
    print(geometry.to_string(float_format="{:.5f}".format))
    print("\nSame evaluation windows, two training baselines")
    print(training.to_string(index=False, float_format="{:.5f}".format))
    print(f"\nRepeated readings: {int(frozen['anomaly'].sum())} of {len(frozen)} samples flagged")
    print(frozen.iloc[[0, -1]].to_string(float_format="{:.5f}".format))
