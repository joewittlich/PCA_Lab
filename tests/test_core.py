import numpy as np

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
