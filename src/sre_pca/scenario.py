"""`sre-scenario` - a scripted experiment: baseline, then each fault in turn, with recovery gaps.

Run load at the same time (separate terminal):   docker compose --profile load run --rm k6
Default timeline (~28 min):  10 min baseline | latency 3 | gap 3 | cpu 3 | gap 3 | errors 3 | gap 3

  uv run sre-scenario
  uv run sre-scenario --baseline-min 5 --fault-min 2 --gap-min 2   # quicker (~17 min)
"""

from __future__ import annotations

import argparse
import csv
import time
from datetime import datetime, timezone
from pathlib import Path

from .fault import set_fault

STEPS = [("latency", "300"), ("cpu", "on"), ("errors", "0.2")]


def _sleep(minutes: float, label: str) -> None:
    end = time.time() + minutes * 60
    while (left := end - time.time()) > 0:
        print(f"\r  {label}: {left / 60:5.1f} min left ", end="", flush=True)
        time.sleep(min(5, left))
    print()


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="sre-scenario", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--baseline-min", type=float, default=10)
    p.add_argument("--fault-min", type=float, default=3)
    p.add_argument("--gap-min", type=float, default=3)
    p.add_argument("--log", default="reports/scenario_log.csv")
    a = p.parse_args(argv)
    Path(a.log).parent.mkdir(parents=True, exist_ok=True)

    def log(event: str) -> None:
        now = datetime.now(timezone.utc).isoformat(timespec="seconds")
        print(f"[{now}] {event}")
        with open(a.log, "a", newline="") as fh:
            csv.writer(fh).writerow([now, event])

    total = a.baseline_min + len(STEPS) * (a.fault_min + a.gap_min)
    print(f"Scenario will take ~{total:.0f} min. Make sure k6 load is running. Ctrl+C resets faults.")
    try:
        set_fault("reset")
        log("baseline start")
        _sleep(a.baseline_min, "baseline")
        for kind, value in STEPS:
            set_fault(kind, value)
            log(f"fault {kind}={value} ON")
            _sleep(a.fault_min, f"fault {kind}")
            set_fault("reset")
            log(f"fault {kind} OFF")
            _sleep(a.gap_min, "recovery")
        log("scenario done")
        print(f"\nNow analyze it:  uv run sre-pca --minutes {int(total) + 2}")
    except KeyboardInterrupt:
        set_fault("reset")
        log("interrupted - faults reset")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
