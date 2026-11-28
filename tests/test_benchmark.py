import numpy as np
import pandas as pd

from sre_pca.benchmark import compare_detectors, make_relationship_windows


def test_relationship_fault_stays_inside_baseline_ranges():
    baseline, normal, fault = make_relationship_windows()
    assert baseline.index.max() < normal.index.min() <= normal.index.max() < fault.index.min()
    assert (fault.ge(baseline.min()) & fault.le(baseline.max())).all().all()
    assert fault["app_cpu"].isin(baseline["app_cpu"]).all()

    results = compare_detectors(baseline, normal, fault).set_index(["window", "detector"])
    for detector in ("per-metric bounds", "PCA"):
        assert results.loc[("held-out normal", detector), "samples"] == len(normal) > 0
        assert results.loc[("relationship fault", detector), "samples"] == len(fault) > 0
        assert results.loc[("held-out normal", detector), "flagged_frac"] < 0.15
    assert results.loc[("relationship fault", "per-metric bounds"), "flagged_frac"] == 0
    assert results.loc[("relationship fault", "PCA"), "flagged_frac"] > 0.9


def test_detectors_keep_training_thresholds_when_scoring_new_extremes():
    baseline = pd.DataFrame({"req_rate": [1, 2, 3, 4], "app_cpu": [1, 2, 3, 4]})
    normal = pd.DataFrame({"req_rate": [1, 5, 2], "app_cpu": [1, 5, 0]})
    fault = pd.DataFrame({"req_rate": [1, 2], "app_cpu": [4, 3]})
    rows = compare_detectors(baseline, normal, fault).set_index(["window", "detector"])
    assert rows.loc[("held-out normal", "per-metric bounds"), "flagged"] == 2
    np.testing.assert_allclose(rows.loc[("held-out normal", "per-metric bounds"), "flagged_frac"], 2 / 3)
    assert rows.loc[("relationship fault", "PCA"), "flagged"] == 2
