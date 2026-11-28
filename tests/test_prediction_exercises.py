import json
import shutil
import subprocess
import sys
from pathlib import Path

import numpy as np
import pandas as pd

from sre_pca import benchmark, core, prediction_exercises


def test_published_prediction_examples():
    geometry, training, frozen = prediction_exercises.run_exercises()
    baseline, _, _ = benchmark.make_relationship_windows()
    model = core.fit_pca(baseline, n_components=1, threshold_quantile=1.0)
    np.testing.assert_allclose(np.linalg.norm(model.standardize(geometry), axis=1), [2.6, 2.6])
    np.testing.assert_allclose(geometry["recon_error"], [0, 6.76], atol=1e-10)
    assert geometry["anomaly"].tolist() == [False, True]
    assert geometry.loc["along", "req_rate"] > baseline.req_rate.max()
    assert training.set_index(["baseline", "window"])["flagged"].to_dict() == {
        ("original", "healthy"): 1, ("original", "replay"): 20,
        ("altered", "healthy"): 0, ("altered", "replay"): 0,
    }
    assert training["samples"].tolist() == [180, 20, 180, 20]
    assert len(frozen) == 20 and not frozen.anomaly.any()
    assert (frozen.index.to_series().diff().dropna() == pd.Timedelta(seconds=15)).all()
    assert len(frozen[["req_rate", "app_cpu"]].drop_duplicates()) == 1


def test_exercises_can_be_translated_independently(tmp_path):
    source = Path(__file__).resolve().parents[1] / "docs" / "first-on-call"
    shutil.copytree(source / "en-US", tmp_path / "en-US")
    shutil.copy2(source / "localize.py", tmp_path)
    target = tmp_path / "ar"
    target.mkdir()
    for name in ("direction", "training", "readings"):
        catalog = f"{name}.strings.json"
        data = json.loads((source / "en-US" / catalog).read_text(encoding="utf-8"))
        data["locale"] = "ar"
        data["strings"]["cases.observe"] = "اقرأ المثال"
        (target / catalog).write_text(json.dumps(data), encoding="utf-8")
        subprocess.run([sys.executable, str(tmp_path / "localize.py"), "ar", "--dir", "rtl", "--page", name], check=True)
        html = (target / f"{name}.html").read_text(encoding="utf-8")
        assert '<html lang="ar" dir="rtl">' in html and "اقرأ المثال" in html
    assert not (target / "index.html").exists()
