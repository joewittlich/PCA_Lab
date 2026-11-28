# Second session: a three-hour run

Run this after the session in [quickstart.md](quickstart.md). That session shows one fault at a time. This one starts the same way, then keeps the load running through combined failures: retries that turn errors into latency, a downstream call that passes its time budget, and a memory leak that stays after the allocator stops.

The scenario is three hours. The load command below is three and a half hours, so traffic is still flowing when the scenario finishes. You can leave. Prometheus keeps the series for 15 days, and `analyze --run latest` reopens the recorded window.

This is one service. The chapters reproduce the shape of those incidents in the same 11 descriptors. They are not a second application and not a second notebook.

Rebuild the demo app before the first long session, so the new fault endpoints are in the image. `up` does that. k6 reads `load/load.js` from the repository, so that file does not need an image rebuild.

## 1. Start the stack

Use the same `up` and `status` steps as the first session. Every Prometheus target should be `up`.

## 2. Start load and leave it running

In terminal 1:

```bash
./scripts/lab.sh load-bg 3h30m 20
```

```powershell
.\scripts\lab.ps1 load-bg 3h30m 20
```

`load-bg` records the load and returns. k6 keeps running until the duration ends, or until you run `load-stop`. The same 5-minute traffic wave is still there. Three hours contains enough of those waves for a seasonal pass to matter.

## 3. Run the long scenario

In terminal 2, within a few minutes of starting the load:

```bash
./scripts/lab.sh scenario --profile long
```

```powershell
.\scripts\lab.ps1 scenario --profile long
```

`--baseline-min`, `--fault-min`, and `--gap-min` belong to the default profile. The long profile uses the timeline below. Ctrl+C clears the faults, releases the held memory, and records `scenario.end` with `"status": "interrupted"`.

The manifest at `reports/runs/<run_id>.json` stores the plan at the start and fills each chapter's start and end as it happens. The first `fault ... ON` is still the latency chapter, so the training interval is the 30 minutes of loaded baseline.

| Clock | Length | Chapter | What changes |
|---|---|---|---|
| 0:00 | 30 min | baseline | Faults off. This is the training window. |
| 0:30 | 5 min | latency | +300 ms on each request. Same fault as the first session. |
| 0:35 | 10 min | recovery | Faults off. |
| 0:45 | 5 min | cpu | Background CPU burner. |
| 0:50 | 10 min | recovery | Faults off. |
| 1:00 | 5 min | errors | About 20% of requests return HTTP 500. No retries yet. |
| 1:05 | 10 min | recovery | Faults off. |
| 1:15 | 30 min | retry-ramp | The app retries a failed attempt twice. k6 retries a failed request once. The error rate rises from 5% to 85%. |
| 1:45 | 30 min | downstream-timeout | A downstream call would take 2 s. The app returns HTTP 504 at 1 s. k6 waits 1.5 s, so it usually records that 504. |
| 2:15 | 15 min | leak | The app holds 64 MB more. |
| 2:30 | 10 min | leak-held | Allocation stops. The memory stays. The leak gauge is off. |
| 2:40 | 20 min | healthy-after-leak | No labeled fault. Memory is still high. |
| 3:00 | | done | The scenario end is recorded, then the held memory is released. |

The opening three faults are the same knobs as the first session, held a little longer so each one is readable on a three-hour plot. The recovery gaps are 10 minutes so `rate()[1m]` from one chapter has faded before the next chapter is scored.

## 4. What each new chapter is for

**Retries.** A failed attempt is tried again inside the same request, with a short pause between tries. Early in the ramp most failures are hidden by a later success, and the request simply takes longer. Later in the ramp the retries run out, so the error ratio and the latency are high together. k6's extra attempt multiplies that load for this chapter only. The request rate can rise here because each client retry is its own HTTP request.

**Downstream timeout.** The server sleeps until the 1 s budget and then returns 504. It does not sleep the remaining second. In the lab's descriptors, request rate counts every completed response, including 504, so the rate stays near the offered load while `error_ratio` and latency carry the timeout. A caller that gave up would see those 504s as timeouts. k6 waits 500 ms past the server budget so the response is what gets recorded.

**Leak, then a healthy tail.** Stopping the leak turns `demo_fault_active{type="leak"}` off and leaves the process resident set where it is. The last 20 minutes are unlabeled on purpose. A flag there is a level shift, not a fault the manifest called out. Re-run with `--drop app_rss_mb` when you want to see the other descriptors without that shift. The memory is released after `scenario done`, so the samples inside the last chapter still contain it.

Docker Desktop's `node_mem_used_frac` and `node_cpu_busy` wander over three hours. That movement is outside the demo app. The same `--drop` list used in the first session (`app_rss_mb,node_mem_used_frac`) is the comparison when those series dominate the score.

## 5. Analyze twice

When the scenario prints `scenario done`, run the two commands it prints. The same window is:

```bash
./scripts/lab.sh analyze --source prometheus --run latest --reports-dir reports/long-run
./scripts/lab.sh analyze --source prometheus --run latest --deseason stl --period 20 --reports-dir reports/long-run-deseason
```

```powershell
.\scripts\lab.ps1 analyze --source prometheus --run latest --reports-dir reports/long-run
.\scripts\lab.ps1 analyze --source prometheus --run latest --deseason stl --period 20 --reports-dir reports/long-run-deseason
```

The first pass trains on the manifest baseline: loaded traffic up to two minutes before the latency chapter. Thirty minutes leaves enough samples for `baseline_rule` `manifest`.

The second pass removes the 5-minute traffic wave before fitting. The period is 20 samples because the wave is 300 s and the default step is 15 s. Compare the chapter table, not only the single detection rate. A three-hour detection number mixes the quiet gaps with the incidents.

`summary.json` includes a `chapters` list when the manifest has chapters. Each entry has the flagged fraction, the seconds from the chapter start to the first flagged sample, and the top contributors in the order they first appear among flagged rows. For the timeout chapter, that order is the handoff to look for: latency, then in-flight requests, then errors. A chapter with no flagged sample has `seconds_to_first_flag` null.

The held-out normal row still mixes every unlabeled, non-baseline sample, including the post-leak tail. Use the chapter rows named `recovery-*`, `leak-held`, and `healthy-after-leak` when you want those stretches separate. Samples after `scenario.end` stay in `after_run`.

Plots and `scores.csv` are written in the reports directory you named. Both directories are gitignored with the rest of `reports/`.

The live exporter is a third comparison, not part of the script. During the last hour its default training window is the most recent 30 minutes, so a slow ramp can fall inside what it treats as normal. The one-shot analysis above keeps the original baseline and still flags that ramp. See [src/sre_pca/README.md](../src/sre_pca/README.md) for the exporter's own checks.

## 6. Stop

```bash
./scripts/lab.sh load-stop
```

```powershell
.\scripts\lab.ps1 load-stop
```

Stop the stack with `down` when you are finished. That keeps the Prometheus history, so you can analyze this run later with `--run <run_id>`.
