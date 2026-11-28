"""Executes the starter notebook headlessly against synthetic data (no Docker needed)."""

import asyncio
import os
import sys
from contextlib import closing
from pathlib import Path

import nbformat
import pytest
from nbclient import NotebookClient

NB = Path(__file__).resolve().parents[1] / "notebooks" / "sre_pca_starter.ipynb"


@pytest.mark.filterwarnings("error:Proactor event loop does not implement add_reader:RuntimeWarning")
def test_notebook_runs_on_synthetic(monkeypatch):
    monkeypatch.setenv("SRE_PCA_SOURCE", os.getenv("SRE_PCA_SOURCE", "synthetic"))
    monkeypatch.setenv("MPLBACKEND", "Agg")
    nb = nbformat.read(NB, as_version=4)
    client = NotebookClient(nb, timeout=300, kernel_name="python3", resources={"metadata": {"path": str(NB.parent)}})
    if sys.platform == "win32":
        # ZeroMQ registers socket readers while the client waits for kernel messages.
        with closing(asyncio.SelectorEventLoop()) as loop:
            loop.run_until_complete(client.async_execute())
    else:
        client.execute()
