"""The three-hour session: chapter plan, fault order, and per-chapter scores."""

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


def test_long_profile_is_three_hours_and_keeps_the_opening_faults(tmp_path):
    chapters = scenario.long_chapters()
    assert [chapter.name for chapter in chapters] == [
        "baseline", "latency", "recovery-latency", "cpu", "recovery-cpu", "errors", "recovery-errors",
        "retry-ramp", "downstream-timeout", "leak", "leak-held", "healthy-after-leak",
    ]
    assert sum(chapter.minutes for chapter in chapters) == 180
    assert chapters[0].role == "baseline" and chapters[0].minutes == 30
    assert chapters[-2].role == "level_shift" and chapters[-1].role == "level_shift"

    now, sleep = _clock(T0)
    calls = []

    def set_fault(kind, value=None):
        calls.append((kind, value))
        return {}

    manifest = scenario.run_scenario(
        baseline_min=10, fault_min=3, gap_min=3, runs_dir=tmp_path,
        sleep=sleep, now=now, set_fault=set_fault, profile="long",
    )
    assert manifest["scenario"]["status"] == "done"
    assert manifest["scenario"]["start"] == "2026-11-27T19:00:00+00:00"
    assert manifest["scenario"]["baseline_end"] == "2026-11-27T19:30:00+00:00"
    assert manifest["scenario"]["end"] == "2026-11-27T22:00:00+00:00"
    assert [chapter["name"] for chapter in manifest["chapters"]] == [chapter.name for chapter in chapters]
    assert manifest["chapters"][0]["end"] == "2026-11-27T19:30:00+00:00"
    assert manifest["chapters"][-1]["end"] == manifest["scenario"]["end"]
    assert manifest["plan"][7]["name"] == "retry-ramp"
    assert manifest["plan"][7]["offset_min"] == 75

    events = [event for _, event in manifest["events"]]
    assert "baseline start" in events
    assert "chapter retry-ramp start" in events
    assert events[-2] == "scenario done"
    assert events[-1] == "fault leak released"
    assert ("retries", "2") in calls
    assert ("client_retries", "1") in calls
    assert ("downstream", "2000") in calls
    assert ("timeout", "1000") in calls
    assert ("leak", "64") in calls
    assert ("leak", "0") in calls
    assert calls[-1] == ("leak_release", None)
    errors = [float(value) for kind, value in calls if kind == "errors"]
    assert errors[0] == 0.2
    assert errors[1] == 0.05
    assert errors[-1] == 0.85
    assert errors[1:] == sorted(errors[1:])


def test_interrupted_long_run_releases_the_leak(tmp_path):
    now, _sleep = _clock(T0)
    calls = []

    def set_fault(kind, value=None):
        calls.append((kind, value))
        return {}

    def boom(_minutes, _label):
        raise KeyboardInterrupt

    try:
        scenario.run_scenario(
            baseline_min=10, fault_min=3, gap_min=3, runs_dir=tmp_path,
            sleep=boom, now=now, set_fault=set_fault, profile="long",
        )
    except KeyboardInterrupt:
        pass
    manifest = runs.latest_manifest(tmp_path)
    assert manifest["scenario"]["status"] == "interrupted"
    assert manifest["chapters"][0]["end"] == runs.iso(T0)
    assert calls[-2:] == [("reset", None), ("leak_release", None)]


def test_default_profile_events_stay_the_same(tmp_path):
    now, sleep = _clock(T0)
    manifest = scenario.run_scenario(
        baseline_min=10, fault_min=3, gap_min=3, runs_dir=tmp_path,
        sleep=sleep, now=now, set_fault=lambda *_args, **_kwargs: {},
    )
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
    assert [chapter["name"] for chapter in manifest["chapters"]] == [
        "baseline", "latency", "recovery-1", "cpu", "recovery-2", "errors", "recovery-3",
    ]


def test_chapter_report_orders_contributors_and_skips_an_open_chapter():
    index = pd.date_range("2026-11-27T19:00:00Z", periods=4, freq="15s")
    scores = pd.DataFrame({
        "recon_error": [1.0, 2.0, 3.0, 0.0],
        "anomaly": [True, True, True, False],
        "top_contributor": ["lat_p95", "error_ratio", "lat_p95", "req_rate"],
    }, index=index)
    report = core.chapter_report(scores, [
        {
            "name": "retry-ramp",
            "role": "fault",
            "start": "2026-11-27T19:00:00+00:00",
            "end": "2026-11-27T19:01:00+00:00",
        },
        {"name": "still-open", "role": "fault", "start": "2026-11-27T19:00:00+00:00", "end": None},
        {
            "name": "outside",
            "role": "recovery",
            "start": "2026-11-27T18:00:00+00:00",
            "end": "2026-11-27T18:01:00+00:00",
        },
    ])
    assert [row["name"] for row in report] == ["retry-ramp", "outside"]
    assert report[0]["samples"] == 4
    assert report[0]["flagged_frac"] == 0.75
    assert report[0]["seconds_to_first_flag"] == 0
    assert report[0]["contributors"] == [
        {"name": "lat_p95", "flagged_samples": 2},
        {"name": "error_ratio", "flagged_samples": 1},
    ]
    assert report[1]["samples"] == 0
    assert report[1]["flagged_frac"] is None
    assert report[1]["contributors"] == []


def test_analyze_writes_chapter_scores(tmp_path, monkeypatch, capsys):
    runs.begin_load("40m", 20, tmp_path, now=T0)
    manifest = runs.begin_scenario(tmp_path, T0)
    fault_at = T0 + timedelta(minutes=12)
    done = T0 + timedelta(minutes=30)
    runs.record_event(manifest, "baseline start", tmp_path, now=T0)
    runs.record_event(manifest, "fault latency=300 ON", tmp_path, now=fault_at)
    runs.record_event(manifest, "scenario done", tmp_path, now=done)
    manifest["chapters"] = [{
        "name": "latency",
        "role": "fault",
        "start": runs.iso(fault_at),
        "end": runs.iso(fault_at + timedelta(minutes=3)),
    }]
    runs.write_manifest(manifest, tmp_path, make_latest=False)

    def fetch_metrics(minutes=60, step="15s", end=None, queries=None, url=None, start=None):
        index = pd.date_range(start, end, freq="15s", inclusive="both")
        rng = np.random.default_rng(0)
        frame = pd.DataFrame({f"m{i}": rng.normal(size=len(index)) for i in range(4)}, index=index)
        faults = pd.DataFrame(0, index=index, columns=["fault_cpu", "fault_errors", "fault_latency"])
        faults.loc[(index >= fault_at) & (index < fault_at + timedelta(minutes=3)), "fault_latency"] = 1
        return frame, faults

    monkeypatch.setattr(core.prom, "is_up", lambda url, timeout=2.0: True)
    monkeypatch.setattr(core.prom, "fetch_metrics", fetch_metrics)
    reports = tmp_path / "out"
    assert cli.main([
        "--source", "prometheus", "--run", "latest", "--runs-dir", str(tmp_path), "--reports-dir", str(reports),
    ]) == 0
    summary = json.loads((reports / "summary.json").read_text(encoding="utf-8"))
    assert summary["chapters"][0]["name"] == "latency"
    assert summary["chapters"][0]["role"] == "fault"
    assert summary["chapters"][0]["samples"] == 12
    assert "chapters (" in capsys.readouterr().out


def test_long_profile_ignores_the_short_timeline_flags(tmp_path, monkeypatch, capsys):
    seen = {}

    def fake_run(**kwargs):
        seen.update(kwargs)
        return {"run_id": "20261127T190000Z"}

    monkeypatch.setattr(scenario, "run_scenario", fake_run)
    assert scenario.main(["--profile", "long", "--baseline-min", "5", "--runs-dir", str(tmp_path)]) == 0
    assert seen["profile"] == "long"
    out = capsys.readouterr().out
    assert "uses its own timeline" in out
    assert "reports/long-run-deseason" in out
