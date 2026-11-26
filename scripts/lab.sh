#!/usr/bin/env bash
# Day-to-day commands for the lab (macOS / Linux / WSL). Run from anywhere:
#   ./scripts/lab.sh <command> [args]
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

APP_URL="${APP_URL:-http://localhost:${APP_PORT:-8000}}"
PROM_URL="${PROM_URL:-http://localhost:${PROMETHEUS_PORT:-9090}}"
export APP_URL PROM_URL

compose() {
  if docker compose version >/dev/null 2>&1; then
    docker compose "$@"
  elif command -v docker-compose >/dev/null 2>&1; then
    docker-compose "$@"
  else
    echo "Docker Compose not found. Run ./scripts/bootstrap.sh first." >&2
    exit 1
  fi
}

py() {
  if command -v uv >/dev/null 2>&1; then
    uv run "$@"
  elif [ -x .venv/bin/python ]; then
    PATH="$ROOT/.venv/bin:$PATH" "$@"
  else
    echo "Neither uv nor .venv found. Run ./scripts/bootstrap.sh (or see README pip fallback)." >&2
    exit 1
  fi
}

need_docker() {
  if ! docker info >/dev/null 2>&1; then
    echo "Docker is not running (or your user can't reach it). Start Docker Desktop / 'sudo systemctl start docker'," >&2
    echo "or on Linux log out/in after being added to the 'docker' group." >&2
    exit 1
  fi
}

usage() {
  cat <<'USAGE'
Usage: ./scripts/lab.sh <command> [args]

Stack
  up                 build + start the stack (app, collector, prometheus, node-exporter, grafana)
  down               stop the stack (keeps Prometheus/Grafana data)
  nuke               stop and DELETE volumes (fresh Prometheus/Grafana)
  status             containers + Prometheus scrape target health
  logs [service]     follow logs
Load & faults
  load [dur] [rps]   run k6 in the foreground (default 10m, 20 rps)   e.g. load 30m 40
  load-bg [dur] [rps] same, detached (stop with: lab.sh load-stop)
  load-stop          stop background k6
  fault <kind> [v]   latency <ms> | cpu on|off | errors <rate> | reset | status
  scenario [args]    scripted baseline + faults (pass e.g. --baseline-min 5 --fault-min 2 --gap-min 2)
Analysis
  analyze [args]     run the full PCA analysis (CLI), plots in reports/   e.g. analyze --minutes 40
  synthetic          same, on synthetic data (no Docker needed)
  notebook           start JupyterLab on notebooks/
  exporter           publish live anomaly score on :9105 (see README Next steps)
  test               run the Python tests (synthetic, no Docker needed)
USAGE
}

cmd="${1:-help}"
shift || true

case "$cmd" in
  up)        need_docker; compose up -d --build; echo; "$0" status ;;
  down)      compose down ;;
  nuke)      compose --profile load down -v ;;
  status)
    compose ps
    echo
    if command -v curl >/dev/null 2>&1; then
      echo "Prometheus targets:"
      curl -fsS "$PROM_URL/api/v1/targets" 2>/dev/null \
        | py python -c 'import json, sys
for t in json.load(sys.stdin)["data"]["activeTargets"]:
    print("  %-18s %-7s %s" % (t["labels"]["job"], t["health"], t["lastError"]))' \
        || echo "  (Prometheus not reachable at $PROM_URL yet)"
    fi
    echo
    echo "Grafana:    http://localhost:${GRAFANA_PORT:-3000}  (admin / admin)"
    echo "Prometheus: $PROM_URL"
    echo "Demo app:   $APP_URL/docs"
    ;;
  logs)      compose logs -f "$@" ;;
  load)      need_docker; LOAD_DURATION="${1:-10m}" LOAD_RPS="${2:-20}" compose --profile load run --rm k6 ;;
  load-bg)   need_docker; LOAD_DURATION="${1:-10m}" LOAD_RPS="${2:-20}" compose --profile load up -d k6; echo "k6 running in background: lab.sh logs k6" ;;
  load-stop) compose --profile load stop k6; compose --profile load rm -f k6 ;;
  fault)     py sre-fault "$@" ;;
  scenario)  py sre-scenario "$@" ;;
  analyze)   py sre-pca "$@" ;;
  synthetic) py sre-pca --source synthetic "$@" ;;
  notebook)  py jupyter lab --notebook-dir=notebooks ;;
  exporter)  py sre-pca-exporter "$@" ;;
  test)      py pytest -q ;;
  help|-h|--help) usage ;;
  *)         echo "unknown command: $cmd" >&2; usage; exit 1 ;;
esac
