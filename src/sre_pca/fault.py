"""`sre-fault` - toggle faults on the demo app (cross-platform alternative to curl).

  uv run sre-fault status
  uv run sre-fault latency 300     # ms added per request (0 = off)
  uv run sre-fault cpu on          # on/off
  uv run sre-fault errors 0.2      # fraction of requests returning 500 (0 = off)
  uv run sre-fault reset
"""

from __future__ import annotations

import json
import os
import sys
import urllib.parse
import urllib.request

APP_URL = os.getenv("APP_URL", "http://localhost:8000")


def call(path: str, method: str = "POST", **params) -> dict:
    q = ("?" + urllib.parse.urlencode(params)) if params else ""
    req = urllib.request.Request(f"{APP_URL}{path}{q}", method=method)
    with urllib.request.urlopen(req, timeout=5) as r:
        return json.loads(r.read())


def set_fault(kind: str, value: str | None = None) -> dict:
    if kind == "status":
        return call("/fault", "GET")
    if kind == "reset":
        return call("/fault/reset")
    if kind == "latency":
        return call("/fault/latency", ms=float(value if value is not None else 300))
    if kind == "cpu":
        on = (value or "on").lower() in {"on", "1", "true", "yes"}
        return call("/fault/cpu", on=str(on).lower())
    if kind == "errors":
        return call("/fault/errors", rate=float(value if value is not None else 0.2))
    raise SystemExit(f"unknown fault {kind!r}; use status|reset|latency|cpu|errors")


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    if not argv or argv[0] in {"-h", "--help"}:
        print(__doc__)
        return 0
    print(json.dumps(set_fault(argv[0], argv[1] if len(argv) > 1 else None)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
