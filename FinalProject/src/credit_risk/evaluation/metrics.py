"""Classification metrics for credit default models."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

import numpy as np
import pandas as pd
from sklearn.metrics import (
    accuracy_score,
    average_precision_score,
    brier_score_loss,
    confusion_matrix,
    f1_score,
    precision_score,
    recall_score,
    roc_auc_score,
)

from credit_risk.evaluation.business_cost import calculate_financial_loss


def evaluate_model(model: Any, features: pd.DataFrame, target: pd.Series) -> dict[str, float]:
    """Compute accuracy, precision, recall, F1, ROC-AUC, PR-AUC and confusion-matrix counts.

    ROC-AUC/PR-AUC use ``predict_proba`` when available; ROC-AUC is reported as
    0.5 (and PR-AUC as the positive rate) when ``target`` contains a single class.
    """
    y_pred = model.predict(features)
    y_prob = model.predict_proba(features)[:, 1] if hasattr(model, "predict_proba") else y_pred

    single_class = pd.Series(target).nunique() <= 1
    roc_auc = 0.5 if single_class else float(roc_auc_score(target, y_prob))
    pr_auc = float(np.mean(target)) if single_class else float(average_precision_score(target, y_prob))

    tn, fp, fn, tp = confusion_matrix(target, y_pred, labels=[0, 1]).ravel()

    return {
        "accuracy": float(accuracy_score(target, y_pred)),
        "precision": float(precision_score(target, y_pred, zero_division=0)),
        "recall": float(recall_score(target, y_pred, zero_division=0)),
        "f1_score": float(f1_score(target, y_pred, zero_division=0)),
        "roc_auc": roc_auc,
        "pr_auc": pr_auc,
        "true_negatives": int(tn),
        "false_positives": int(fp),
        "false_negatives": int(fn),
        "true_positives": int(tp),
    }


def classification_report_from_proba(
    y_true: Sequence[int] | np.ndarray | pd.Series,
    y_prob: Sequence[float] | np.ndarray,
    threshold: float = 0.5,
    cost_fn: float = 10.0,
    cost_fp: float = 1.0,
) -> dict[str, float]:
    """Threshold-based metrics plus business cost from predicted default probabilities.

    Returns ranking metrics (``roc_auc``, ``pr_auc``, ``brier``), decision metrics at
    ``threshold`` (``accuracy``, ``precision``, ``recall``, ``f1_score``, confusion
    counts) and the cost-matrix loss (``financial_loss`` total and
    ``expected_loss`` per cardholder).
    """
    labels = np.asarray(y_true, dtype=int)
    probs = np.asarray(y_prob, dtype=float)
    preds = (probs >= threshold).astype(int)
    single_class = np.unique(labels).size <= 1

    tn, fp, fn, tp = confusion_matrix(labels, preds, labels=[0, 1]).ravel()
    loss = calculate_financial_loss(labels, preds, cost_fn, cost_fp)
    n_samples = max(len(labels), 1)
    return {
        "roc_auc": 0.5 if single_class else float(roc_auc_score(labels, probs)),
        "pr_auc": float(labels.mean()) if single_class else float(average_precision_score(labels, probs)),
        "brier": float(brier_score_loss(labels, probs)),
        "accuracy": float(accuracy_score(labels, preds)),
        "precision": float(precision_score(labels, preds, zero_division=0)),
        "recall": float(recall_score(labels, preds, zero_division=0)),
        "f1_score": float(f1_score(labels, preds, zero_division=0)),
        "financial_loss": loss,
        "expected_loss": loss / n_samples,
        "true_negatives": int(tn),
        "false_positives": int(fp),
        "false_negatives": int(fn),
        "true_positives": int(tp),
    }
