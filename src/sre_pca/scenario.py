"""`sre-scenario` - a scripted experiment: baseline, then each fault in turn, with recovery gaps.

Run load at the same time (separate terminal):   docker compose --profile load run --rm k6
Default timeline (~28 min):  10 min baseline | latency 3 | gap 3 | cpu 3 | gap 3 | errors 3 | gap 3

The scenario writes reports/runs/<run_id>.json. Analyze that window later with:
  uv run sre-pca --run <run_id>

  uv run sre-scenario
  uv run sre-scenario --baseline-min 5 --fault-min 2 --gap-min 2   # quicker (~17 min)
  uv run sre-scenario --profile long                               # second session, 3 hours

The long profile repeats the three single faults, then adds retries, a downstream timeout,
and a memory leak that stays after the allocator stops. See docs/long-run.md.
"""

from __future__ import annotations

import argparse
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from . import runs
from .fault import set_fault

STEPS = [("latency", "300"), ("cpu", "on"), ("errors", "0.2")]
RAMP_STEP_S = 30.0
LONG_LOAD = "3h30m"


@dataclass(frozen=True)
class Chapter:
    """One named stretch of the long session.

    ``faults`` are applied together at the start. ``ramp`` moves one fault from its first value
    to its last across the chapter. ``stop_leak`` ends allocation and leaves the memory held.
    """

    name: str
    minutes: float
    role: str
    faults: tuple[tuple[str, str], ...] = ()
    ramp: tuple[str, str, str] | None = None
    stop_leak: bool = False


def long_chapters() -> list[Chapter]:
    """Three hours: the usual three faults, then retries, a timeout, and a leak that stays."""
    return [
        Chapter("baseline", 30, "baseline"),
        Chapter("latency", 5, "fault", faults=(("latency", "300"),)),
        Chapter("recovery-latency", 10, "recovery"),
        Chapter("cpu", 5, "fault", faults=(("cpu", "on"),)),
        Chapter("recovery-cpu", 10, "recovery"),
        Chapter("errors", 5, "fault", faults=(("errors", "0.2"),)),
        Chapter("recovery-errors", 10, "recovery"),
        Chapter(
            "retry-ramp",
            30,
            "fault",
            faults=(("retries", "2"), ("client_retries", "1")),
            ramp=("errors", "0.05", "0.85"),
        ),
        Chapter(
            "downstream-timeout",
            30,
            "fault",
            faults=(("downstream", "2000"), ("timeout", "1000")),
        ),
        Chapter("leak", 15, "fault", faults=(("leak", "64"),), stop_leak=True),
        Chapter("leak-held", 10, "level_shift"),
        Chapter("healthy-after-leak", 20, "level_shift"),
    ]


def _sleep(minutes: float, label: str) -> None:
    end = time.time() + minutes * 60
    while (left := end - time.time()) > 0:
        print(f"\r  {label}: {left / 60:5.1f} min left ", end="", flush=True)
        time.sleep(min(5, left))
    print()


def _start_chapter(manifest: dict, chapter: Chapter, root: Path, stamp: datetime) -> None:
    manifest.setdefault("chapters", []).append({
        "name": chapter.name,
        "role": chapter.role,
        "start": runs.iso(stamp),
        "end": None,
        "faults": {kind: value for kind, value in chapter.faults},
        "ramp": list(chapter.ramp) if chapter.ramp else None,
    })
    runs.write_manifest(manifest, root, make_latest=False)


def _end_chapter(manifest: dict, root: Path, stamp: datetime) -> None:
    chapters = manifest.get("chapters") or []
    if chapters and chapters[-1].get("end") is None:
        chapters[-1]["end"] = runs.iso(stamp)
        runs.write_manifest(manifest, root, make_latest=False)


def _remember_plan(manifest: dict, chapters: list[Chapter], root: Path) -> None:
    offset = 0.0
    plan = []
    for chapter in chapters:
        plan.append({
            "name": chapter.name,
            "role": chapter.role,
            "offset_min": offset,
            "minutes": chapter.minutes,
            "faults": {kind: value for kind, value in chapter.faults},
            "ramp": list(chapter.ramp) if chapter.ramp else None,
        })
        offset += chapter.minutes
    manifest["plan"] = plan
    runs.write_manifest(manifest, root, make_latest=False)


def _ramp_steps(start: float, end: float, minutes: float) -> list[tuple[float, float]]:
    """Values and sleep lengths, in minutes, covering ``minutes`` exactly."""
    n = max(1, int(round(minutes * 60 / RAMP_STEP_S)))
    sleep = minutes / n
    if n == 1:
        return [(end, sleep)]
    return [(start + (end - start) * i / (n - 1), sleep) for i in range(n)]


def _release(set_fault: Callable[..., dict]) -> None:
    set_fault("reset")
    set_fault("leak_release")


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
    profile: str = "default",
) -> dict:
    """Drive the fault timeline and record it on a run manifest. ``sleep`` receives minutes."""
    if profile == "long":
        return _run_long(runs_dir=runs_dir, sleep=sleep, now=now, set_fault=set_fault)
    if profile != "default":
        raise ValueError(f"unknown scenario profile {profile!r}")
    return _run_default(
        baseline_min=baseline_min,
        fault_min=fault_min,
        gap_min=gap_min,
        runs_dir=runs_dir,
        sleep=sleep,
        now=now,
        set_fault=set_fault,
        steps=steps,
    )


def _run_default(
    *,
    baseline_min: float,
    fault_min: float,
    gap_min: float,
    runs_dir: Path,
    sleep: Callable[[float, str], None],
    now: Callable[[], datetime],
    set_fault: Callable[..., dict],
    steps: list[tuple[str, str]],
) -> dict:
    manifest = runs.begin_scenario(runs_dir, now())
    chapters = [
        Chapter("baseline", baseline_min, "baseline"),
        *[
            piece
            for index, (kind, value) in enumerate(steps, start=1)
            for piece in (
                Chapter(kind, fault_min, "fault", faults=((kind, value),)),
                Chapter(f"recovery-{index}", gap_min, "recovery"),
            )
        ],
    ]

    def log(event: str) -> None:
        stamp = now()
        print(f"[{runs.iso(stamp)}] {event}")
        runs.record_event(manifest, event, runs_dir, now=stamp)

    _remember_plan(manifest, chapters, runs_dir)
    total = baseline_min + len(steps) * (fault_min + gap_min)
    print(f"Scenario will take ~{total:.0f} min. Make sure k6 load is running. Ctrl+C resets faults.")
    print(f"Recording {runs_dir / (manifest['run_id'] + '.json')}")
    try:
        set_fault("reset")
        _start_chapter(manifest, chapters[0], runs_dir, now())
        log("baseline start")
        sleep(baseline_min, "baseline")
        _end_chapter(manifest, runs_dir, now())
        for index, (kind, value) in enumerate(steps):
            fault_chapter = chapters[1 + index * 2]
            recovery = chapters[2 + index * 2]
            _start_chapter(manifest, fault_chapter, runs_dir, now())
            set_fault(kind, value)
            log(f"fault {kind}={value} ON")
            sleep(fault_min, f"fault {kind}")
            set_fault("reset")
            log(f"fault {kind} OFF")
            _end_chapter(manifest, runs_dir, now())
            _start_chapter(manifest, recovery, runs_dir, now())
            sleep(gap_min, "recovery")
            _end_chapter(manifest, runs_dir, now())
        log("scenario done")
    except KeyboardInterrupt:
        _end_chapter(manifest, runs_dir, now())
        set_fault("reset")
        log("interrupted - faults reset")
        raise
    return manifest


def _run_long(
    *,
    runs_dir: Path,
    sleep: Callable[[float, str], None],
    now: Callable[[], datetime],
    set_fault: Callable[..., dict],
) -> dict:
    chapters = long_chapters()
    manifest = runs.begin_scenario(runs_dir, now())

    def log(event: str) -> None:
        stamp = now()
        print(f"[{runs.iso(stamp)}] {event}")
        runs.record_event(manifest, event, runs_dir, now=stamp)

    _remember_plan(manifest, chapters, runs_dir)
    total = sum(chapter.minutes for chapter in chapters)
    print(f"Long session will take ~{total:.0f} min. Start it with load already running, for example load {LONG_LOAD} 20.")
    print("Ctrl+C resets faults and releases the leak.")
    print(f"Recording {runs_dir / (manifest['run_id'] + '.json')}")
    offset = 0.0
    for chapter in chapters:
        print(f"  {offset:6.0f} min  {chapter.name} ({chapter.minutes:.0f} min, {chapter.role})")
        offset += chapter.minutes
    try:
        for chapter in chapters:
            _play_chapter(chapter, manifest, runs_dir, sleep, now, set_fault, log)
        log("scenario done")
        try:
            set_fault("leak_release")
        except OSError as exc:
            print(f"[sre-scenario] scenario is recorded; could not release the leak: {exc}")
        else:
            log("fault leak released")
    except KeyboardInterrupt:
        _end_chapter(manifest, runs_dir, now())
        _release(set_fault)
        log("interrupted - faults reset")
        raise
    return manifest


def _play_chapter(
    chapter: Chapter,
    manifest: dict,
    runs_dir: Path,
    sleep: Callable[[float, str], None],
    now: Callable[[], datetime],
    set_fault: Callable[..., dict],
    log: Callable[[str], None],
) -> None:
    set_fault("reset")
    _start_chapter(manifest, chapter, runs_dir, now())
    log(f"chapter {chapter.name} start")
    if chapter.role == "baseline":
        log("baseline start")
    active: list[str] = []
    for kind, value in chapter.faults:
        set_fault(kind, value)
        log(f"fault {kind}={value} ON")
        active.append(kind)
    if chapter.ramp:
        kind, raw_start, raw_end = chapter.ramp
        first = True
        for value, pause in _ramp_steps(float(raw_start), float(raw_end), chapter.minutes):
            rendered = f"{value:.3f}"
            set_fault(kind, rendered)
            log(f"fault {kind}={rendered} ON" if first else f"fault {kind}={rendered}")
            first = False
            sleep(pause, f"{chapter.name} {kind}")
        if kind not in active:
            active.append(kind)
    else:
        sleep(chapter.minutes, chapter.name)
    if chapter.stop_leak:
        set_fault("leak", "0")
        if "leak" not in active:
            active.append("leak")
    set_fault("reset")
    for kind in active:
        log(f"fault {kind} OFF")
    _end_chapter(manifest, runs_dir, now())
    log(f"chapter {chapter.name} end")


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="sre-scenario", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--profile", choices=["default", "long"], default="default")
    p.add_argument("--baseline-min", type=float, default=10)
    p.add_argument("--fault-min", type=float, default=3)
    p.add_argument("--gap-min", type=float, default=3)
    p.add_argument("--runs-dir", default=str(runs.RUNS_DIR))
    a = p.parse_args(argv)
    if a.profile == "long" and (a.baseline_min != 10 or a.fault_min != 3 or a.gap_min != 3):
        print(
            "[sre-scenario] --profile long uses its own timeline. "
            "--baseline-min, --fault-min, and --gap-min apply to the default profile."
        )
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
            profile=a.profile,
        )
    except KeyboardInterrupt:
        return 0
    print(f"\nWrote {runs_dir / (manifest['run_id'] + '.json')}")
    if a.profile == "long":
        print(f"Now analyze it:  uv run sre-pca --run {manifest['run_id']} --reports-dir reports/long-run")
        print("Compare a second pass with the traffic wave removed:")
        print(f"  uv run sre-pca --run {manifest['run_id']} --deseason stl --period 20 --reports-dir reports/long-run-deseason")
    else:
        print(f"Now analyze it:  uv run sre-pca --run {manifest['run_id']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
