# Session quickstart

One complete lab session: start the stack, drive steady traffic, inject the scripted faults, and finish with a PCA report on disk. Plan on about **40 minutes** after the images are already downloaded. The first `up` on a new machine also pulls about 1.5 GB of images and builds the demo app.

You need two terminals, both in the repository root. Docker is running, and either `uv` or a project `.venv` is already installed. First-time machine setup is in the README, section 1.

Commands below are paired. Use the left column on macOS, Linux, or WSL, and the right column in Windows PowerShell.

## 1. Start the stack

```bash
./scripts/lab.sh up
```

```powershell
.\scripts\lab.ps1 up
```

`up` builds the demo app and starts it with the OpenTelemetry Collector, Prometheus, node-exporter, and Grafana. When it finishes it prints container status and scrape health.

## 2. Confirm every target is up

```bash
./scripts/lab.sh status
```

```powershell
.\scripts\lab.ps1 status
```

Wait until each Prometheus target is `up`: `prometheus`, `node`, `otel-collector`, `otel-app-metrics`, and `demo-app`. If one is still down, wait about 30 seconds and run `status` again.

These pages are useful while the session runs:

| Page | URL |
|---|---|
| Grafana (admin / admin) | http://localhost:3000 |
| Dashboard | SRE PCA Lab → SRE PCA Lab - Demo App |
| Prometheus targets | http://localhost:9090/targets |
| Demo app API | http://localhost:8000/docs |

## 3. Start load and leave it running

In **terminal 1**:

```bash
./scripts/lab.sh load 40m 20
```

```powershell
.\scripts\lab.ps1 load 40m 20
```

This is 40 minutes at about 20 requests per second, with a slow 5-minute wave so the baseline is steady traffic. The command stays in the foreground until k6 exits. Leave it alone. It records the load start, planned end, and rate in `reports/runs/<run_id>.json`.

Forty minutes is longer than the 28-minute scenario on purpose. Start the scenario in the next step within a minute or two, so k6 is still sending traffic through the last recovery gap.

## 4. Run the fault scenario

In **terminal 2**, once k6 is sending requests:

```bash
./scripts/lab.sh scenario
```

```powershell
.\scripts\lab.ps1 scenario
```

The default timeline is about **28 minutes**:

| Phase | Length | What changes |
|---|---|---|
| Baseline | 10 min | Faults cleared. This is the normal window PCA trains on. |
| Latency | 3 min | +300 ms on each request |
| Recovery | 3 min | Faults off |
| CPU | 3 min | Background CPU burner on |
| Recovery | 3 min | Faults off |
| Errors | 3 min | About 20% of requests return HTTP 500 |
| Recovery | 3 min | Faults off, then `scenario done` |

Each toggle is published as `demo_fault_active` and appended to the run manifest. The scenario writes its start, the time of the first fault, and its finish time into the load's manifest (or into a new file that copies the load block). Press Ctrl+C if you need to stop early. The scenario turns every fault off, records `scenario.end`, and marks the run `interrupted`.

## 5. Analyze the recorded run

Still in **terminal 2**, when you see `scenario done`, run the command it prints. That command names the run id. The same window is also:

```bash
./scripts/lab.sh analyze --source prometheus --run latest
```

```powershell
.\scripts\lab.ps1 analyze --source prometheus --run latest
```

`--run latest` reads `reports/runs/<run_id>.json` and queries Prometheus for that interval: from two minutes before the load started until two minutes after the scenario finished. You can run it after you come back. Prometheus keeps the series for 15 days. `--minutes 30` does not use the manifest. It is the 30 minutes before the moment you launch `analyze`.

Training uses the loaded stretch up to two minutes before the first fault. That stretch has to leave at least 20 samples, which is about seven minutes of loaded time before the first fault at a 15-second step. The default 10-minute baseline does. A shorter one falls back to the first 40% of the pulled window, and `summary.json` records that as `baseline_rule` `first_fraction`. Samples after the scenario finishes are reported as `after_run` and stay out of the baseline and the held-out normal row.

`--source prometheus` fails if Prometheus is down or almost empty. The default `auto` source would silently switch to generated data and ignore the manifest baseline.

The command keeps enough components to explain 90% of baseline variance and sets the anomaly threshold at the 0.99 quantile of baseline reconstruction error.

## 6. Read the finished report

The terminal prints the source, row count, components kept, threshold, loadings, a detection table, and one inverse-transform example. A finished live run says `source=prometheus`.

The same run writes:

| File | What it shows |
|---|---|
| `reports/summary.json` | Source, components, threshold, detection rates, query window, baseline bounds, and fault intervals |
| `reports/scores.csv` | Reconstruction error, anomaly flag, and fault flags per sample |
| `reports/pca_scree_scatter.png` | Variance by component, and the samples in the PC1/PC2 plane |
| `reports/recon_error.png` | Reconstruction error over time, with the threshold and fault shading |
| `reports/raw_metrics.png` | The descriptor series, with the same fault shading |
| `reports/runs/<run_id>.json` | Load and scenario start/end, the first fault time, and the event list |

In the detection table, the baseline row should be flagged only rarely (about 1% at the default quantile). Each `fault_latency`, `fault_cpu`, and `fault_errors` row should be flagged for most of its samples.

The held-out normal row can stay elevated after the faults. Memory levels such as `app_rss_mb` often settle at a new value, and on Docker Desktop `node_mem_used_frac` moves with the Linux VM. Re-run the same window with those two descriptors left out:

```bash
./scripts/lab.sh analyze --source prometheus --run latest --drop app_rss_mb,node_mem_used_frac
```

```powershell
.\scripts\lab.ps1 analyze --source prometheus --run latest --drop app_rss_mb,node_mem_used_frac
```

To browse the numbers in the lesson page, open `docs/first-on-call/en-US/index.html` in a browser and select `reports/scores.csv` or `reports/summary.json`. The page reads the files locally.

## 7. Stop

k6 in terminal 1 exits on its own at 40 minutes. To stop it sooner:

```bash
./scripts/lab.sh load-stop
```

```powershell
.\scripts\lab.ps1 load-stop
```

Stop the stack when you are done. This keeps Prometheus and Grafana data for a later session:

```bash
./scripts/lab.sh down
```

```powershell
.\scripts\lab.ps1 down
```

## Shorter session (about 25 minutes)

Use the same `up` and `status` steps. Then:

```bash
./scripts/lab.sh load 25m 20
./scripts/lab.sh scenario --baseline-min 5 --fault-min 2 --gap-min 2
./scripts/lab.sh analyze --source prometheus --run latest
```

```powershell
.\scripts\lab.ps1 load 25m 20
.\scripts\lab.ps1 scenario --baseline-min 5 --fault-min 2 --gap-min 2
.\scripts\lab.ps1 analyze --source prometheus --run latest
```

Load stays in terminal 1. Start the scenario in terminal 2 within a minute. Analyze in terminal 2 with the command the scenario prints, or with `--run latest` while that manifest is still the newest one. The shorter baseline is five minutes, and each fault and recovery gap is two minutes (about 17 minutes total). Five minutes of baseline leaves fewer than 20 samples after the two-minute trim, so this session's `baseline_rule` is `first_fraction`.

## Automated five-minute check

With the stack already up:

```bash
./scripts/lab.sh test-short
```

```powershell
.\scripts\lab.ps1 test-short
```

This pytest session (`tests/test_short_run.py`) starts k6, runs a three-minute baseline and three 24-second faults, and analyzes that manifest. It writes `reports/short-run/record.json` plus the summary, scores, and plots. Ordinary `test` skips it. The three-minute baseline also uses `baseline_rule` `first_fraction`.

## If the session stalls

| What you see | What to do |
|---|---|
| `Docker is not running` | Start Docker Desktop and wait until the engine is running, then run `up` again. |
| A target stays `down` | `./scripts/lab.sh logs <service>` (PowerShell: `.\scripts\lab.ps1 logs <service>`). |
| Analysis says Prometheus returned too little data | Load was not running long enough. Repeat from step 3. |
| The summary covers the wrong time | Use `--run latest` or the run id the scenario printed. `--minutes` is only the lookback from the moment you analyze. |
| `baseline_rule` is `first_fraction` | The clean loaded stretch was shorter than about seven minutes. `summary.json` names the rule that was used. |
| `source=synthetic` | The stack was not reachable and `--source prometheus` was left off. Re-run step 5. |
| Port 3000, 9090, or 8000 is already taken | Copy `.env.example` to `.env`, change that host port, and run `up` again. |
