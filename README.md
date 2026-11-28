# SRE PCA Lab

A local, vendor-agnostic sandbox for trying **PCA / reconstruction-error anomaly detection** on
service metrics. Use Docker Compose to generate live observations from the demo service. Use the
Python CLI or notebook to study generated data. The recorded on-call exercise needs only a browser.

**Preparing for your first on-call rotation?** Download and extract the repository ZIP, then open
`docs/first-on-call/en-US/index.html` in your browser. The [US English lesson](docs/first-on-call/en-US/index.html)
includes the incident exercise, a facilitator guide, and a local report reader. You can copy the HTML file alone
to run the activity offline. Copy the entire `first-on-call` folder to include the example reports and
[translation resources](docs/first-on-call/en-US/translation-guide.html).

After a lab run, select `reports/scores.csv` or `reports/summary.json` on the page to explore the results.
The browser reads the files you choose. Use the [lesson review notes](docs/first-on-call/en-US/README.md)
to trace the recorded case back to its evidence or review an edit with a learner.

```
k6 generates requests to the demo app.

demo-app /metrics            -> Prometheus
demo-app -> OTLP -> Collector -> Prometheus (scrapes the Collector on port 8889)
node-exporter /metrics       -> Prometheus

Grafana, the notebook, and the Python CLI query Prometheus.
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

For the live experiment, the setup below uses **Git**, **Docker** (with Compose v2), and **uv**, which installs Python 3.12 for you.
On macOS, Linux, or WSL, run `chmod +x scripts/bootstrap.sh scripts/lab.sh` after extracting or cloning the repository so the shell and Make commands below can start the scripts.
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

A single timed session, from `up` through the written report, is in [docs/quickstart.md](docs/quickstart.md).

| Step | macOS / Linux | Windows PowerShell |
|---|---|---|
| Start stack | `./scripts/lab.sh up` (or `make up`) | `.\scripts\lab.ps1 up` |
| Check health | `./scripts/lab.sh status` | `.\scripts\lab.ps1 status` |
| Generate load (terminal 1) | `./scripts/lab.sh load 40m 20` | `.\scripts\lab.ps1 load 40m 20` |
| Scripted faults (terminal 2) | `./scripts/lab.sh scenario` | `.\scripts\lab.ps1 scenario` |
| Analyze | `./scripts/lab.sh analyze --run latest` | `.\scripts\lab.ps1 analyze --run latest` |
| Notebook | `./scripts/lab.sh notebook` | `.\scripts\lab.ps1 notebook` |
| Stop | `./scripts/lab.sh down` | `.\scripts\lab.ps1 down` |

The first `up` downloads about 1.5 GB of images and builds the app, so it takes a few minutes. `status` should then show
every Prometheus target as `up`. `load` records `reports/runs/<run_id>.json`, and the scenario completes that file.
`./scripts/lab.sh test-short` (PowerShell: `.\scripts\lab.ps1 test-short`) runs a live five-minute check of the same path
and writes `reports/short-run/`. The stack must already be up. Ordinary `test` stays offline and skips it.

### URLs and ports

| Service | URL | Notes |
|---|---|---|
| Grafana | http://localhost:3000 | login **admin / admin** (it will offer to change it; you can skip). Dashboard: *SRE PCA Lab → SRE PCA Lab - Demo App* |
| Prometheus | http://localhost:9090 | *Status → Targets* shows scrape health |
| Demo app | http://localhost:8000/docs | Swagger UI. You can toggle faults from here too |
| Demo app metrics | http://localhost:8000/metrics | |
| node-exporter | http://localhost:9100/metrics | |
| OTel Collector | 4317 (gRPC), 4318 (HTTP) OTLP in; http://localhost:8889/metrics re-exported app metrics | |

To change a published Compose port, copy `.env.example` to `.env` and edit it. The host scripts also need the new addresses. For example, for `PROMETHEUS_PORT=9091`, set `export PROM_URL=http://localhost:9091` in Bash or `$env:PROM_URL = 'http://localhost:9091'` in PowerShell before running `status` or `analyze`. If you change the app port, set `APP_URL` before using the fault or scenario commands.

---

## 3. Running an experiment

PCA needs a **baseline**, a stretch of known-normal behaviour to learn from. Then you inject faults and
see if the reconstruction error catches them.

**1. Start load and leave it running.** It's a steady rate with a slow 5-minute wave, so the baseline isn't perfectly flat:
```bash
./scripts/lab.sh load 40m 20            # duration, average requests/sec; outlasts the 28-minute scenario
```

**2. Inject faults.** In a second terminal, either run the scripted scenario:
```bash
./scripts/lab.sh scenario               # 10 min baseline, then latency / CPU / errors for 3 min each, 3 min gaps (~28 min)
./scripts/lab.sh scenario --baseline-min 5 --fault-min 2 --gap-min 2   # quicker (~17 min)
```
A second session, after this one, is the three-hour profile in [docs/long-run.md](docs/long-run.md): the same three faults, then retries, a downstream timeout, and a leak that outlives its gauge. Start it with `./scripts/lab.sh scenario --profile long` while `load-bg 3h30m 20` is running.

Or toggle faults by hand:
```bash
./scripts/lab.sh fault latency 300      # +300 ms per request   (0 = off)
./scripts/lab.sh fault cpu on           # background CPU burner (off = stop)
./scripts/lab.sh fault errors 0.2       # 20% HTTP 500s         (0 = off)
./scripts/lab.sh fault reset            # clear latency, CPU, and errors (held leak memory stays)
./scripts/lab.sh fault status
```
Plain HTTP works too, from any language. For example: `curl -X POST "localhost:8000/fault/latency?ms=300"`, or in PowerShell
`Invoke-RestMethod -Method Post "http://localhost:8000/fault/latency?ms=300"`.

Faults can also be set when the app starts, through env vars in `.env`: `FAULT_LATENCY_MS`, `FAULT_CPU`, `FAULT_ERROR_RATE`.
The app also has a small background error rate (`BASE_ERROR_RATE=0.002`) so "errors" isn't a constant 0.

Every fault toggle is recorded in the `demo_fault_active{type=...}` metric. The analysis uses it to **shade the fault periods**
and to keep fault samples out of the baseline.

`load` writes `reports/runs/<run_id>.json` with the load start, planned end, and rate. The scenario adds its start, the first fault time, and its finish time to that file (or starts a new file and copies the load block when the previous scenario already finished). Ctrl+C still clears the faults and records `scenario.end`, with `"status": "interrupted"`.

**3. Analyze.** When the scenario finishes it prints the command to reopen that window, including if you come back later:
```bash
./scripts/lab.sh analyze --run latest
```
`--run latest` reads the newest manifest. `--run <run_id>` or a path to the JSON file selects one run. The query starts two minutes before the load start (or the scenario start, when no load time was recorded) and ends two minutes after the scenario end. Training uses the loaded stretch up to two minutes before the first fault, so the quiet period before k6 and the `rate()[1m]` ramp stay out of the fit. That interval has to leave at least 20 samples, about seven minutes of loaded time before the first fault at a 15-second step. Otherwise the summary's `baseline_rule` is `first_fraction` (the first 40% of the pulled window). Samples after `scenario.end` are scored as `after_run` and stay out of the held-out normal row.

`--minutes 30` is still a lookback from the moment you run the command. It does not remember when the scenario happened. `--start` and `--end` take an explicit UTC window and override both `--run` and `--minutes`.

This writes plots and data to `reports/`: `pca_scree_scatter.png`, `recon_error.png`, `raw_metrics.png`, `scores.csv` and `summary.json`. The summary includes `run_id`, the query window, the data span, `baseline_start` / `baseline_end` / `baseline_rule`, and `fault_intervals`. When the manifest recorded chapters, the summary also lists each chapter's flagged fraction, time to the first flag, and contributors in the order they appeared.
Useful flags:

| Flag | Meaning |
|---|---|
| `--run latest` / `--run <id>` | Analyze the window stored in `reports/runs/<id>.json` |
| `--start` / `--end` | Explicit UTC ISO-8601 window. Overrides `--run` and `--minutes` |
| `--minutes N` | Lookback from `--end` (default: now) when `--run` and `--start` are omitted |
| `--source auto\|prometheus\|synthetic` | `auto` uses synthetic data if Prometheus is unreachable or has fewer than 20 rows with any metric value. Check `source` in `summary.json`. |
| `--baseline-minutes N` | Fit on the first N minutes of the pulled window. Overrides the manifest baseline. With a manifest, the default is the loaded stretch up to two minutes before the first fault. Otherwise the lab leaves eight samples between training and the first labeled fault. If that leaves fewer than 20 rows, or there is no labeled fault, the default uses the first 40% of the series (at least 20 rows if available). It then excludes labeled fault rows. |
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
To check notebook execution from a terminal, run `uv run pytest -q tests/test_notebook.py`.
On Windows, this test uses a dedicated event loop to read messages from the Jupyter kernel.

**No Docker yet?** Run `./scripts/lab.sh synthetic` (or `uv run sre-pca --source synthetic`) and `./scripts/lab.sh test`.
The synthetic command analyzes generated data. The default tests are offline and also cover the exporter, detector comparison, and lesson translation tool. `test-short` is the live five-minute session and needs the stack.

### Optional experiment: ordinary CPU at unusually low traffic

Run `uv run python -m sre_pca.benchmark` for a fixed-seed, offline comparison using request rate and
app CPU. Both detectors train on the first 60 healthy minutes. The per-metric rule flags a row if
either value falls outside its observed baseline minimum and maximum. PCA keeps one component and
flags reconstruction errors above the **largest baseline error**. Both rules therefore flag zero
training rows, and their thresholds stay fixed throughout evaluation.

The next 45 minutes measure false alarms under healthy traffic. During the final five minutes, the
benchmark replays CPU readings from baseline minutes 5–10, when traffic was high, alongside the
current, lower request rates. Each metric stays within its own baseline range during the replay.

| Detector | Healthy rows flagged (false alarms) | Replay rows flagged (detections) |
|---|---:|---:|
| Per-metric bounds | 14/180 (7.8%) | 0/20 (0%) |
| PCA reconstruction error | 1/180 (0.6%) | 20/20 (100%) |

For this synthetic workload, a healthy high-traffic CPU reading is unusual when paired with low
traffic. The PCA score measures how far that pairing falls from the learned relationship. The percentages count individual samples in each evaluation window. For training thresholds and checks you can reproduce, see the [analysis package guide](src/sre_pca/README.md).

### Predict what PCA will flag

Download and extract the repository, then open any of these US English HTML files in a browser.
Each is an independent five-minute exercise with its own prediction, answer reveal, and notes.
You can use one file offline, alone or with a partner.

- [Same size change, different direction](docs/first-on-call/en-US/direction.html) asks whether high traffic can have a low score.
- [A fault enters the training data](docs/first-on-call/en-US/training.html) compares two models on the same simulated incident.
- [New timestamps, repeated readings](docs/first-on-call/en-US/readings.html) asks how to tell steady traffic from a sensor repeating an old reading.

To reproduce all three results with the project dependencies, run `uv run python -m sre_pca.prediction_exercises`.
The [facilitator and review notes](docs/first-on-call/en-US/prediction-exercises.md) connect each discussion to its simulation.

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
| The analysis missed the scenario | `--minutes` looks back from the moment you run it. Use the command the scenario printed, or `--run latest`, so the window comes from `reports/runs/<id>.json`. |
| `baseline_rule` is `first_fraction` | The manifest baseline had fewer than 20 samples after the two-minute trim. Give the loaded period about seven minutes before the first fault at a 15-second step. `summary.json` records which rule was used. |
| `after_run` is mostly flagged | Those samples are after `scenario.end`. They are separate from the held-out normal row. A quiet stretch after k6 stops often flags. |
| "Normal" time after the faults is still flagged | That's often real: after a fault, memory levels like `app_rss_mb` settle at a new level, and on Docker Desktop `node_mem_used_frac` moves with everything else on the VM. Use a longer baseline, or `--drop app_rss_mb,node_mem_used_frac` to model rates and latencies only. Up to about 1 min after a fault ends, the `rate(...[1m])` windows are still catching up. |
| Every sample is flagged / nothing is flagged | Make sure the baseline is a healthy period with load running (`--baseline-minutes`). Try a different `--k` or `--quantile`, or run a longer baseline. |
| PowerShell: "running scripts is disabled on this system" | `Set-ExecutionPolicy -Scope CurrentUser RemoteSigned`, or prefix with `powershell -ExecutionPolicy Bypass -File`. |
| `permission denied: ./scripts/lab.sh` (macOS/Linux) | `chmod +x scripts/*.sh`, or run it as `bash scripts/lab.sh ...` |
| `uv` not found right after install | Open a new terminal so PATH updates. On Windows, it's in `%USERPROFILE%\.local\bin`. |
| Corporate proxy / image pulls fail | Configure the proxy in Docker Desktop → Settings → Resources → Proxies. For uv, set `HTTPS_PROXY`. |
| Start completely fresh | `./scripts/lab.sh nuke`. This deletes the Prometheus and Grafana volumes. |
| Apple Silicon | All images are multi-arch. Nothing special is needed. |

---

## 6. Optional live score in Grafana

Start the exporter on your host with `uv run sre-pca-exporter`. It fits PCA on recent data
(default 30 minutes). Choose a healthy period for training. The exporter excludes rows with a fault label.
It serves the score, threshold, anomaly flag, and component scores on port 9105.

1. Enable the `sre-pca-anomaly` job in the [Prometheus configuration](config/prometheus/prometheus.yml).
2. Reload Prometheus with `curl -X POST http://localhost:9090/-/reload` (default port). Open the
   *PCA anomaly score* panel in Grafana.
3. Check `sre_pca_last_scored_timestamp_seconds`. Zero means the exporter is waiting for its first
   complete row. After that, query `time() - sre_pca_last_scored_timestamp_seconds` to get the score's
   age in seconds. A scrape can succeed while the score stays unchanged. See the
   [exporter review notes](src/sre_pca/README.md#review-the-live-score).

To try an alert, use `sre_pca_reconstruction_error > sre_pca_threshold` as the expression and
`for: 2m` as the rule duration. Before paging someone, check whether flagged periods coincide
with user impact and how often healthy traffic triggers the rule.

## 7. Next steps

- **Package the exporter** as a Compose service if you want to run it with the rest of the stack.
- **Seasonality.** With days of data, fit per time-of-day, or use `--deseason stl --period 5760` (1 day at 15 s), so
  Monday morning doesn't look like an incident.
- **Extend the [detector comparison](src/sre_pca/benchmark.py).** Try `IsolationForest` or a simple z-score per metric on the same standardized matrix, and Hotelling's T²
  for "big move *along* normal directions" alongside SPE, which catches moves *off* them.
- **Per-host / per-pod view.** Scale up with `kind`/`k3d`, then plot each pod as a dot in PC1/PC2 space.
- **Bigger data.** The optional Python packages include Polars and DuckDB (`uv sync --extra extras`) for local data analysis. To try longer metric retention, point the lab at a compatible Prometheus query API and check that each feature query still returns one series.
- **Real services.** Point any OpenTelemetry-instrumented app at `localhost:4317/4318`, or add a Prometheus scrape job,
  then edit `DEFAULT_QUERIES`.

---

## Repo layout

```
app/                     demo FastAPI service (Dockerfile, fault endpoints, metrics)
config/otel/             OpenTelemetry Collector config
config/prometheus/       scrape config
config/grafana/          provisioned datasource + dashboard
docs/quickstart.md       first session, from startup through the report
docs/long-run.md         second session: the three-hour scenario
docs/first-on-call/      offline lesson, facilitator guide, translation resources, and recorded evidence
load/load.js             k6 load profile
notebooks/               starter notebook (+ generator script)
src/sre_pca/             core.py (PCA logic), prom.py (Prometheus API), synthetic.py, plots.py,
                         cli.py (sre-pca), fault.py (sre-fault), scenario.py (sre-scenario),
                         runs.py (run manifests), exporter.py, benchmark.py,
                         prediction_exercises.py
scripts/                 bootstrap.ps1 / bootstrap.sh, lab.ps1 / lab.sh
tests/                   pytest. The default run is offline: PCA math, notebook execution,
                         exporter freshness, benchmark, lesson localization, prediction exercises.
                         `test-short` is a live 5-minute session that writes `reports/short-run/`
                         (stack must already be up)
reports/                 analysis outputs, gitignored except .gitkeep: plots, scores.csv, summary.json
reports/runs/            one JSON manifest per load/scenario (`latest` names the newest)
reports/short-run/       record from `test-short` (record.json, summary, scores, plots)
```

Pinned images: `otel/opentelemetry-collector-contrib:0.114.0`, `prom/prometheus:v2.55.1`,
`prom/node-exporter:v1.8.2`, `grafana/grafana:11.3.1`, `grafana/k6:0.55.0`, and `python:3.12.8-slim-bookworm` for the app.
Bump them together and re-run `status` to confirm.
