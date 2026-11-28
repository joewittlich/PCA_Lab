"""`sre-fault` - toggle faults on the demo app (cross-platform alternative to curl).

  uv run sre-fault status
  uv run sre-fault latency 300     # ms added per request (0 = off)
  uv run sre-fault cpu on          # on/off
  uv run sre-fault errors 0.2      # fraction of requests returning 500 (0 = off)
  uv run sre-fault retries 2       # extra server attempts after a failure
  uv run sre-fault client_retries 1
  uv run sre-fault downstream 2000 # ms of downstream delay
  uv run sre-fault timeout 1000    # ms budget; longer downstream becomes HTTP 504
  uv run sre-fault leak 64         # hold 64 MB (0 stops growing, memory stays)
  uv run sre-fault leak_release    # free the held memory
  uv run sre-fault reset           # clears every fault except held leak memory
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
    if kind == "retries":
        return call("/fault/retries", count=int(float(value if value is not None else 2)))
    if kind == "client_retries":
        return call("/fault/client-retries", count=int(float(value if value is not None else 1)))
    if kind == "downstream":
        return call("/fault/downstream", ms=float(value if value is not None else 2000))
    if kind == "timeout":
        return call("/fault/timeout", ms=float(value if value is not None else 1000))
    if kind == "leak":
        return call("/fault/leak", mb=float(value if value is not None else 64))
    if kind == "leak_release":
        return call("/fault/leak", release="true")
    raise SystemExit(
        f"unknown fault {kind!r}; use status|reset|latency|cpu|errors|retries|"
        "client_retries|downstream|timeout|leak|leak_release"
    )


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    if not argv or argv[0] in {"-h", "--help"}:
        print(__doc__)
        return 0
    print(json.dumps(set_fault(argv[0], argv[1] if len(argv) > 1 else None)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
