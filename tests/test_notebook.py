"""Executes the starter notebook headlessly against synthetic data (no Docker needed)."""

import os
from pathlib import Path

import nbformat
from nbclient import NotebookClient

NB = Path(__file__).resolve().parents[1] / "notebooks" / "sre_pca_starter.ipynb"


def test_notebook_runs_on_synthetic(monkeypatch):
    monkeypatch.setenv("SRE_PCA_SOURCE", os.getenv("SRE_PCA_SOURCE", "synthetic"))
    monkeypatch.setenv("MPLBACKEND", "Agg")
    nb = nbformat.read(NB, as_version=4)
    NotebookClient(nb, timeout=300, kernel_name="python3", resources={"metadata": {"path": str(NB.parent)}}).execute()
