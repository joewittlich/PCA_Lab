"""Demo service for the SRE PCA lab.

A tiny FastAPI app that:
  * exposes Prometheus metrics at /metrics (prometheus_client)
  * optionally pushes OpenTelemetry metrics + traces to the OTel Collector (OTLP/HTTP)
  * lets you inject faults at runtime (latency, CPU burn, errors) via HTTP or env vars

Fault toggles (HTTP):
  GET  /fault                       -> current fault state
  POST /fault/latency?ms=300        -> add 300 ms (+ jitter) to every API request (0 = off)
  POST /fault/cpu?on=true           -> start/stop a background CPU burner
  POST /fault/errors?rate=0.2       -> return HTTP 500 for 20% of API requests (0 = off)
  POST /fault/retries?count=2       -> retry a failed attempt this many extra times
  POST /fault/client-retries?count=1 -> ask k6 to retry a failed request this many extra times
  POST /fault/downstream?ms=2000    -> extra delay standing in for a downstream call
  POST /fault/timeout?ms=1000       -> if downstream would take longer, return 504 at this budget
  POST /fault/leak?mb=64            -> hold this many extra megabytes (0 stops growing, memory stays)
  POST /fault/leak?release=true     -> free the held memory
  POST /fault/reset                 -> clear every fault except held leak memory

Env defaults: FAULT_LATENCY_MS, FAULT_CPU (true/false), FAULT_ERROR_RATE, BASE_ERROR_RATE (background flake rate, default 0.002).
"""

from __future__ import annotations

import hashlib
import logging
import os
import random
import threading
import time

from fastapi import FastAPI, HTTPException, Request, Response
from prometheus_client import CONTENT_TYPE_LATEST, Counter, Gauge, Histogram, generate_latest

log = logging.getLogger("demo-app")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")


def _env_bool(name: str, default: bool = False) -> bool:
    return os.getenv(name, str(default)).strip().lower() in {"1", "true", "yes", "on"}


RETRY_BACKOFF_S = 0.25
_LEAK_CHUNK = 1024 * 1024


# --------------------------------------------------------------------------- fault state
class FaultState:
    def __init__(self) -> None:
        self.lock = threading.Lock()
        self.latency_ms = float(os.getenv("FAULT_LATENCY_MS", "0"))
        self.error_rate = float(os.getenv("FAULT_ERROR_RATE", "0"))
        self.retries = 0
        self.client_retries = 0
        self.downstream_ms = 0.0
        self.timeout_ms = 0.0
        self.cpu_on = False
        self.leak_active = False
        self._leak_chunks: list[bytearray] = []
        self._cpu_stop = threading.Event()
        self._cpu_threads: list[threading.Thread] = []
        if _env_bool("FAULT_CPU"):
            self.set_cpu(True)

    def set_cpu(self, on: bool) -> None:
        with self.lock:
            if on and not self.cpu_on:
                self._cpu_stop.clear()
                n = int(os.getenv("CPU_BURN_THREADS", "2"))
                self._cpu_threads = [
                    threading.Thread(target=self._burn, daemon=True, name=f"cpu-burn-{i}") for i in range(n)
                ]
                for t in self._cpu_threads:
                    t.start()
                self.cpu_on = True
            elif not on and self.cpu_on:
                self._cpu_stop.set()
                self.cpu_on = False

    def _burn(self) -> None:
        # Pure-Python busy loop: holds the GIL most of the time, so it also slows request handling,
        # which is realistic (noisy neighbour / runaway work).
        x = 0
        while not self._cpu_stop.is_set():
            for _ in range(20_000):
                x = (x * 31 + 7) % 1_000_003
            time.sleep(0.0005)

    def set_leak(self, mb: float) -> None:
        """Grow held memory up to ``mb``. Zero stops further growth and keeps what is already held."""
        target = max(0, int(mb))
        with self.lock:
            while len(self._leak_chunks) < target:
                self._leak_chunks.append(bytearray(_LEAK_CHUNK))
            self.leak_active = target > 0

    def release_leak(self) -> None:
        with self.lock:
            self._leak_chunks.clear()
            self.leak_active = False

    def snapshot(self) -> dict:
        return {
            "latency_ms": self.latency_ms,
            "cpu_on": self.cpu_on,
            "error_rate": self.error_rate,
            "retries": self.retries,
            "client_retries": self.client_retries,
            "downstream_ms": self.downstream_ms,
            "timeout_ms": self.timeout_ms,
            "leak_mb": float(len(self._leak_chunks)),
            "leak_active": self.leak_active,
        }


faults = FaultState()

# --------------------------------------------------------------------------- prometheus metrics
REQS = Counter("http_requests_total", "HTTP requests", ["endpoint", "method", "status"])
LAT = Histogram(
    "http_request_duration_seconds",
    "HTTP request latency",
    ["endpoint"],
    buckets=(0.005, 0.01, 0.025, 0.05, 0.1, 0.2, 0.3, 0.5, 0.75, 1, 1.5, 2.5, 5),
)
INFLIGHT = Gauge("http_requests_in_flight", "In-flight HTTP requests")
QUEUE = Gauge("demo_work_queue_depth", "Simulated internal work queue depth")
FAULT = Gauge("demo_fault_active", "1 if a fault type is currently injected", ["type"])
FAULT_VALUE = Gauge("demo_fault_value", "Configured fault magnitude", ["type"])


def _publish_fault_gauges() -> None:
    s = faults.snapshot()
    active = {
        "latency": s["latency_ms"] > 0,
        "cpu": s["cpu_on"],
        "errors": s["error_rate"] > 0,
        "retries": s["retries"] > 0,
        "client_retries": s["client_retries"] > 0,
        "downstream": s["downstream_ms"] > 0,
        "timeout": s["timeout_ms"] > 0,
        "leak": s["leak_active"],
    }
    values = {
        "latency": s["latency_ms"],
        "cpu": 1 if s["cpu_on"] else 0,
        "errors": s["error_rate"],
        "retries": s["retries"],
        "client_retries": s["client_retries"],
        "downstream": s["downstream_ms"],
        "timeout": s["timeout_ms"],
        "leak": s["leak_mb"],
    }
    for kind, flag in active.items():
        FAULT.labels(kind).set(1 if flag else 0)
        FAULT_VALUE.labels(kind).set(values[kind])


_publish_fault_gauges()

# --------------------------------------------------------------------------- app
app = FastAPI(title="SRE PCA lab demo app")


# --------------------------------------------------------------------------- optional OpenTelemetry
def _setup_otel(application: FastAPI) -> None:
    if not _env_bool("OTEL_ENABLED", True):
        log.info("OpenTelemetry disabled (OTEL_ENABLED=false)")
        return
    try:
        from opentelemetry import metrics, trace
        from opentelemetry.exporter.otlp.proto.http.metric_exporter import OTLPMetricExporter
        from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
        from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
        from opentelemetry.sdk.metrics import MeterProvider
        from opentelemetry.sdk.metrics.export import PeriodicExportingMetricReader
        from opentelemetry.sdk.resources import Resource
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export import BatchSpanProcessor

        resource = Resource.create({"service.name": os.getenv("OTEL_SERVICE_NAME", "demo-app")})
        reader = PeriodicExportingMetricReader(OTLPMetricExporter(), export_interval_millis=10_000)
        metrics.set_meter_provider(MeterProvider(resource=resource, metric_readers=[reader]))
        tp = TracerProvider(resource=resource)
        tp.add_span_processor(BatchSpanProcessor(OTLPSpanExporter()))
        trace.set_tracer_provider(tp)
        FastAPIInstrumentor.instrument_app(application, excluded_urls="metrics,healthz")
        log.info("OpenTelemetry enabled -> %s", os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT", "(default)"))
    except Exception as exc:  # never let telemetry break the app
        log.warning("OpenTelemetry setup failed, continuing without it: %s", exc)


_setup_otel(app)


@app.middleware("http")
async def metrics_middleware(request: Request, call_next):
    path = request.url.path
    if path in ("/metrics", "/healthz") or path.startswith("/fault"):
        return await call_next(request)
    start = time.perf_counter()
    INFLIGHT.inc()
    status = 500
    try:
        response = await call_next(request)
        status = response.status_code
        return response
    finally:
        INFLIGHT.dec()
        route = request.scope.get("route")
        endpoint = getattr(route, "path", "unmatched")
        LAT.labels(endpoint).observe(time.perf_counter() - start)
        REQS.labels(endpoint, request.method, str(status)).inc()


BASE_ERROR_RATE = float(os.getenv("BASE_ERROR_RATE", "0.002"))  # realistic background noise


def _fault_once(s: dict) -> None:
    if BASE_ERROR_RATE > 0 and random.random() < BASE_ERROR_RATE:
        raise HTTPException(status_code=503, detail="background flake")
    if s["latency_ms"] > 0:
        time.sleep((s["latency_ms"] + random.uniform(-0.2, 0.2) * s["latency_ms"]) / 1000.0)
    if s["downstream_ms"] > 0:
        if s["timeout_ms"] > 0 and s["downstream_ms"] > s["timeout_ms"]:
            time.sleep(s["timeout_ms"] / 1000.0)
            raise HTTPException(status_code=504, detail="downstream timeout")
        time.sleep(s["downstream_ms"] / 1000.0)
    if s["error_rate"] > 0 and random.random() < s["error_rate"]:
        raise HTTPException(status_code=500, detail="injected error")


def _apply_faults() -> None:
    """Apply the current faults. Server retries repeat a failed attempt, so errors cost latency."""
    s = faults.snapshot()
    attempts = 1 + max(0, int(s["retries"]))
    for attempt in range(attempts):
        try:
            _fault_once(s)
            return
        except HTTPException:
            if attempt + 1 == attempts:
                raise
            time.sleep(RETRY_BACKOFF_S)


# Plain `def` handlers run in FastAPI's threadpool, so time.sleep / CPU work do not block the loop.
@app.get("/api/items")
def list_items():
    _apply_faults()
    time.sleep(random.uniform(0.005, 0.02))  # pretend DB call
    return {"items": [{"id": i, "name": f"item-{i}"} for i in range(10)]}


@app.get("/api/work")
def do_work(n: int = 2000):
    _apply_faults()
    QUEUE.inc()
    try:
        h = b"seed"
        for _ in range(max(1, min(n, 50_000))):
            h = hashlib.sha256(h).digest()
        return {"digest": h.hex()[:16]}
    finally:
        QUEUE.dec()


@app.get("/healthz")
def healthz():
    return {"ok": True}


@app.get("/metrics")
def prom_metrics():
    _publish_fault_gauges()
    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)


# --------------------------------------------------------------------------- fault endpoints
@app.get("/fault")
def get_fault():
    return faults.snapshot()


@app.post("/fault/latency")
def set_latency(ms: float = 300):
    faults.latency_ms = max(0.0, ms)
    _publish_fault_gauges()
    log.info("fault latency_ms=%s", faults.latency_ms)
    return faults.snapshot()


@app.post("/fault/cpu")
def set_cpu(on: bool = True):
    faults.set_cpu(on)
    _publish_fault_gauges()
    log.info("fault cpu_on=%s", faults.cpu_on)
    return faults.snapshot()


@app.post("/fault/errors")
def set_errors(rate: float = 0.2):
    faults.error_rate = min(1.0, max(0.0, rate))
    _publish_fault_gauges()
    log.info("fault error_rate=%s", faults.error_rate)
    return faults.snapshot()


@app.post("/fault/retries")
def set_retries(count: int = 2):
    faults.retries = max(0, count)
    _publish_fault_gauges()
    log.info("fault retries=%s", faults.retries)
    return faults.snapshot()


@app.post("/fault/client-retries")
def set_client_retries(count: int = 1):
    faults.client_retries = max(0, count)
    _publish_fault_gauges()
    log.info("fault client_retries=%s", faults.client_retries)
    return faults.snapshot()


@app.post("/fault/downstream")
def set_downstream(ms: float = 2000):
    faults.downstream_ms = max(0.0, ms)
    _publish_fault_gauges()
    log.info("fault downstream_ms=%s", faults.downstream_ms)
    return faults.snapshot()


@app.post("/fault/timeout")
def set_timeout(ms: float = 1000):
    faults.timeout_ms = max(0.0, ms)
    _publish_fault_gauges()
    log.info("fault timeout_ms=%s", faults.timeout_ms)
    return faults.snapshot()


@app.post("/fault/leak")
def set_leak(mb: float | None = None, release: bool = False):
    if release:
        faults.release_leak()
    elif mb is not None:
        faults.set_leak(mb)
    _publish_fault_gauges()
    log.info("fault leak_mb=%s active=%s", faults.snapshot()["leak_mb"], faults.leak_active)
    return faults.snapshot()


@app.post("/fault/reset")
def reset():
    faults.latency_ms = 0
    faults.error_rate = 0
    faults.retries = 0
    faults.client_retries = 0
    faults.downstream_ms = 0.0
    faults.timeout_ms = 0.0
    faults.set_cpu(False)
    _publish_fault_gauges()
    log.info("faults reset")
    return faults.snapshot()
