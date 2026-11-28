"""`sre-pca-exporter` - NEXT STEP: publish the live anomaly score back to Prometheus.

Fits PCA on a recent window (assumed normal), then every --interval seconds scores the newest
sample and exposes it at http://<host>:9105/metrics as:
  sre_pca_reconstruction_error, sre_pca_threshold, sre_pca_anomaly, sre_pca_pc_score{pc="PC1"...}
  sre_pca_last_scored_timestamp_seconds (Unix time of the last complete input row scored)
Uncomment the `sre-pca-anomaly` job in config/prometheus/prometheus.yml, reload Prometheus,
and the Grafana dashboard's "PCA anomaly score" panel lights up. Alert on it like any metric.
"""

from __future__ import annotations

import argparse
import time

import numpy as np
from prometheus_client import Gauge, start_http_server

from . import core, prom


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="sre-pca-exporter", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--port", type=int, default=9105)
    p.add_argument("--train-minutes", type=float, default=30, help="recent window treated as normal baseline")
    p.add_argument("--interval", type=float, default=15)
    p.add_argument("--refit-every", type=float, default=0, help="minutes between refits (0 = never)")
    p.add_argument("--prom-url", default=prom.PROM_URL)
    p.add_argument("--once", action="store_true", help="score once, print, exit (for testing)")
    a = p.parse_args(argv)

    def fit():
        raw, faults = prom.fetch_metrics(minutes=a.train_minutes, url=a.prom_url)
        df = core.preprocess(raw)
        base = core.choose_baseline(df, faults, baseline_minutes=a.train_minutes)
        return core.fit_pca(df[base]), df.columns

    model, cols = fit()
    err_g = Gauge("sre_pca_reconstruction_error", "PCA reconstruction error (SPE) of the latest sample")
    thr_g = Gauge("sre_pca_threshold", "Anomaly threshold (baseline quantile)")
    an_g = Gauge("sre_pca_anomaly", "1 if latest sample exceeds threshold")
    pc_g = Gauge("sre_pca_pc_score", "Latest PC score", ["pc"])
    last_scored_g = Gauge(
        "sre_pca_last_scored_timestamp_seconds",
        "Unix timestamp of the last complete input row scored, or 0 before the first score",
    )
    if not a.once:
        start_http_server(a.port)
        print(f"serving on :{a.port}/metrics (k={model.k}, threshold={model.threshold:.3f})")
    last_fit = time.time()
    while True:
        raw, _ = prom.fetch_metrics(minutes=3, url=a.prom_url)
        # A filled gap would give an old measurement a new timestamp.
        latest = raw.reindex(columns=cols).replace([np.inf, -np.inf], np.nan).dropna().sort_index().tail(1)
        if not latest.empty:
            s = core.score(model, latest)
            err = float(s["recon_error"].iloc[-1])
            err_g.set(err)
            thr_g.set(model.threshold)
            an_g.set(int(err > model.threshold))
            for name, v in model.transform(latest).iloc[-1].items():
                pc_g.labels(name).set(float(v))
            last_scored_g.set(latest.index[-1].timestamp())
            print(f"recon_error={err:.3f} threshold={model.threshold:.3f} top={s['top_contributor'].iloc[-1]}")
        if a.once:
            return 0
        if a.refit_every and time.time() - last_fit > a.refit_every * 60:
            model, cols = fit()
            last_fit = time.time()
        time.sleep(a.interval)


if __name__ == "__main__":
    raise SystemExit(main())
