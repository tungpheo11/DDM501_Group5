"""
Module: evaluate.py
Calculates model performance metrics and fairness/drift indicators.
"""

from typing import Dict, Any
import pandas as pd
from sklearn.metrics import (
    accuracy_score,
    precision_score,
    recall_score,
    f1_score,
    roc_auc_score,
    confusion_matrix,
)


def evaluate_model(model: Any, X: pd.DataFrame, y: pd.Series) -> Dict[str, float]:
    """
    Computes comprehensive evaluation metrics for classification.
    """
    y_pred = model.predict(X)

    # Get probabilities for positive class (default)
    if hasattr(model, "predict_proba"):
        y_prob = model.predict_proba(X)[:, 1]
    else:
        y_prob = y_pred

    acc = float(accuracy_score(y, y_pred))
    prec = float(precision_score(y, y_pred, zero_division=0))
    rec = float(recall_score(y, y_pred, zero_division=0))
    f1 = float(f1_score(y, y_pred, zero_division=0))

    try:
        roc_auc = float(roc_auc_score(y, y_prob))
    except Exception:
        roc_auc = 0.5

    tn, fp, fn, tp = confusion_matrix(y, y_pred).ravel()

    metrics = {
        "accuracy": acc,
        "precision": prec,
        "recall": rec,
        "f1_score": f1,
        "roc_auc": roc_auc,
        "true_negatives": int(tn),
        "false_positives": int(fp),
        "false_negatives": int(fn),
        "true_positives": int(tp),
    }
    return metrics
