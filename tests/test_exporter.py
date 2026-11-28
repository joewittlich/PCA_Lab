from functools import partial

import numpy as np
import pytest
from prometheus_client import CollectorRegistry, Gauge

from sre_pca import exporter, synthetic


def test_last_scored_timestamp_tracks_complete_input(monkeypatch):
    raw, flags = synthetic.make_synthetic()
    good = raw.iloc[120:132]
    missing = raw.iloc[132:144].drop(columns="lat_p95")
    partial_window = good.copy()
    partial_window.loc[partial_window.index[-1], "lat_p95"] = np.nan
    partial_window.loc[partial_window.index[-2], "app_cpu"] = np.inf
    recovered = raw.iloc[144:156]
    windows = iter([raw.iloc[:120], missing, partial_window, good, missing, recovered])
    registry = CollectorRegistry()
    observed = []
    scores = []

    def fetch(**kwargs):
        frame = next(windows)
        return frame, flags.loc[frame.index]

    def observe(_interval):
        observed.append(registry.get_sample_value("sre_pca_last_scored_timestamp_seconds"))
        scores.append([
            sample for metric in registry.collect() for sample in metric.samples
            if sample.name != "sre_pca_last_scored_timestamp_seconds"
        ])

    monkeypatch.setattr(exporter.prom, "fetch_metrics", fetch)
    monkeypatch.setattr(exporter, "Gauge", partial(Gauge, registry=registry))
    monkeypatch.setattr(exporter, "start_http_server", lambda port: None)
    monkeypatch.setattr(exporter.time, "sleep", observe)
    with pytest.raises(StopIteration):
        exporter.main([])

    assert observed == [
        0,
        good.index[-3].timestamp(),
        good.index[-1].timestamp(),
        good.index[-1].timestamp(),
        recovered.index[-1].timestamp(),
    ]
    assert scores[2] == scores[3]
    assert scores[3] != scores[4]
