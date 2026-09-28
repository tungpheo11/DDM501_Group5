"""Business cost of classification errors."""

from __future__ import annotations

from collections.abc import Sequence

import numpy as np
from sklearn.metrics import confusion_matrix


def calculate_financial_loss(
    y_true: Sequence[int] | np.ndarray,
    y_pred: Sequence[int] | np.ndarray,
    cost_fn: float = 10.0,
    cost_fp: float = 1.0,
) -> float:
    """Total loss under an asymmetric cost matrix: ``FN * cost_fn + FP * cost_fp``."""
    _, fp, fn, _ = confusion_matrix(y_true, y_pred, labels=[0, 1]).ravel()
    return float(fn * cost_fn + fp * cost_fp)


def expected_financial_loss(
    y_true: Sequence[int] | np.ndarray,
    y_pred: Sequence[int] | np.ndarray,
    cost_fn: float = 10.0,
    cost_fp: float = 1.0,
) -> float:
    """Average loss per applicant, comparable across evaluation sets of different sizes."""
    n_samples = len(y_true)
    if n_samples == 0:
        return 0.0
    return calculate_financial_loss(y_true, y_pred, cost_fn, cost_fp) / n_samples


def cost_optimal_threshold(
    y_true: Sequence[int] | np.ndarray,
    y_prob: Sequence[float] | np.ndarray,
    cost_fn: float = 10.0,
    cost_fp: float = 1.0,
    grid: np.ndarray | None = None,
) -> tuple[float, float]:
    """Probability threshold minimising total loss on ``(y_true, y_prob)``.

    Returns:
        ``(threshold, total_loss_at_threshold)``; ties resolve to the highest threshold.
    """
    labels = np.asarray(y_true, dtype=int)
    probs = np.asarray(y_prob, dtype=float)
    thresholds = np.round(np.linspace(0.05, 0.95, 91), 4) if grid is None else grid
    best_threshold, best_loss = 0.5, float("inf")
    for threshold in thresholds:
        loss = calculate_financial_loss(labels, (probs >= threshold).astype(int), cost_fn, cost_fp)
        if loss <= best_loss:
            best_threshold, best_loss = float(threshold), loss
    return best_threshold, best_loss
