"""Evaluation figures logged to MLflow and embedded in reports."""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Any

import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402
from sklearn.metrics import (  # noqa: E402
    ConfusionMatrixDisplay,
    PrecisionRecallDisplay,
    RocCurveDisplay,
    confusion_matrix,
)


def feature_importances(pipeline: Any) -> pd.DataFrame:
    """Importance of every model-matrix column: tree ``feature_importances_`` or ``|coef|`` for linear models.

    Returns:
        DataFrame with ``feature`` and ``importance`` sorted descending (empty if unsupported).
    """
    classifier = pipeline.named_steps["classifier"]
    names = list(pipeline.named_steps["preprocessor"].get_feature_names_out())
    if hasattr(classifier, "feature_importances_"):
        values = np.asarray(classifier.feature_importances_, dtype=float)
    elif hasattr(classifier, "coef_"):
        values = np.abs(np.asarray(classifier.coef_, dtype=float)).ravel()
    else:
        return pd.DataFrame(columns=["feature", "importance"])
    total = values.sum()
    normalised = values / total if total > 0 else values
    frame = pd.DataFrame({"feature": names, "importance": normalised})
    return frame.sort_values("importance", ascending=False, ignore_index=True)


def _save(fig: plt.Figure, path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    fig.tight_layout()
    fig.savefig(path, dpi=120)
    plt.close(fig)
    return path


def plot_confusion_matrix(y_true: np.ndarray, y_pred: np.ndarray, path: Path, title: str) -> Path:
    """Confusion matrix with counts (labels: 0 = no default, 1 = default)."""
    matrix = confusion_matrix(y_true, y_pred, labels=[0, 1])
    fig, ax = plt.subplots(figsize=(4.5, 4))
    ConfusionMatrixDisplay(matrix, display_labels=["no default", "default"]).plot(ax=ax, colorbar=False, cmap="Blues")
    ax.set_title(title)
    return _save(fig, path)


def plot_roc_curves(curves: Mapping[str, tuple[np.ndarray, np.ndarray]], path: Path, title: str) -> Path:
    """ROC curves for one or more ``label -> (y_true, y_proba)`` pairs."""
    fig, ax = plt.subplots(figsize=(5, 4.5))
    for label, (y_true, y_prob) in curves.items():
        RocCurveDisplay.from_predictions(y_true, y_prob, name=label, ax=ax)
    ax.plot([0, 1], [0, 1], linestyle="--", color="grey", linewidth=1)
    ax.set_title(title)
    return _save(fig, path)


def plot_pr_curves(curves: Mapping[str, tuple[np.ndarray, np.ndarray]], path: Path, title: str) -> Path:
    """Precision-recall curves for one or more ``label -> (y_true, y_proba)`` pairs."""
    fig, ax = plt.subplots(figsize=(5, 4.5))
    for label, (y_true, y_prob) in curves.items():
        PrecisionRecallDisplay.from_predictions(y_true, y_prob, name=label, ax=ax)
    ax.set_title(title)
    return _save(fig, path)


def plot_feature_importance(importances: pd.DataFrame, path: Path, title: str, top_n: int = 20) -> Path:
    """Horizontal bar chart of the ``top_n`` most important features."""
    top = importances.head(top_n).iloc[::-1]
    fig, ax = plt.subplots(figsize=(6, max(3.0, 0.3 * len(top) + 1)))
    ax.barh(top["feature"], top["importance"], color="#3b6ea5")
    ax.set_xlabel("normalised importance")
    ax.set_title(title)
    return _save(fig, path)
