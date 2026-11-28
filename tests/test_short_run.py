"""Live five-minute lab session.

Drives k6, the scripted faults, and ``sre-pca --run`` against the Docker stack, then writes the
record to ``reports/short-run/``. Everyday ``pytest`` skips it. Run it with the stack already up:

    uv run pytest -m short_run
    ./scripts/lab.sh test-short
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import threading
import time
import urllib.parse
import urllib.request
from datetime import timedelta
from pathlib import Path

import pandas as pd
import pytest

from sre_pca import cli, runs, scenario
from sre_pca.fault import set_fault

pytestmark = pytest.mark.short_run

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "reports" / "short-run"
RUNS = ROOT / "reports" / "runs"
APP = os.getenv("APP_URL", "http://localhost:8000")
PROM = os.getenv("PROM_URL", "http://localhost:9090")

# 180s baseline + three faults of 24s with 16s gaps = 300s.
BASELINE_S = 180
FAULT_S = 24
GAP_S = 16
PLANNED_S = BASELINE_S + 3 * (FAULT_S + GAP_S)
BASELINE_MIN = BASELINE_S / 60
FAULT_MIN = FAULT_S / 60
GAP_MIN = GAP_S / 60


def _get_json(url: str, params: dict | None = None) -> dict:
    if params:
        url = f"{url}?{urllib.parse.urlencode(params)}"
    with urllib.request.urlopen(url, timeout=5) as response:
        return json.loads(response.read().decode())


def _require_stack() -> list[dict]:
    try:
        health = _get_json(f"{APP}/healthz")
        ready = urllib.request.urlopen(f"{PROM}/-/ready", timeout=5)
        ready_status = ready.status
        ready.close()
    except OSError as exc:
        pytest.fail(f"Lab stack is not reachable ({exc}). Start it with scripts/lab.ps1 up or scripts/lab.sh up")
    assert health.get("ok") is True
    assert ready_status == 200
    payload = _get_json(f"{PROM}/api/v1/targets")
    targets = payload["data"]["activeTargets"]
    demo = [row for row in targets if row["labels"].get("job") == "demo-app"]
    assert demo and demo[0]["health"] == "up", "Prometheus is not scraping demo-app"
    return targets


def _compose(*args: str, check: bool = True) -> None:
    subprocess.run(["docker", "compose", *args], cwd=ROOT, check=check)


def _stop_k6() -> None:
    _compose("--profile", "load", "stop", "k6", check=False)
    _compose("--profile", "load", "rm", "-f", "k6", check=False)


def _start_k6() -> None:
    env = os.environ.copy()
    env["LOAD_DURATION"] = "6m"
    env["LOAD_RPS"] = "20"
    subprocess.run(
        ["docker", "compose", "--profile", "load", "up", "-d", "k6"],
        cwd=ROOT, check=True, env=env,
    )


def _k6_running() -> bool:
    result = subprocess.run(
        ["docker", "inspect", "-f", "{{.State.Running}}", "k6"],
        cwd=ROOT, capture_output=True, text=True, check=False,
    )
    return result.returncode == 0 and result.stdout.strip() == "true"


def _request_count() -> float:
    payload = _get_json(f"{PROM}/api/v1/query", {"query": 'sum(http_requests_total{job="demo-app"})'})
    result = payload["data"]["result"]
    if not result:
        return 0.0
    return float(result[0]["value"][1])


def _wait_for_traffic() -> float:
    started = _request_count()
    deadline = time.time() + 45
    while time.time() < deadline:
        if _k6_running() and _request_count() >= started + 10:
            return _request_count() - started
        time.sleep(2)
    pytest.fail("k6 did not raise the demo-app request count within 45s")


def _watch_faults(observations: list[dict], stop: threading.Event) -> None:
    while not stop.is_set():
        stamp = runs.iso(runs.utcnow())
        try:
            state = set_fault("status")
        except Exception as exc:  # keep the session going if one poll fails
            observations.append({"time": stamp, "error": str(exc)})
        else:
            observations.append({"time": stamp, **state})
        stop.wait(2)


def _assert_summary(summary: dict, manifest: dict) -> None:
    assert summary["source"] == "prometheus"
    assert summary["run_id"] == manifest["run_id"]
    assert summary["rows"] >= 20
    assert isinstance(summary["k"], int) and summary["k"] > 0
    assert summary["threshold"] >= 0
    ratios = summary["explained_variance_ratio"]
    assert len(ratios) >= summary["k"]
    assert all(0 <= value <= 1 for value in ratios)
    assert summary["detection"]
    for row in summary["detection"]:
        assert row["window"]
        assert 0 <= row["samples"] <= summary["rows"]
        assert 0 <= row["flagged_frac"] <= 1
    assert summary["baseline_rule"] in {"manifest", "first_fault", "first_fraction", "baseline_minutes"}
    scenario_block = manifest["scenario"]
    assert runs.parse_time(summary["query_start"]) <= runs.parse_time(manifest["load"]["start"])
    assert runs.parse_time(summary["query_end"]) >= runs.parse_time(scenario_block["end"])
    assert runs.parse_time(summary["data_start"]) <= runs.parse_time(scenario_block["start"])


def test_five_minute_lab_run():
    """Run load and the three faults for five minutes, then analyze that manifest."""
    assert PLANNED_S == 300
    targets = _require_stack()
    if OUT.exists():
        shutil.rmtree(OUT)
    OUT.mkdir(parents=True)
    record: dict = {
        "test": "tests/test_short_run.py::test_five_minute_lab_run",
        "planned_minutes": PLANNED_S / 60,
        "schedule": {"baseline_min": BASELINE_MIN, "fault_min": FAULT_MIN, "gap_min": GAP_MIN},
        "prometheus_targets": [
            {"job": row["labels"].get("job"), "health": row["health"]} for row in targets
        ],
    }
    manifest = None
    try:
        _stop_k6()
        manifest = runs.begin_load("6m", 20, RUNS)
        record["run_id"] = manifest["run_id"]
        record["started"] = manifest["load"]["start"]
        _start_k6()
        record["requests_during_warmup"] = _wait_for_traffic()
        observations: list[dict] = []
        stop = threading.Event()
        watcher = threading.Thread(target=_watch_faults, args=(observations, stop), daemon=True)
        watcher.start()
        try:
            manifest = scenario.run_scenario(
                baseline_min=BASELINE_MIN,
                fault_min=FAULT_MIN,
                gap_min=GAP_MIN,
                runs_dir=RUNS,
                sleep=scenario._sleep,
                now=runs.utcnow,
                set_fault=set_fault,
            )
        finally:
            stop.set()
            watcher.join(timeout=5)
        record["fault_observations"] = observations
        record["manifest"] = json.loads((RUNS / f"{manifest['run_id']}.json").read_text(encoding="utf-8"))
        manifest = record["manifest"]
        code = cli.main([
            "--source", "prometheus",
            "--run", manifest["run_id"],
            "--runs-dir", str(RUNS),
            "--reports-dir", str(OUT),
            "--step", "5s",
        ])
        assert code == 0
        summary = json.loads((OUT / "summary.json").read_text(encoding="utf-8"))
        record["summary"] = summary
        record["finished"] = runs.iso(runs.utcnow())
        (OUT / "record.json").write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")

        events = [event for _, event in manifest["events"]]
        assert events == [
            "baseline start",
            "fault latency=300 ON",
            "fault latency OFF",
            "fault cpu=on ON",
            "fault cpu OFF",
            "fault errors=0.2 ON",
            "fault errors OFF",
            "scenario done",
        ]
        assert manifest["scenario"]["status"] == "done"
        assert manifest["scenario"]["baseline_end"] == manifest["events"][1][0]
        elapsed = runs.parse_time(manifest["scenario"]["end"]) - runs.parse_time(manifest["scenario"]["start"])
        assert timedelta(seconds=PLANNED_S - 2) <= elapsed <= timedelta(seconds=PLANNED_S + 45)
        assert any(float(row.get("latency_ms") or 0) > 0 for row in observations)
        assert any(row.get("cpu_on") is True for row in observations)
        assert any(float(row.get("error_rate") or 0) > 0 for row in observations)
        final = set_fault("status")
        assert float(final["latency_ms"]) == 0
        assert final["cpu_on"] is False
        assert float(final["error_rate"]) == 0
        _assert_summary(summary, manifest)
        scores = pd.read_csv(OUT / "scores.csv", index_col=0)
        assert list(scores.columns[:3]) == ["recon_error", "top_contributor", "anomaly"]
        assert set(scores.columns[3:]) >= {"fault_cpu", "fault_errors", "fault_latency"}
        assert all(column.startswith("fault_") for column in scores.columns[3:])
        assert len(scores) == summary["rows"]
        for column in ("fault_latency", "fault_cpu", "fault_errors"):
            assert int(scores[column].sum()) > 0, column
        for name in ("pca_scree_scatter.png", "recon_error.png", "raw_metrics.png", "scores.csv", "summary.json"):
            artifact = OUT / name
            assert artifact.is_file() and artifact.stat().st_size > 0, name
    finally:
        if "summary" not in record:
            record["finished"] = runs.iso(runs.utcnow())
            OUT.mkdir(parents=True, exist_ok=True)
            (OUT / "record.json").write_text(json.dumps(record, indent=2, default=str) + "\n", encoding="utf-8")
        try:
            set_fault("reset")
        except OSError:
            pass
        if manifest is not None:
            runs.finish_load(RUNS, manifest["run_id"])
        _stop_k6()
