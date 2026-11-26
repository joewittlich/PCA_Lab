"""Matplotlib helpers shared by the notebook and CLI."""

from __future__ import annotations

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

from .core import PCAModel

FAULT_COLORS = {"fault_latency": "tab:orange", "fault_cpu": "tab:red", "fault_errors": "tab:purple"}


def shade_faults(ax, faults: pd.DataFrame | None) -> None:
    if faults is None:
        return
    for col in faults.columns:
        on = faults[col].astype(bool).to_numpy()
        if not on.any():
            continue
        idx = faults.index
        edges = np.flatnonzero(np.diff(np.r_[0, on.astype(int), 0]))
        for i, (a, b) in enumerate(zip(edges[::2], edges[1::2])):
            ax.axvspan(idx[a], idx[min(b, len(idx) - 1)], color=FAULT_COLORS.get(col, "grey"), alpha=0.18,
                       label=col.replace("fault_", "fault: ") if i == 0 else None)


def scree(model: PCAModel, ax=None):
    ax = ax or plt.subplots(figsize=(7, 4))[1]
    ev = model.explained
    n = np.arange(1, len(ev) + 1)
    ax.bar(n, ev, color=["tab:blue" if i < model.k else "lightgrey" for i in range(len(ev))], label="per PC")
    ax.plot(n, np.cumsum(ev), "o-", color="black", label="cumulative")
    ax.axvline(model.k + 0.5, ls="--", color="grey")
    ax.set(xlabel="principal component", ylabel="explained variance ratio", title=f"Scree plot (kept k={model.k})",
           xticks=n, ylim=(0, 1.05))
    ax.legend()
    return ax


def pc_scatter(model: PCAModel, df: pd.DataFrame, baseline_mask: pd.Series, faults: pd.DataFrame | None, ax=None,
               extra_point=None):
    ax = ax or plt.subplots(figsize=(7, 6))[1]
    if model.k < 2:
        ax.text(0.5, 0.5, "k < 2: only one PC kept", ha="center", transform=ax.transAxes)
        return ax
    pcs = model.transform(df)
    f = faults.reindex(df.index).fillna(0) if faults is not None else None
    normal = ~baseline_mask.reindex(df.index).fillna(False)
    if f is not None:
        normal &= f.max(axis=1) == 0
    ax.scatter(pcs.loc[baseline_mask, "PC1"], pcs.loc[baseline_mask, "PC2"], s=8, c="tab:blue", alpha=0.5, label="baseline")
    ax.scatter(pcs.loc[normal, "PC1"], pcs.loc[normal, "PC2"], s=8, c="tab:green", alpha=0.4, label="other normal")
    if f is not None:
        for c in f.columns:
            sel = f[c] > 0
            if sel.any():
                ax.scatter(pcs.loc[sel, "PC1"], pcs.loc[sel, "PC2"], s=14, c=FAULT_COLORS.get(c, "grey"),
                           label=c.replace("fault_", "fault: "))
    if extra_point is not None:
        ax.scatter([extra_point[0]], [extra_point[1]], marker="*", s=300, c="gold", edgecolor="black",
                   label="chosen point (inverse)", zorder=5)
    ax.set(xlabel=f"PC1 ({model.explained[0]:.0%})", ylabel=f"PC2 ({model.explained[1]:.0%})", title="PC1 vs PC2")
    ax.legend(fontsize=8)
    return ax


def recon_timeline(scores: pd.DataFrame, threshold: float, faults: pd.DataFrame | None, ax=None):
    ax = ax or plt.subplots(figsize=(12, 4))[1]
    ax.plot(scores.index, scores["recon_error"], lw=1, label="reconstruction error")
    ax.axhline(threshold, color="red", ls="--", label=f"threshold ({threshold:.2f})")
    shade_faults(ax, faults.reindex(scores.index).fillna(0) if faults is not None else None)
    ax.set_yscale("symlog", linthresh=max(threshold, 1e-3))
    ax.set_ylim(bottom=0)
    ax.set(title="Reconstruction error over time (shaded = injected faults)", ylabel="SPE (symlog)")
    ax.legend(fontsize=8, loc="upper left")
    return ax


def raw_metrics(df: pd.DataFrame, faults: pd.DataFrame | None, cols: list[str] | None = None):
    cols = cols or list(df.columns)
    fig, axes = plt.subplots(len(cols), 1, figsize=(12, 1.6 * len(cols)), sharex=True)
    for ax, c in zip(np.atleast_1d(axes), cols):
        ax.plot(df.index, df[c], lw=0.8)
        shade_faults(ax, faults.reindex(df.index).fillna(0) if faults is not None else None)
        ax.set_ylabel(c, rotation=0, ha="right", fontsize=8)
    fig.tight_layout()
    return fig
