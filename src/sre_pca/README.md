# How the lab scores service metrics

Use this guide when reviewing a change to the analysis, the benchmark, or the live exporter. Run commands from the repository root with the project's Python dependencies installed.

| Question | Where to look | What to inspect |
|---|---|---|
| Which measurements enter the model? | [prom.py](prom.py) and [synthetic.py](synthetic.py) | Each Prometheus query returns one time series. Check the source recorded in the report before interpreting a result. |
| What does a flag mean? | [core.py](core.py) and [cli.py](cli.py) | The model learns a baseline, then flags rows whose reconstruction error exceeds the fitted threshold. The largest contributor identifies a measurement to investigate. |
| How old is the displayed score? | [exporter.py](exporter.py) | The exporter chooses the newest row with finite values for every feature used in training. A missing trained feature can leave the previous score on display. |
| Can two ordinary readings form an unusual pair? | [benchmark.py](benchmark.py) | The experiment pairs recorded synthetic CPU values from higher traffic with lower request rates. Compare both detectors on the same held-out rows. |

## Review the live score

With Prometheus collecting data during a healthy period, run `uv run sre-pca-exporter` on the host. The default training window is 30 minutes. The exporter then queries the last three minutes on each scoring pass. The [scrape configuration](../../config/prometheus/prometheus.yml) includes the optional job for this endpoint.

The endpoint exposes `sre_pca_reconstruction_error`, `sre_pca_threshold`, `sre_pca_anomaly`, and `sre_pca_pc_score{pc=...}`.

Look at `sre_pca_last_scored_timestamp_seconds` first. Zero means that no complete row has been scored yet. After the first score, `time() - sre_pca_last_scored_timestamp_seconds` gives its age in seconds. The timestamp refers to the Prometheus query row. The underlying measurements can cover a longer interval. If the age keeps increasing while the endpoint is reachable, check for missing or nonfinite measurements before using the displayed score. The [exporter test](../../tests/test_exporter.py) exercises this case.

## Reproduce the detector comparison

Run `uv run python -m sre_pca.benchmark`. It prints counts for a fixed synthetic workload. The first 240 rows train both rules. The next 180 healthy rows measure false alarms. The final 20 rows form one CPU replay. Both rules keep their training thresholds throughout. For this experiment PCA keeps one component and uses the largest training error as its threshold. The usual analysis defaults to a 0.99 quantile.

Compare the two evaluation windows separately. Each flagged row represents one sample. Several adjacent flags can describe the same event. To assess its value for paging, you would also need evidence about separate incidents, user impact, and false alerts over time. The [benchmark tests](../../tests/test_benchmark.py) check the replay and the fixed thresholds.

Return to the [lab instructions](../../README.md) for the live experiment, notebook, and example results.
