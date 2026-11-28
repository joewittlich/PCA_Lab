"""Run manifests: load and scenario metadata, and the analysis window they select."""

import json
from datetime import datetime, timedelta, timezone

import numpy as np
import pandas as pd

from sre_pca import cli, core, runs, scenario

T0 = datetime(2026, 11, 27, 19, 0, tzinfo=timezone.utc)


def _clock(start):
    state = {"t": start}

    def now():
        return state["t"]

    def sleep(minutes, _label):
        state["t"] = state["t"] + timedelta(minutes=minutes)

    return now, sleep


def test_duration_and_load_manifest(tmp_path):
    assert runs.parse_duration("40m") == timedelta(minutes=40)
    assert runs.parse_duration("1h30m") == timedelta(minutes=90)
    manifest = runs.begin_load("40m", "20", tmp_path, now=T0)
    assert manifest["run_id"] == "20261127T190000Z"
    assert manifest["load"]["end"] == "2026-11-27T19:40:00+00:00"
    assert manifest["load"]["rps"] == 20
    saved = json.loads((tmp_path / "20261127T190000Z.json").read_text(encoding="utf-8"))
    assert saved["load"]["duration"] == "40m"
    assert (tmp_path / "latest").read_text(encoding="utf-8").strip() == manifest["run_id"]
    assert (tmp_path / "active-load").read_text(encoding="utf-8").strip() == manifest["run_id"]


def test_scenario_attaches_to_the_load_and_records_bounds(tmp_path):
    runs.begin_load("40m", 20, tmp_path, now=T0)
    now, sleep = _clock(T0 + timedelta(minutes=2))
    calls = []

    def set_fault(kind, value=None):
        calls.append((kind, value))
        return {}

    manifest = scenario.run_scenario(
        baseline_min=10, fault_min=3, gap_min=3, runs_dir=tmp_path,
        sleep=sleep, now=now, set_fault=set_fault,
    )
    assert manifest["run_id"] == "20261127T190000Z"
    assert manifest["scenario"]["start"] == "2026-11-27T19:02:00+00:00"
    assert manifest["scenario"]["baseline_end"] == "2026-11-27T19:12:00+00:00"
    assert manifest["scenario"]["end"] == "2026-11-27T19:30:00+00:00"
    assert manifest["scenario"]["status"] == "done"
    assert calls[0] == ("reset", None)
    assert ("latency", "300") in calls
    start, end = runs.query_window(manifest)
    assert start == T0 - timedelta(minutes=2)
    assert end == datetime(2026, 11, 27, 19, 32, tzinfo=timezone.utc)
    bounds = runs.baseline_bounds(manifest)
    assert bounds == (T0, datetime(2026, 11, 27, 19, 12, tzinfo=timezone.utc))


def test_second_scenario_copies_an_active_load(tmp_path):
    runs.begin_load("40m", 20, tmp_path, now=T0)
    now, sleep = _clock(T0 + timedelta(minutes=1))

    def set_fault(kind, value=None):
        return {}

    first = scenario.run_scenario(
        baseline_min=1, fault_min=1, gap_min=1, runs_dir=tmp_path,
        sleep=sleep, now=now, set_fault=set_fault,
    )
    second = runs.begin_scenario(tmp_path, now())
    assert second["run_id"] != first["run_id"]
    assert second["load"]["start"] == first["load"]["start"]
    assert second["scenario"]["status"] == "running"
    finished = runs.finish_load(tmp_path, now=now())
    assert finished == first["run_id"]
    again = runs.read_manifest(tmp_path / f"{second['run_id']}.json")
    assert again["load"]["actual_end"] == runs.iso(now())


def test_interrupted_scenario_keeps_an_end_time(tmp_path):
    now, sleep = _clock(T0)

    def set_fault(kind, value=None):
        return {}

    def boom(_minutes, _label):
        raise KeyboardInterrupt

    try:
        scenario.run_scenario(
            baseline_min=10, fault_min=3, gap_min=3, runs_dir=tmp_path,
            sleep=boom, now=now, set_fault=set_fault,
        )
    except KeyboardInterrupt:
        pass
    manifest = runs.latest_manifest(tmp_path)
    assert manifest["scenario"]["status"] == "interrupted"
    assert manifest["scenario"]["end"] == runs.iso(T0)


def test_analyze_run_uses_the_manifest_window(tmp_path, monkeypatch, capsys):
    load = runs.begin_load("40m", 20, tmp_path, now=T0)
    scenario_start = T0 + timedelta(minutes=2)
    manifest = runs.begin_scenario(tmp_path, scenario_start)
    runs.record_event(manifest, "baseline start", tmp_path, now=scenario_start)
    fault_at = T0 + timedelta(minutes=12)
    runs.record_event(manifest, "fault latency=300 ON", tmp_path, now=fault_at)
    done = T0 + timedelta(minutes=30)
    runs.record_event(manifest, "scenario done", tmp_path, now=done)
    captured = {}

    def fetch_metrics(minutes=60, step="15s", end=None, queries=None, url=None, start=None):
        captured["start"] = start
        captured["end"] = end
        index = pd.date_range(start, end, freq="15s", inclusive="both")
        rng = np.random.default_rng(0)
        frame = pd.DataFrame({f"m{i}": rng.normal(size=len(index)) + i * 0.1 for i in range(4)}, index=index)
        faults = pd.DataFrame(0, index=index, columns=["fault_cpu", "fault_errors", "fault_latency"])
        faults.loc[(index >= fault_at) & (index < fault_at + timedelta(minutes=3)), "fault_latency"] = 1
        return frame, faults

    monkeypatch.setattr(core.prom, "is_up", lambda url, timeout=2.0: True)
    monkeypatch.setattr(core.prom, "fetch_metrics", fetch_metrics)
    reports = tmp_path / "out"
    code = cli.main([
        "--source", "prometheus", "--run", "latest", "--runs-dir", str(tmp_path), "--reports-dir", str(reports),
    ])
    assert code == 0
    assert captured["start"] == T0 - timedelta(minutes=2)
    assert captured["end"] == done + timedelta(minutes=2)
    summary = json.loads((reports / "summary.json").read_text(encoding="utf-8"))
    assert summary["source"] == "prometheus"
    assert summary["run_id"] == load["run_id"]
    assert summary["baseline_rule"] == "manifest"
    assert summary["query_start"] == "2026-11-27T18:58:00+00:00"
    assert summary["query_end"] == "2026-11-27T19:32:00+00:00"
    assert summary["baseline_start"] == "2026-11-27T19:00:00+00:00"
    assert summary["baseline_end"] < "2026-11-27T19:10:00+00:00"
    assert summary["fault_intervals"][0]["type"] == "latency"
    windows = {row["window"]: row["samples"] for row in summary["detection"]}
    assert windows["after_run"] > 0
    assert "run_id=" in capsys.readouterr().out


def test_minutes_lookback_still_ends_at_now(tmp_path):
    before = runs.utcnow()
    reports = tmp_path / "out"
    assert cli.main(["--source", "synthetic", "--minutes", "30", "--reports-dir", str(reports)]) == 0
    after = runs.utcnow()
    summary = json.loads((reports / "summary.json").read_text(encoding="utf-8"))
    assert summary["run_id"] is None
    assert summary["baseline_rule"] == "first_fault"
    query_end = runs.parse_time(summary["query_end"])
    query_start = runs.parse_time(summary["query_start"])
    assert before - timedelta(seconds=2) <= query_end <= after + timedelta(seconds=2)
    assert query_end - query_start == timedelta(minutes=30)
