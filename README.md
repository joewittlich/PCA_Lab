# SRE PCA Lab

A local, vendor-agnostic sandbox for trying **PCA / reconstruction-error anomaly detection** on
service metrics. Everything is open source and runs on your laptop with Docker.

```
 k6 load ──► demo-app (FastAPI) ──OTLP──► OpenTelemetry Collector ──┐
              │  /metrics  ▲ fault toggles                          │ :8889
              ▼            │ (latency / CPU / errors)               ▼
        node-exporter ──► Prometheus  ◄─────────────────────────────┘
                           │   ▲
                 Grafana ◄─┘   └── Python (pandas, scikit-learn, Jupyter): PCA, scree,
                                    PC1/PC2, reconstruction error, inverse transform
```

| Piece | What it's for |
|---|---|
| **demo-app** | Small FastAPI service. Exposes Prometheus metrics, sends OpenTelemetry metrics/traces, and lets you inject faults. |
| **OpenTelemetry Collector** | Vendor-neutral pipeline. Receives OTLP and re-exposes metrics for Prometheus. Point it at any backend later. |
| **Prometheus** | Time-series storage + PromQL. The notebook pulls data from its HTTP API. |
| **node-exporter** | Host metrics (CPU, load, memory). See the note on Docker Desktop below. |
| **Grafana** | Dashboards. Prometheus data source and a starter dashboard are pre-provisioned. |
| **k6** | Load generator (a Compose *profile*, so it only runs when you ask). |
| **Python (uv)** | `src/sre_pca/` holds the core logic. `notebooks/` has the step-by-step notebook. |

---

## 1. Prerequisites (starting from nothing)

You need **Git**, **Docker** (with Compose v2), and **uv**, which installs Python 3.12 for you.
The bootstrap scripts install only what's missing and are safe to re-run.

You'll need about 4 GB of free RAM for Docker and about 3 GB of disk for the images and Python packages.

### Windows 10/11

1. Get the repo onto your machine. Unzip `sre-pca-lab.zip` somewhere like `C:\dev\sre-pca-lab`. Avoid OneDrive-synced folders.
2. Open **PowerShell as Administrator** (Start, type *PowerShell*, then *Run as administrator*):
   ```powershell
   cd C:\dev\sre-pca-lab
   powershell -ExecutionPolicy Bypass -File .\scripts\bootstrap.ps1
   ```
   This uses `winget` to install Git, Docker Desktop and uv. It also runs `wsl --install --no-distribution` if WSL2 is missing, then installs Python 3.12 and the project's packages.
3. **Reboot if it asks.** WSL2 and Docker Desktop need one. After the reboot, start **Docker Desktop** from the Start menu, accept the terms, and wait for "Engine running". Then run the bootstrap again to finish:
   ```powershell
   powershell -ExecutionPolicy Bypass -File .\scripts\bootstrap.ps1
   ```
4. From now on, use a normal (non-admin) PowerShell with `.\scripts\lab.ps1 <command>`.
   If scripts are blocked, run once: `Set-ExecutionPolicy -Scope CurrentUser RemoteSigned`.

> **WSL2 note:** Docker Desktop on Windows runs containers inside a lightweight WSL2 VM. You don't
> need to use a Linux distro yourself. If you *do* work inside WSL (Ubuntu), enable
> *Docker Desktop → Settings → Resources → WSL integration* for that distro and use the
> macOS/Linux commands from inside it.

### macOS

```bash
cd ~/dev/sre-pca-lab          # wherever you unzipped it
./scripts/bootstrap.sh         # installs Homebrew if needed, then git, uv, Docker Desktop
open -a Docker                 # first run: accept prompts, wait for "Engine running"
```
Prefer not to use Docker Desktop? OrbStack (`brew install --cask orbstack`) or Colima also work. Any engine that provides `docker compose` will do.

### Linux (Debian/Ubuntu; dnf/pacman get the basics)

```bash
cd ~/dev/sre-pca-lab
./scripts/bootstrap.sh         # apt: git curl make; Docker via https://get.docker.com; uv via astral.sh
newgrp docker                  # or log out/in, so you can run docker without sudo
```

### Without uv (pip fallback)

```bash
python3 -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements.txt    # also installs this repo (src/sre_pca) in editable mode
```
`lab.sh` and `lab.ps1` automatically use `.venv` when uv isn't installed.

---

## 2. Quickstart

| Step | macOS / Linux | Windows PowerShell |
|---|---|---|
| Start stack | `./scripts/lab.sh up` (or `make up`) | `.\scripts\lab.ps1 up` |
| Check health | `./scripts/lab.sh status` | `.\scripts\lab.ps1 status` |
| Generate load (terminal 1) | `./scripts/lab.sh load 30m 20` | `.\scripts\lab.ps1 load 30m 20` |
| Scripted faults (terminal 2) | `./scripts/lab.sh scenario` | `.\scripts\lab.ps1 scenario` |
| Analyze | `./scripts/lab.sh analyze --minutes 30` | `.\scripts\lab.ps1 analyze --minutes 30` |
| Notebook | `./scripts/lab.sh notebook` | `.\scripts\lab.ps1 notebook` |
| Stop | `./scripts/lab.sh down` | `.\scripts\lab.ps1 down` |

The first `up` downloads about 1.5 GB of images and builds the app, so it takes a few minutes. `status` should then show
every Prometheus target as `up`.

### URLs and ports

| Service | URL | Notes |
|---|---|---|
| Grafana | http://localhost:3000 | login **admin / admin** (it will offer to change it; you can skip). Dashboard: *SRE PCA Lab → SRE PCA Lab - Demo App* |
| Prometheus | http://localhost:9090 | *Status → Targets* shows scrape health |
| Demo app | http://localhost:8000/docs | Swagger UI. You can toggle faults from here too |
| Demo app metrics | http://localhost:8000/metrics | |
| node-exporter | http://localhost:9100/metrics | |
| OTel Collector | 4317 (gRPC), 4318 (HTTP) OTLP in; http://localhost:8889/metrics re-exported app metrics | |

You can change any host port: `cp .env.example .env` and edit it. On Windows, use `copy .env.example .env`.

---

## 3. Running an experiment

PCA needs a **baseline**, a stretch of known-normal behaviour to learn from. Then you inject faults and
see if the reconstruction error catches them.

**1. Start load and leave it running.** It's a steady rate with a slow 5-minute wave, so the baseline isn't perfectly flat:
```bash
./scripts/lab.sh load 30m 20            # duration, average requests/sec
```

**2. Inject faults.** In a second terminal, either run the scripted scenario:
```bash
./scripts/lab.sh scenario               # 10 min baseline, then latency / CPU / errors for 3 min each, 3 min gaps (~28 min)
./scripts/lab.sh scenario --baseline-min 5 --fault-min 2 --gap-min 2   # quicker (~17 min)
```
Or toggle faults by hand:
```bash
./scripts/lab.sh fault latency 300      # +300 ms per request   (0 = off)
./scripts/lab.sh fault cpu on           # background CPU burner (off = stop)
./scripts/lab.sh fault errors 0.2       # 20% HTTP 500s         (0 = off)
./scripts/lab.sh fault reset            # all off
./scripts/lab.sh fault status
```
Plain HTTP works too, from any language. For example: `curl -X POST "localhost:8000/fault/latency?ms=300"`, or in PowerShell
`Invoke-RestMethod -Method Post "http://localhost:8000/fault/latency?ms=300"`.

Faults can also be set when the app starts, through env vars in `.env`: `FAULT_LATENCY_MS`, `FAULT_CPU`, `FAULT_ERROR_RATE`.
The app also has a small background error rate (`BASE_ERROR_RATE=0.002`) so "errors" isn't a constant 0.

Every fault toggle is recorded in the `demo_fault_active{type=...}` metric. The analysis uses it to **shade the fault periods**
and to keep fault samples out of the baseline.

**3. Analyze.**
```bash
./scripts/lab.sh analyze --minutes 30   # prints explained variance, loadings, detection rates, inverse example
```
This writes plots and data to `reports/`: `pca_scree_scatter.png`, `recon_error.png`, `raw_metrics.png`, `scores.csv` and `summary.json`.
Useful flags:

| Flag | Meaning |
|---|---|
| `--source auto\|prometheus\|synthetic` | `auto` falls back to synthetic data if Prometheus isn't reachable |
| `--baseline-minutes N` | Fit on the first N minutes. The default is everything before the first injected fault. |
| `--var-target 0.9` / `--k 3` | How many PCs to keep |
| `--quantile 0.99` | Threshold = this quantile of baseline reconstruction error |
| `--deseason stl --period 20` | Remove a cycle first. The period is in samples: the k6 wave is 300 s / 15 s = 20, and a real day at 15 s is 5760. |
| `--pc-point 3,-2` | PC point to back-calculate into descriptor values |
| `--drop a,b` | Leave descriptors out, e.g. slow-drifting levels like `app_rss_mb,node_mem_used_frac` |

**4. Notebook.**
```bash
./scripts/lab.sh notebook               # opens JupyterLab → sre_pca_starter.ipynb
```
The notebook walks through each step with the math: it pulls data from the Prometheus API, aligns it, standardizes it, optionally removes seasonality, fits PCA on the
baseline, then shows the scree plot, the PC1/PC2 scatter, reconstruction error over time with fault shading, and the **inverse
transform** (x = μ + σ ⊙ zWᵀ), including a check that the back-calculated point projects back to where you chose.
If Prometheus isn't running, it uses synthetic data, so you can explore it before Docker works.
`notebooks/make_notebook.py` regenerates the notebook from code.

**No Docker yet?** Run `./scripts/lab.sh synthetic` (or `uv run sre-pca --source synthetic`) and `./scripts/lab.sh test`.
Both run on generated data.

### What's in the feature matrix

The analysis uses 11 descriptors, each one PromQL expression (`src/sre_pca/prom.py`, `DEFAULT_QUERIES`): request rate,
error ratio, p50/p95/mean latency, in-flight requests, app CPU, app RSS, node CPU busy, node load1 and
node memory used. To add your own, add a line to that dict. Each expression has to return one series, so aggregate with `sum`/`max`.

---

## 4. Note on node-exporter and Docker Desktop

node-exporter reports on **the Linux kernel it runs on**. On native Linux that's your machine. On
**Docker Desktop (Windows/macOS) it's Docker's Linux VM**, not your laptop. Its CPU/memory are still a
good host-level signal for these experiments, since all the containers run in that VM. Just don't read it
as your Windows/Mac CPU. Some collectors, like filesystems, will show the VM's disks.

---

## 5. Troubleshooting

| Symptom | Fix |
|---|---|
| `Cannot connect to the Docker daemon` / `docker info` fails / `lab` says "Docker is not running" | Start Docker Desktop and wait for *Engine running*. On Linux: `sudo systemctl start docker`, and log out/in after being added to the `docker` group (or use `newgrp docker`). |
| Docker Desktop: "WSL 2 installation is incomplete" / "Virtualization not enabled" | Run `wsl --install --no-distribution` then `wsl --update` in an admin PowerShell and reboot. Enable virtualization (Intel VT-x / AMD-V / SVM) in BIOS/UEFI. Check *Task Manager → Performance → CPU → Virtualization*. |
| `Bind for 0.0.0.0:3000 failed: port is already allocated` (or 9090/8000/…) | Something else uses the port. Copy `.env.example` to `.env`, change e.g. `GRAFANA_PORT=3001`, and run `up` again. To find the culprit: `lsof -i :3000` (mac/Linux) or `netstat -ano \| findstr :3000` (Windows). |
| `status` shows a target `down` | Give it 30 s after `up`. Then `./scripts/lab.sh logs <service>`. For `demo-app` down, check `docker compose logs demo-app`. |
| Analysis says "too little data" / uses synthetic | Prometheus needs a few minutes of data with load running. Use `--source prometheus` to get an error instead of the fallback. |
| "Normal" time after the faults is still flagged | That's often real: after a fault, memory levels like `app_rss_mb` settle at a new level, and on Docker Desktop `node_mem_used_frac` moves with everything else on the VM. Use a longer baseline, or `--drop app_rss_mb,node_mem_used_frac` to model rates and latencies only. Up to about 1 min after a fault ends, the `rate(...[1m])` windows are still catching up. |
| Every sample is flagged / nothing is flagged | Make sure the baseline is a calm period with load running (`--baseline-minutes`). Try a different `--k` or `--quantile`, or run a longer baseline. |
| PowerShell: "running scripts is disabled on this system" | `Set-ExecutionPolicy -Scope CurrentUser RemoteSigned`, or prefix with `powershell -ExecutionPolicy Bypass -File`. |
| `permission denied: ./scripts/lab.sh` (macOS/Linux) | `chmod +x scripts/*.sh`, or run it as `bash scripts/lab.sh ...` |
| `uv` not found right after install | Open a new terminal so PATH updates. On Windows, it's in `%USERPROFILE%\.local\bin`. |
| Corporate proxy / image pulls fail | Configure the proxy in Docker Desktop → Settings → Resources → Proxies. For uv, set `HTTPS_PROXY`. |
| Start completely fresh | `./scripts/lab.sh nuke`. This deletes the Prometheus and Grafana volumes. |
| Apple Silicon | All images are multi-arch. Nothing special is needed. |

---

## 6. Next steps

- **Export the anomaly score back to Prometheus.** `uv run sre-pca-exporter` (or `lab.sh exporter`) fits PCA on the
  last 30 minutes, treated as normal, then serves `sre_pca_reconstruction_error`, `sre_pca_threshold`, `sre_pca_anomaly` and
  `sre_pca_pc_score{pc=...}` on `:9105`. Uncomment the `sre-pca-anomaly` job in `config/prometheus/prometheus.yml`,
  then reload with `curl -X POST localhost:9090/-/reload` (or `./scripts/lab.sh down; ./scripts/lab.sh up`). The dashboard's
  *PCA anomaly score* panel fills in, and you can alert on it with an ordinary Prometheus/Grafana alert rule such as
  `sre_pca_reconstruction_error > sre_pca_threshold for 2m`. Later, package the exporter as another Compose service.
  To check the age of the displayed score in seconds, query `time() - sre_pca_last_scored_timestamp_seconds`.
  The gauge is zero until the first score. It records the Prometheus query timestamp of the latest scored row
  with finite values for all trained features. A scrape can succeed while this timestamp and the score stay unchanged.
- **Seasonality.** With days of data, fit per time-of-day, or use `--deseason stl --period 5760` (1 day at 15 s), so
  Monday morning doesn't look like an incident.
- **Compare detectors.** Try `IsolationForest` or a simple z-score per metric on the same standardized matrix, and Hotelling's T²
  for "big move *along* normal directions" alongside SPE, which catches moves *off* them.
- **Per-host / per-pod view.** Scale up with `kind`/`k3d`, then plot each pod as a dot in PC1/PC2 space.
- **Bigger data.** Use Polars or DuckDB (`uv sync --extra extras`) and VictoriaMetrics or Thanos for long retention. All of them speak PromQL, so the code stays the same.
- **Real services.** Point any OpenTelemetry-instrumented app at `localhost:4317/4318`, or add a Prometheus scrape job,
  then edit `DEFAULT_QUERIES`.

---

## Repo layout

```
app/                     demo FastAPI service (Dockerfile, fault endpoints, metrics)
config/otel/             OpenTelemetry Collector config
config/prometheus/       scrape config
config/grafana/          provisioned datasource + dashboard
load/load.js             k6 load profile
notebooks/               starter notebook (+ generator script)
src/sre_pca/             core.py (PCA logic), prom.py (Prometheus API), synthetic.py, plots.py,
                         cli.py (sre-pca), fault.py (sre-fault), scenario.py (sre-scenario), exporter.py
scripts/                 bootstrap.ps1 / bootstrap.sh, lab.ps1 / lab.sh
tests/                   pytest: core math + notebook execution on synthetic data
reports/                 analysis outputs (git-ignored)
```

Pinned images: `otel/opentelemetry-collector-contrib:0.114.0`, `prom/prometheus:v2.55.1`,
`prom/node-exporter:v1.8.2`, `grafana/grafana:11.3.1`, `grafana/k6:0.55.0`, and `python:3.12.8-slim-bookworm` for the app.
Bump them together and re-run `status` to confirm.
