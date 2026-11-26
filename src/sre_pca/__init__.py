"""SRE PCA lab: PCA / reconstruction-error anomaly detection on Prometheus metrics."""

from .core import (
    PCAModel,
    choose_baseline,
    fit_pca,
    inverse_from_pcs,
    load_metrics,
    preprocess,
    remove_seasonality,
    score,
)

__all__ = [
    "PCAModel",
    "choose_baseline",
    "fit_pca",
    "inverse_from_pcs",
    "load_metrics",
    "preprocess",
    "remove_seasonality",
    "score",
]
__version__ = "0.1.0"
