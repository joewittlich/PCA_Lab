import numpy as np
import pandas as pd

from sre_pca import core, synthetic


def _fit():
    raw, faults = synthetic.make_synthetic()
    df = core.preprocess(raw)
    base = core.choose_baseline(df, faults)
    model = core.fit_pca(df[base])
    return df, faults, base, model


def test_pipeline_detects_injected_faults():
    df, faults, base, model = _fit()
    scores = core.score(model, df)
    ev = core.evaluate(scores, faults, base).set_index("window")["flagged_frac"]
    for c in ("fault_latency", "fault_cpu", "fault_errors"):
        assert ev[c] > 0.8, (c, ev[c])
    assert ev["normal (held-out)"] < 0.1


def test_inverse_roundtrip_in_pc_plane():
    df, faults, base, model = _fit()
    z = np.array([2.0, -1.0][: model.k])
    x = core.inverse_from_pcs(model, z)
    z_back = model.transform(x.to_frame().T).iloc[0].to_numpy()[: len(z)]
    np.testing.assert_allclose(z_back, z, atol=1e-8)


def test_origin_maps_to_baseline_mean():
    _, _, _, model = _fit()
    np.testing.assert_allclose(core.inverse_from_pcs(model, [0.0]).to_numpy(), model.mu.to_numpy())


def test_manifest_baseline_drops_the_last_two_minutes():
    index = pd.date_range("2026-11-27T19:00:00Z", periods=80, freq="15s")
    df = pd.DataFrame({"a": np.arange(len(index)), "b": np.arange(len(index)) / 2}, index=index)
    faults = pd.DataFrame(0, index=index, columns=["fault_latency"])
    faults.iloc[40:52, 0] = 1
    start, end = index[0], index[40]
    mask = core.choose_baseline(df, faults, baseline_start=start, baseline_end=end)
    assert mask.attrs["baseline_rule"] == "manifest"
    assert mask.sum() == 32  # 10 minutes of samples, minus the last 2 minutes
    assert mask.to_numpy()[0]
    assert not mask.to_numpy()[32]
    assert not mask.to_numpy()[40]


def test_short_manifest_baseline_falls_back():
    index = pd.date_range("2026-11-27T19:00:00Z", periods=80, freq="15s")
    df = pd.DataFrame({"a": np.arange(len(index), dtype=float)}, index=index)
    faults = pd.DataFrame(0, index=index, columns=["fault_latency"])
    mask = core.choose_baseline(df, faults, baseline_start=index[0], baseline_end=index[4])
    assert mask.attrs["baseline_rule"] == "first_fraction"
    assert mask.sum() >= 20


def test_fault_intervals_and_after_run():
    index = pd.date_range("2026-11-27T19:00:00Z", periods=20, freq="1min")
    faults = pd.DataFrame(0, index=index, columns=["fault_latency", "fault_cpu"])
    faults.iloc[8:11, 0] = 1
    scores = pd.DataFrame({"anomaly": False, "recon_error": 0.0}, index=index)
    scores.loc[index[8:11], "anomaly"] = True
    baseline = pd.Series(False, index=index)
    baseline.iloc[:6] = True
    ev = core.evaluate(scores, faults, baseline, run_end=index[14]).set_index("window")
    assert ev.loc["fault_latency", "samples"] == 3
    assert ev.loc["after_run", "samples"] == 5
    assert ev.loc["normal (held-out)", "samples"] == 2  # the two samples between the baseline and the dilated fault
    intervals = core.fault_intervals(faults)
    assert intervals == [{
        "type": "latency",
        "start": "2026-11-27T19:08:00+00:00",
        "end": "2026-11-27T19:10:00+00:00",
    }]
