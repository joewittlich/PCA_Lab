"""`sre-scenario` - a scripted experiment: baseline, then each fault in turn, with recovery gaps.

Run load at the same time (separate terminal):   docker compose --profile load run --rm k6
Default timeline (~28 min):  10 min baseline | latency 3 | gap 3 | cpu 3 | gap 3 | errors 3 | gap 3

The scenario writes reports/runs/<run_id>.json. Analyze that window later with:
  uv run sre-pca --run <run_id>

  uv run sre-scenario
  uv run sre-scenario --baseline-min 5 --fault-min 2 --gap-min 2   # quicker (~17 min)
"""

from __future__ import annotations

import argparse
import time
from collections.abc import Callable
from datetime import datetime
from pathlib import Path

from . import runs
from .fault import set_fault

STEPS = [("latency", "300"), ("cpu", "on"), ("errors", "0.2")]


def _sleep(minutes: float, label: str) -> None:
    end = time.time() + minutes * 60
    while (left := end - time.time()) > 0:
        print(f"\r  {label}: {left / 60:5.1f} min left ", end="", flush=True)
        time.sleep(min(5, left))
    print()


def run_scenario(
    *,
    baseline_min: float,
    fault_min: float,
    gap_min: float,
    runs_dir: Path,
    sleep: Callable[[float, str], None],
    now: Callable[[], datetime],
    set_fault: Callable[..., dict],
    steps: list[tuple[str, str]] = STEPS,
) -> dict:
    """Drive the fault timeline and record it on a run manifest. ``sleep`` receives minutes."""
    manifest = runs.begin_scenario(runs_dir, now())

    def log(event: str) -> None:
        stamp = now()
        print(f"[{runs.iso(stamp)}] {event}")
        runs.record_event(manifest, event, runs_dir, now=stamp)

    total = baseline_min + len(steps) * (fault_min + gap_min)
    print(f"Scenario will take ~{total:.0f} min. Make sure k6 load is running. Ctrl+C resets faults.")
    print(f"Recording {runs_dir / (manifest['run_id'] + '.json')}")
    try:
        set_fault("reset")
        log("baseline start")
        sleep(baseline_min, "baseline")
        for kind, value in steps:
            set_fault(kind, value)
            log(f"fault {kind}={value} ON")
            sleep(fault_min, f"fault {kind}")
            set_fault("reset")
            log(f"fault {kind} OFF")
            sleep(gap_min, "recovery")
        log("scenario done")
    except KeyboardInterrupt:
        set_fault("reset")
        log("interrupted - faults reset")
        raise
    return manifest


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="sre-scenario", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--baseline-min", type=float, default=10)
    p.add_argument("--fault-min", type=float, default=3)
    p.add_argument("--gap-min", type=float, default=3)
    p.add_argument("--runs-dir", default=str(runs.RUNS_DIR))
    a = p.parse_args(argv)
    runs_dir = Path(a.runs_dir)
    try:
        manifest = run_scenario(
            baseline_min=a.baseline_min,
            fault_min=a.fault_min,
            gap_min=a.gap_min,
            runs_dir=runs_dir,
            sleep=_sleep,
            now=runs.utcnow,
            set_fault=set_fault,
        )
    except KeyboardInterrupt:
        return 0
    print(f"\nWrote {runs_dir / (manifest['run_id'] + '.json')}")
    print(f"Now analyze it:  uv run sre-pca --run {manifest['run_id']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
