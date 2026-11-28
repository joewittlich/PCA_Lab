"""`sre-pca` - run the full analysis end to end without Jupyter.

  uv run sre-pca --run latest                  # window recorded by the scenario manifest
  uv run sre-pca --source synthetic
  uv run sre-pca --source prometheus --minutes 45 --deseason stl --period 20
  uv run sre-pca --start 2026-11-27T19:00:00Z --end 2026-11-27T19:45:00Z
"""

from __future__ import annotations

import argparse
import json
from datetime import timedelta
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

from . import core, plots, runs  # noqa: E402


def _window(args, manifest: dict | None) -> tuple[pd.Timestamp, pd.Timestamp, tuple | None]:
    """Return (query_start, query_end, baseline_bounds or None)."""
    explicit = bool(args.start or args.end)
    if manifest is not None and not explicit:
        start, end = runs.query_window(manifest, pad=timedelta(minutes=args.pad_minutes))
    else:
        end = runs.parse_time(args.end) if args.end else runs.utcnow()
        start = runs.parse_time(args.start) if args.start else end - timedelta(minutes=args.minutes)
    bounds = runs.baseline_bounds(manifest) if manifest is not None else None
    return pd.Timestamp(start), pd.Timestamp(end), bounds


def _bound_text(index: pd.DatetimeIndex, mask: pd.Series) -> tuple[str | None, str | None]:
    if not bool(mask.any()):
        return None, None
    chosen = index[mask.to_numpy()]
    return runs.iso(chosen[0].to_pydatetime()), runs.iso(chosen[-1].to_pydatetime())


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="sre-pca", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--source", choices=["auto", "prometheus", "synthetic"], default="auto")
    p.add_argument("--prom-url", default=None, help="default: $PROM_URL or http://localhost:9090")
    p.add_argument("--minutes", type=float, default=60,
                   help="lookback from --end (default: now) when --run and --start are omitted")
    p.add_argument("--run", default=None, help="run manifest path, run id, or 'latest'")
    p.add_argument("--runs-dir", default=str(runs.RUNS_DIR), help="directory used by --run latest and bare run ids")
    p.add_argument("--start", default=None, help="query window start, UTC ISO-8601 (overrides --run and --minutes)")
    p.add_argument("--end", default=None, help="query window end, UTC ISO-8601 (default: now)")
    p.add_argument("--pad-minutes", type=float, default=2.0, help="minutes added on each side of a --run window")
    p.add_argument("--step", default="15s")
    p.add_argument("--baseline-minutes", type=float, default=None,
                   help="fit on the first N minutes of the pulled window (overrides the manifest baseline)")
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

    manifest = runs.resolve_run(a.run, Path(a.runs_dir)) if a.run else None
    query_start, query_end, bounds = _window(a, manifest)

    raw, faults, used = core.load_metrics(
        a.source, a.minutes, a.step, a.prom_url,
        start=query_start.to_pydatetime(), end=query_end.to_pydatetime(),
    )
    if manifest is not None and used != "prometheus":
        print("[sre_pca] --run selects a Prometheus window; this analysis used synthetic data, so the manifest baseline was not applied")
        bounds = None
    drop = [c for c in a.drop.split(",") if c]
    df = core.preprocess(raw.drop(columns=drop, errors="ignore"))
    faults = faults.reindex(df.index).fillna(0).astype(int)
    if a.deseason != "none":
        df = core.remove_seasonality(df, a.period, a.deseason)
    baseline_start = baseline_end = None
    if bounds is not None and a.baseline_minutes is None:
        baseline_start, baseline_end = bounds
    base = core.choose_baseline(
        df, faults, a.baseline_minutes, baseline_start=baseline_start, baseline_end=baseline_end,
    )
    rule = base.attrs.get("baseline_rule", "first_fraction")
    model = core.fit_pca(df[base], var_target=a.var_target, n_components=a.k, threshold_quantile=a.quantile)
    scores = core.score(model, df)
    run_end = None
    scenario = (manifest or {}).get("scenario") or {}
    if used == "prometheus" and scenario.get("end"):
        run_end = runs.parse_time(scenario["end"])
    ev = core.evaluate(scores, faults, base, run_end=run_end)
    chapters = core.chapter_report(scores, (manifest or {}).get("chapters") or [])

    trained_start, trained_end = _bound_text(df.index, base)
    print(f"\nsource={used} rows={len(df)} descriptors={len(model.columns)} baseline_rows={int(base.sum())}")
    if manifest is not None:
        print(f"run_id={manifest['run_id']}")
    print(f"query: {runs.iso(query_start.to_pydatetime())} -> {runs.iso(query_end.to_pydatetime())} (UTC)")
    print(f"span: {df.index[0]} -> {df.index[-1]} (UTC)")
    print(f"baseline_rule={rule} baseline: {trained_start} -> {trained_end}")
    print("explained variance ratio:", np.round(model.explained, 3).tolist())
    print(f"kept k={model.k} PCs (cumulative {model.explained[: model.k].sum():.1%}); "
          f"threshold (q{a.quantile}) = {model.threshold:.3f}")
    print("\nloadings (first PCs):\n", model.loadings().round(2).to_string())
    print("\ndetection summary (fraction of samples flagged as anomalous):\n", ev.to_string(index=False))
    if chapters:
        print("\nchapters (flagged fraction, seconds to the first flag, contributors in the order they appear):")
        for chapter in chapters:
            names = " -> ".join(item["name"] for item in chapter["contributors"]) or "-"
            flagged = chapter["flagged_frac"]
            flagged_text = "n/a" if flagged is None else f"{flagged:.0%}"
            first = chapter["seconds_to_first_flag"]
            first_text = "n/a" if first is None else f"{first:.0f}s"
            print(f"  {chapter['name']}: samples={chapter['samples']} flagged={flagged_text} first={first_text} contributors={names}")
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
    plt.close("all")
    scores.join(faults).to_csv(out / "scores.csv")
    summary = {
        "source": used,
        "rows": len(df),
        "k": model.k,
        "threshold": model.threshold,
        "explained_variance_ratio": model.explained.tolist(),
        "detection": ev.to_dict(orient="records"),
        "run_id": manifest["run_id"] if manifest else None,
        "query_start": runs.iso(query_start.to_pydatetime()),
        "query_end": runs.iso(query_end.to_pydatetime()),
        "data_start": runs.iso(df.index[0].to_pydatetime()),
        "data_end": runs.iso(df.index[-1].to_pydatetime()),
        "baseline_start": trained_start,
        "baseline_end": trained_end,
        "baseline_rule": rule,
        "fault_intervals": core.fault_intervals(faults),
    }
    if chapters:
        summary["chapters"] = chapters
    (out / "summary.json").write_text(json.dumps(summary, indent=2, default=str) + "\n", encoding="utf-8")
    print(f"\nwrote {out}/pca_scree_scatter.png, recon_error.png, raw_metrics.png, scores.csv, summary.json")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
