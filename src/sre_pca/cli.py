"""`sre-pca` - run the full analysis end to end without Jupyter.

  uv run sre-pca                         # auto: Prometheus if reachable, else synthetic
  uv run sre-pca --source synthetic
  uv run sre-pca --source prometheus --minutes 45 --deseason stl --period 20
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

from . import core, plots  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="sre-pca", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--source", choices=["auto", "prometheus", "synthetic"], default="auto")
    p.add_argument("--prom-url", default=None, help="default: $PROM_URL or http://localhost:9090")
    p.add_argument("--minutes", type=float, default=60, help="how far back to pull from Prometheus")
    p.add_argument("--step", default="15s")
    p.add_argument("--baseline-minutes", type=float, default=None,
                   help="fit on the first N minutes (default: everything before the first injected fault)")
    p.add_argument("--var-target", type=float, default=0.90, help="keep PCs until this cumulative variance")
    p.add_argument("--k", type=int, default=None, help="force number of PCs kept")
    p.add_argument("--quantile", type=float, default=0.99, help="baseline error quantile used as threshold")
    p.add_argument("--deseason", choices=["none", "stl", "profile"], default="none")
    p.add_argument("--period", type=int, default=20, help="season length in samples (k6 wave 300s / 15s = 20)")
    p.add_argument("--pc-point", default="3,0", help="PC point to back-calculate, e.g. '3,-2'")
    p.add_argument("--drop", default="", help="comma-separated descriptors to leave out, e.g. 'app_rss_mb,node_mem_used_frac'")
    p.add_argument("--reports-dir", default="reports")
    a = p.parse_args(argv)

    out = Path(a.reports_dir)
    out.mkdir(parents=True, exist_ok=True)

    raw, faults, used = core.load_metrics(a.source, a.minutes, a.step, a.prom_url)
    drop = [c for c in a.drop.split(",") if c]
    df = core.preprocess(raw.drop(columns=drop, errors="ignore"))
    faults = faults.reindex(df.index).fillna(0).astype(int)
    if a.deseason != "none":
        df = core.remove_seasonality(df, a.period, a.deseason)
    base = core.choose_baseline(df, faults, a.baseline_minutes)
    model = core.fit_pca(df[base], var_target=a.var_target, n_components=a.k, threshold_quantile=a.quantile)
    scores = core.score(model, df)
    ev = core.evaluate(scores, faults, base)

    print(f"\nsource={used} rows={len(df)} descriptors={len(model.columns)} baseline_rows={int(base.sum())}")
    print(f"span: {df.index[0]} -> {df.index[-1]} (UTC)")
    print("explained variance ratio:", np.round(model.explained, 3).tolist())
    print(f"kept k={model.k} PCs (cumulative {model.explained[: model.k].sum():.1%}); "
          f"threshold (q{a.quantile}) = {model.threshold:.3f}")
    print("\nloadings (first PCs):\n", model.loadings().round(2).to_string())
    print("\ndetection summary (fraction of samples flagged as anomalous):\n", ev.to_string(index=False))
    top = scores[scores["anomaly"]]["top_contributor"].value_counts().head(5)
    if len(top):
        print("\ntop contributors among flagged samples:\n", top.to_string())

    z = [float(v) for v in a.pc_point.split(",")][: model.k]
    back = core.inverse_from_pcs(model, z)
    print(f"\ninverse transform: PC point {z} -> descriptors (original units), vs baseline mean:")
    print(pd.DataFrame({"baseline_mean": model.mu, "back_calculated": back}).round(4).to_string())

    fig, axes = plt.subplots(1, 2, figsize=(14, 5))
    plots.scree(model, axes[0])
    plots.pc_scatter(model, df, base, faults, axes[1], extra_point=z + [0] * (2 - len(z)))
    fig.tight_layout()
    fig.savefig(out / "pca_scree_scatter.png", dpi=110)
    fig, ax = plt.subplots(figsize=(13, 4))
    plots.recon_timeline(scores, model.threshold, faults, ax)
    fig.tight_layout()
    fig.savefig(out / "recon_error.png", dpi=110)
    plots.raw_metrics(df, faults).savefig(out / "raw_metrics.png", dpi=90)
    scores.join(faults).to_csv(out / "scores.csv")
    (out / "summary.json").write_text(json.dumps({
        "source": used, "rows": len(df), "k": model.k, "threshold": model.threshold,
        "explained_variance_ratio": model.explained.tolist(),
        "detection": ev.to_dict(orient="records"),
    }, indent=2, default=str))
    print(f"\nwrote {out}/pca_scree_scatter.png, recon_error.png, raw_metrics.png, scores.csv, summary.json")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
