"""Synthetic SRE metrics with the same columns as prom.DEFAULT_QUERIES, for offline experiments."""

from __future__ import annotations

import numpy as np
import pandas as pd

# (start_minute, duration_minutes, fault_type)
DEFAULT_FAULTS = [(60, 10, "latency"), (85, 10, "cpu"), (110, 10, "errors")]


def make_synthetic(
    minutes: int = 135,
    step_s: int = 15,
    seed: int = 7,
    faults: list[tuple[float, float, str]] | None = None,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    rng = np.random.default_rng(seed)
    n = int(minutes * 60 / step_s)
    t = np.arange(n) * step_s
    idx = pd.date_range(end=pd.Timestamp.now(tz="UTC").floor("s"), periods=n, freq=f"{step_s}s")

    # latent "load" driver: slow wave + random walk + noise
    load = 20 * (1 + 0.5 * np.sin(2 * np.pi * t / 1800)) + np.cumsum(rng.normal(0, 0.15, n)) + rng.normal(0, 1, n)
    load = np.clip(load, 2, None)

    flags = {k: np.zeros(n, dtype=int) for k in ("latency", "cpu", "errors")}
    for start_m, dur_m, kind in DEFAULT_FAULTS if faults is None else faults:
        a, b = int(start_m * 60 / step_s), int((start_m + dur_m) * 60 / step_s)
        flags[kind][a:b] = 1

    lat_extra = 0.3 * flags["latency"] + 0.05 * flags["cpu"]
    cpu_extra = 1.6 * flags["cpu"]
    err_extra = 0.2 * flags["errors"]

    lat_p50 = 0.012 + 0.0004 * load + lat_extra + rng.normal(0, 0.001, n)
    lat_p95 = 0.025 + 0.0012 * load + 1.3 * lat_extra + rng.normal(0, 0.003, n)
    lat_mean = 0.015 + 0.0006 * load + lat_extra + rng.normal(0, 0.0015, n)
    req_rate = load + rng.normal(0, 0.5, n)
    df = pd.DataFrame(
        {
            "req_rate": req_rate,
            "error_ratio": np.clip(0.002 + err_extra + rng.normal(0, 0.001, n), 0, 1),
            "lat_p50": lat_p50,
            "lat_p95": lat_p95,
            "lat_mean": lat_mean,
            "inflight": req_rate * lat_mean + rng.normal(0, 0.05, n),  # Little's law
            "app_cpu": 0.01 * load + cpu_extra + rng.normal(0, 0.01, n),
            "app_rss_mb": 80 + 0.3 * load + rng.normal(0, 0.5, n),
            "node_cpu_busy": np.clip(0.05 + 0.006 * load + 0.2 * flags["cpu"] + rng.normal(0, 0.01, n), 0, 1),
            "node_load1": 0.3 + 0.03 * load + 2 * flags["cpu"] + rng.normal(0, 0.05, n),
            "node_mem_used_frac": 0.4 + 0.001 * load + rng.normal(0, 0.002, n),
        },
        index=idx,
    )
    faults_df = pd.DataFrame({f"fault_{k}": v for k, v in sorted(flags.items())}, index=idx)
    return df, faults_df
