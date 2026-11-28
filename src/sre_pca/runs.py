"""Run manifests: one JSON file per load/scenario, so analysis can reopen that window later.

A manifest lives at ``reports/runs/<run_id>.json``. ``lab`` writes the load block when k6
starts. ``sre-scenario`` fills the scenario block and the event list. ``sre-pca --run latest``
reads the file and queries that interval instead of "the last N minutes from now".
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

RUNS_DIR = Path("reports/runs")
PAD = timedelta(minutes=2)

_DURATION = re.compile(r"(\d+(?:\.\d+)?)(ms|s|m|h|d)")
_DURATION_UNIT = {
    "ms": lambda n: timedelta(milliseconds=n),
    "s": lambda n: timedelta(seconds=n),
    "m": lambda n: timedelta(minutes=n),
    "h": lambda n: timedelta(hours=n),
    "d": lambda n: timedelta(days=n),
}


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def iso(value: datetime) -> str:
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc).isoformat(timespec="seconds")


def parse_time(value: str) -> datetime:
    text = value.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    parsed = datetime.fromisoformat(text)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def parse_duration(text: str) -> timedelta:
    """Parse a k6-style duration such as ``40m``, ``90s``, or ``1h30m``."""
    raw = text.strip().lower().replace(" ", "")
    matches = list(_DURATION.finditer(raw))
    if not raw or not matches or "".join(match.group(0) for match in matches) != raw:
        raise ValueError(f"cannot parse duration {text!r} (examples: 40m, 90s, 1h30m)")
    total = timedelta(0)
    for match in matches:
        total += _DURATION_UNIT[match.group(2)](float(match.group(1)))
    return total


def run_id_from(value: datetime) -> str:
    return value.astimezone(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def manifest_path(run_id: str, root: Path) -> Path:
    return root / f"{run_id}.json"


def new_manifest(now: datetime) -> dict:
    return {"run_id": run_id_from(now), "events": []}


def read_manifest(path: Path) -> dict:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(data, dict) or not data.get("run_id"):
        raise ValueError(f"not a run manifest: {path}")
    return data


def write_manifest(manifest: dict, root: Path, *, make_latest: bool = False) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    path = manifest_path(manifest["run_id"], root)
    path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    if make_latest:
        (root / "latest").write_text(manifest["run_id"] + "\n", encoding="utf-8")
    return path


def latest_manifest(root: Path) -> dict:
    pointer = root / "latest"
    if pointer.is_file():
        run_id = pointer.read_text(encoding="utf-8").strip()
        path = manifest_path(run_id, root)
        if path.is_file():
            return read_manifest(path)
    files = sorted(root.glob("*.json"))
    if not files:
        raise FileNotFoundError(f"no run manifests in {root}")
    return read_manifest(files[-1])


def _try_latest(root: Path) -> dict | None:
    try:
        return latest_manifest(root)
    except FileNotFoundError:
        return None


def _load_is_active(load: dict | None, now: datetime) -> bool:
    """True when this load block can still explain traffic for a scenario starting at ``now``."""
    if not load or not load.get("start") or not load.get("end"):
        return False
    if parse_time(load["start"]) > now:
        return False
    if load.get("actual_end") and parse_time(load["actual_end"]) <= now:
        return False
    # The planned end has passed and nobody recorded a stop. Treat the load as finished.
    if parse_time(load["end"]) <= now and not load.get("actual_end"):
        return False
    return parse_time(load["end"]) > now


def begin_load(duration: str, rps: str | int, root: Path, now: datetime | None = None) -> dict:
    """Record the start of k6. Reuse the latest run when a scenario is already in progress and has no load."""
    now = now or utcnow()
    load = {
        "start": iso(now),
        "end": iso(now + parse_duration(duration)),
        "rps": int(rps),
        "duration": str(duration),
    }
    existing = _try_latest(root)
    scenario = (existing or {}).get("scenario") or {}
    if existing and scenario.get("start") and not scenario.get("end") and not existing.get("load"):
        existing["load"] = load
        manifest = existing
    else:
        manifest = new_manifest(now)
        manifest["load"] = load
    write_manifest(manifest, root, make_latest=True)
    (root / "active-load").write_text(manifest["run_id"] + "\n", encoding="utf-8")
    return manifest


def finish_load(root: Path, run_id: str | None = None, now: datetime | None = None) -> str | None:
    """Set ``load.actual_end`` on the active load and on any scenario run that copied it."""
    pointer = root / "active-load"
    if run_id is None:
        if not pointer.is_file():
            return None
        run_id = pointer.read_text(encoding="utf-8").strip()
    path = manifest_path(run_id, root)
    if not path.is_file():
        return None
    origin = read_manifest(path).get("load") or {}
    start = origin.get("start")
    if not start:
        return None
    stamp = iso(now or utcnow())
    for file in sorted(root.glob("*.json")):
        manifest = read_manifest(file)
        other = manifest.get("load")
        if not other or other.get("start") != start or other.get("actual_end"):
            continue
        other["actual_end"] = stamp
        write_manifest(manifest, root, make_latest=False)
    if pointer.is_file() and pointer.read_text(encoding="utf-8").strip() == run_id:
        pointer.unlink()
    return run_id


def begin_scenario(root: Path, now: datetime | None = None) -> dict:
    """Open the scenario block. Attach to a load-only run; otherwise start a new file and copy an active load."""
    now = now or utcnow()
    existing = _try_latest(root)
    scenario = (existing or {}).get("scenario") or {}
    reuse = existing is not None and not scenario.get("start")
    if reuse:
        manifest = existing
    else:
        manifest = new_manifest(now)
        load = (existing or {}).get("load")
        if _load_is_active(load, now):
            manifest["load"] = dict(load)
    manifest["scenario"] = {
        "start": iso(now),
        "end": None,
        "baseline_end": None,
        "status": "running",
    }
    manifest["events"] = []
    write_manifest(manifest, root, make_latest=True)
    return manifest


def record_event(manifest: dict, event: str, root: Path, now: datetime | None = None) -> dict:
    """Append an event. The first fault ON sets ``baseline_end``. Done and interrupted set ``scenario.end``."""
    stamp = iso(now or utcnow())
    manifest.setdefault("events", []).append([stamp, event])
    scenario = manifest.setdefault("scenario", {})
    if event.startswith("fault ") and event.endswith(" ON") and not scenario.get("baseline_end"):
        scenario["baseline_end"] = stamp
    if event == "scenario done":
        scenario["end"] = stamp
        scenario["status"] = "done"
    elif event.startswith("interrupted"):
        scenario["end"] = stamp
        scenario["status"] = "interrupted"
    write_manifest(manifest, root, make_latest=False)
    return manifest


def resolve_run(spec: str, root: Path) -> dict:
    """``latest``, a run id, or a path to a manifest file."""
    if spec == "latest":
        return latest_manifest(root)
    path = Path(spec)
    if path.is_file():
        return read_manifest(path)
    candidate = root / f"{spec}.json"
    if candidate.is_file():
        return read_manifest(candidate)
    raise FileNotFoundError(f"run manifest not found: {spec}")


def query_window(
    manifest: dict,
    pad: timedelta = PAD,
    now: datetime | None = None,
) -> tuple[datetime, datetime]:
    """Prometheus range for this run: load start (else scenario start) through scenario end, plus ``pad``."""
    load = manifest.get("load") or {}
    scenario = manifest.get("scenario") or {}
    if load.get("start"):
        start = parse_time(load["start"])
    elif scenario.get("start"):
        start = parse_time(scenario["start"])
    else:
        raise ValueError(f"run {manifest.get('run_id')} has no load or scenario start")
    start = start - pad
    if scenario.get("end"):
        end = parse_time(scenario["end"]) + pad
    else:
        end = now or utcnow()
    if end <= start:
        end = start + timedelta(minutes=1)
    return start, end


def baseline_bounds(manifest: dict) -> tuple[datetime, datetime] | None:
    """Declared training interval: load start (else scenario start) through the first fault ON.

    The caller still drops the last two minutes, so the ``rate()`` ramp stays out of the fit.
    """
    scenario = manifest.get("scenario") or {}
    load = manifest.get("load") or {}
    end = scenario.get("baseline_end")
    start = load.get("start") or scenario.get("start")
    if not start or not end:
        return None
    return parse_time(start), parse_time(end)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m sre_pca.runs", description=__doc__)
    parser.add_argument("--runs-dir", default=str(RUNS_DIR))
    sub = parser.add_subparsers(dest="cmd", required=True)

    start = sub.add_parser("load-start", help="record the start of a k6 load")
    start.add_argument("--duration", required=True)
    start.add_argument("--rps", required=True)

    stop = sub.add_parser("load-end", help="record the actual end of the active k6 load")
    stop.add_argument("--run-id", default=None)

    args = parser.parse_args(argv)
    root = Path(args.runs_dir)
    if args.cmd == "load-start":
        manifest = begin_load(args.duration, args.rps, root)
        print(f"[sre_pca] load run {manifest['run_id']} -> {root / (manifest['run_id'] + '.json')}")
        return 0
    run_id = finish_load(root, args.run_id)
    if run_id:
        print(f"[sre_pca] recorded load end for {run_id}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (ValueError, FileNotFoundError, OSError) as exc:
        print(f"[sre_pca] {exc}", file=sys.stderr)
        raise SystemExit(1) from exc
