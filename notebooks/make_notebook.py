"""Regenerates notebooks/sre_pca_starter.ipynb (kept as code so diffs stay readable)."""

from pathlib import Path

import nbformat as nbf

md, code = nbf.v4.new_markdown_cell, nbf.v4.new_code_cell
cells = [
    md("""# SRE PCA starter notebook

Goal: learn what *normal* looks like for a service from correlated metrics, then flag samples whose
**reconstruction error** says "this isn't just more load, it's a new kind of behaviour".

Pipeline: **Prometheus HTTP API → pandas → align → standardize → (optional) remove seasonality → PCA on a
baseline window → scree / PC1-PC2 / reconstruction error → inverse transform**.

If Prometheus isn't reachable (stack not running), it falls back to **synthetic data** so every cell still runs.
The reusable logic lives in `src/sre_pca/` - this notebook shows the math step by step."""),
    code("""import numpy as np
import pandas as pd
import matplotlib.pyplot as plt

from sre_pca import core, plots, prom

pd.set_option("display.width", 140)
%matplotlib inline"""),
    md("""## 1. Settings
`SOURCE`: `"auto"` (Prometheus if reachable, else synthetic), `"prometheus"`, or `"synthetic"`.
`MINUTES`: lookback from the moment this cell runs. `sre-pca --run <id>` uses the window in `reports/runs/<id>.json` instead. This notebook does not read that file. After a scenario, set MINUTES so the pull still covers the run, or analyze with the CLI."""),
    code("""import os
SOURCE = os.getenv("SRE_PCA_SOURCE", "auto")
PROM_URL = prom.PROM_URL        # http://localhost:9090 unless $PROM_URL is set
MINUTES = 45
STEP = "15s"
BASELINE_MINUTES = None         # None = everything before the first injected fault
VAR_TARGET = 0.90               # keep PCs until 90% of baseline variance is explained
DESEASON = None                 # None | "stl" | "profile"
DROP = []                       # descriptors to leave out, e.g. ["app_rss_mb", "node_mem_used_frac"] (slow-drifting levels)
PERIOD = 20                     # samples per cycle (k6 wave 300 s / 15 s step = 20; a real day at 15 s = 5760)"""),
    md("""## 2. Pull metrics from Prometheus
Each descriptor is one PromQL expression (see `prom.DEFAULT_QUERIES`) evaluated with `query_range`,
so all series come back on the **same timestamps** - that's the alignment step.
Fault flags come from the demo app's `demo_fault_active{type=...}` gauge, so we know when faults were injected."""),
    code("""for name, q in prom.DEFAULT_QUERIES.items():
    print(f"{name:20s} {q}")

raw, faults, used = core.load_metrics(SOURCE, MINUTES, STEP, PROM_URL)
print(f"\\nsource used: {used}; raw shape {raw.shape}")
raw.tail()"""),
    md("## 3. Align / clean, optional seasonality removal"),
    code("""df = core.preprocess(raw.drop(columns=DROP, errors="ignore"))  # drop sparse cols, fill short gaps, drop NaN rows
faults = faults.reindex(df.index).fillna(0).astype(int)
if DESEASON:
    df = core.remove_seasonality(df, PERIOD, DESEASON)
print(df.shape)
plots.raw_metrics(df, faults);"""),
    md("""## 4. Pick the baseline ("known normal") window and standardize
z = (x - mu) / sigma, using **baseline** mean/std only. sigma is floored so near-constant metrics
(error ratio ~ 0) don't turn tiny noise into huge z-scores."""),
    code("""base = core.choose_baseline(df, faults, BASELINE_MINUTES)
print(f"baseline rows: {base.sum()} of {len(df)}  ({df.index[base][0]} -> {df.index[base][-1]} UTC)")

model = core.fit_pca(df[base], var_target=VAR_TARGET)
pd.DataFrame({"mu": model.mu, "sigma": model.sigma}).round(4)"""),
    md("""## 5. Scree plot + loadings
Bars = share of baseline variance per PC. PC1 is typically "load goes up, everything goes up".
Loadings say what each PC *means* (weights on the original descriptors)."""),
    code("""plots.scree(model)
plt.show()
print(f"kept k={model.k} PCs, cumulative explained = {model.explained[:model.k].sum():.1%}")
model.loadings().round(2)"""),
    md("## 6. PC1 vs PC2 scatter (baseline vs other normal vs injected faults)"),
    code("""plots.pc_scatter(model, df, base, faults)
plt.show()"""),
    md("""## 7. Reconstruction error over time
Project each sample onto the kept PCs and back: x_hat = (z W) W^T. The leftover
||z - z_hat||^2 (SPE / Q statistic) is what normal structure can't explain.
Threshold = 99th percentile of baseline error. Shaded bands = injected faults."""),
    code("""scores = core.score(model, df)
plots.recon_timeline(scores, model.threshold, faults)
plt.show()
core.evaluate(scores, faults, base)"""),
    code("""# Which descriptor drove each flagged sample?
scores.loc[scores.anomaly, "top_contributor"].value_counts()"""),
    md("""## 8. Going backwards: inverse transform
Pick a point in PC space (e.g. outside the normal cloud) and back-calculate descriptors in real units:

$$x = \\mu + \\sigma \\odot (z\\,W^\\top)$$

PCs beyond the ones you set are held at 0 (= baseline average). Linear model, so far-out points are
extrapolation: expect physically impossible values (negative latency, error ratio > 1)."""),
    code("""z_point = np.array([3.0, -2.0])[: model.k]     # change me

W = model.W                                     # (n_descriptors, k)
x_manual = model.mu.to_numpy() + model.sigma.to_numpy() * (np.pad(z_point, (0, model.k - len(z_point))) @ W.T)
x_lib = core.inverse_from_pcs(model, z_point)
assert np.allclose(x_manual, x_lib)

pd.DataFrame({"baseline_mean": model.mu, "back_calculated": x_lib,
              "change_in_sigmas": (x_lib - model.mu) / model.sigma}).round(4)"""),
    code("""# Sanity check: project the back-calculated row forward again -> should land on z_point
model.transform(x_lib.to_frame().T).round(6)"""),
    md("""## 9. Next steps
- Run the scripted scenario longer, or change fault sizes (`uv run sre-fault latency 120`) to see detection limits.
- Try `DESEASON = "stl"` with a longer run.
- Compare with `sklearn.ensemble.IsolationForest` on the same standardized matrix.
- Export the live score to Prometheus: `uv run sre-pca-exporter` (see README *Next steps*)."""),
]
nb = nbf.v4.new_notebook(cells=cells, metadata={
    "kernelspec": {"display_name": "Python 3", "language": "python", "name": "python3"},
    "language_info": {"name": "python"},
})
out = Path(__file__).with_name("sre_pca_starter.ipynb")
nbf.write(nb, out)
print(f"wrote {out}")
