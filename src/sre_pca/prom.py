"""Pull aligned metric time series from the Prometheus HTTP API into pandas."""

from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone

import numpy as np
import pandas as pd
import requests

PROM_URL = os.getenv("PROM_URL", "http://localhost:9090")

_RATE = "[1m]"
_APP = 'job="demo-app"'

# One PromQL expression per descriptor. Each must return a single series (aggregate if needed).
DEFAULT_QUERIES: dict[str, str] = {
    "req_rate": f"sum(rate(http_requests_total{{{_APP}}}{_RATE}))",
    "error_ratio": (
        f'sum(rate(http_requests_total{{{_APP},status=~"5.."}}{_RATE}))'
        f" / clamp_min(sum(rate(http_requests_total{{{_APP}}}{_RATE})), 1e-9)"
    ),
    "lat_p50": f"histogram_quantile(0.50, sum by (le) (rate(http_request_duration_seconds_bucket{{{_APP}}}{_RATE})))",
    "lat_p95": f"histogram_quantile(0.95, sum by (le) (rate(http_request_duration_seconds_bucket{{{_APP}}}{_RATE})))",
    "lat_mean": (
        f"sum(rate(http_request_duration_seconds_sum{{{_APP}}}{_RATE}))"
        f" / clamp_min(sum(rate(http_request_duration_seconds_count{{{_APP}}}{_RATE})), 1e-9)"
    ),
    "inflight": f"avg_over_time(http_requests_in_flight{{{_APP}}}{_RATE})",
    "app_cpu": f"rate(process_cpu_seconds_total{{{_APP}}}{_RATE})",
    "app_rss_mb": f"process_resident_memory_bytes{{{_APP}}} / 1e6",
    "node_cpu_busy": f'1 - avg(rate(node_cpu_seconds_total{{mode="idle"}}{_RATE}))',
    "node_load1": "max(node_load1)",
    "node_mem_used_frac": "max(1 - node_memory_MemAvailable_bytes / node_memory_MemTotal_bytes)",
}

FAULT_QUERY = f"max by (type) (demo_fault_active{{{_APP}}})"


def is_up(url: str = PROM_URL, timeout: float = 2.0) -> bool:
    try:
        return requests.get(f"{url}/-/ready", timeout=timeout).ok
    except requests.RequestException:
        return False


def query_range(expr: str, start: datetime, end: datetime, step: str = "15s", url: str = PROM_URL) -> list[dict]:
    r = requests.get(
        f"{url}/api/v1/query_range",
        params={"query": expr, "start": start.timestamp(), "end": end.timestamp(), "step": step},
        timeout=30,
    )
    r.raise_for_status()
    body = r.json()
    if body.get("status") != "success":
        raise RuntimeError(f"Prometheus error for {expr!r}: {body}")
    return body["data"]["result"]


def _to_series(result: list[dict], name: str) -> pd.Series:
    if not result:
        return pd.Series(dtype=float, name=name)
    if len(result) > 1:
        raise ValueError(f"query for {name!r} returned {len(result)} series; aggregate it to one")
    vals = np.array(result[0]["values"], dtype=object)
    idx = pd.to_datetime(vals[:, 0].astype(float), unit="s", utc=True)
    data = pd.to_numeric(pd.Series(vals[:, 1]), errors="coerce").replace([np.inf, -np.inf], np.nan).to_numpy()
    return pd.Series(data, index=idx, name=name)


def fetch_metrics(
    minutes: float = 60,
    step: str = "15s",
    end: datetime | None = None,
    queries: dict[str, str] | None = None,
    url: str = PROM_URL,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Return (metrics, faults): two DataFrames on the same UTC time index.

    faults has one 0/1 column per injected fault type (fault_latency, fault_cpu, fault_errors)."""
    queries = queries or DEFAULT_QUERIES
    end = end or datetime.now(timezone.utc)
    start = end - timedelta(minutes=minutes)
    cols = {name: _to_series(query_range(q, start, end, step, url), name) for name, q in queries.items()}
    df = pd.DataFrame(cols).sort_index()

    fault_cols = {}
    for series in query_range(FAULT_QUERY, start, end, step, url):
        ftype = series["metric"].get("type", "unknown")
        fault_cols[f"fault_{ftype}"] = _to_series([series], f"fault_{ftype}")
    faults = pd.DataFrame(fault_cols).reindex(df.index).fillna(0).astype(int)
    for c in ("fault_latency", "fault_cpu", "fault_errors"):
        if c not in faults:
            faults[c] = 0
    return df, faults[sorted(faults.columns)]
