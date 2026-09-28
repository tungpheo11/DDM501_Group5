"""
Unit tests for src/evaluate.py
"""

import pandas as pd
from sklearn.dummy import DummyClassifier

from src.evaluate import evaluate_model


def test_evaluate_model_metrics():
    """Test comprehensive evaluation metrics calculation."""
    X = pd.DataFrame({"feat1": [1, 2, 3, 4, 5, 6, 7, 8, 9, 10]})
    y = pd.Series([0, 1, 0, 1, 0, 1, 0, 1, 0, 1])

    # Fit a simple dummy classifier
    model = DummyClassifier(strategy="uniform", random_state=42)
    model.fit(X, y)

    metrics = evaluate_model(model, X, y)

    expected_keys = [
        "accuracy",
        "precision",
        "recall",
        "f1_score",
        "roc_auc",
        "true_negatives",
        "false_positives",
        "false_negatives",
        "true_positives",
    ]

    for key in expected_keys:
        assert key in metrics
        assert isinstance(metrics[key], (float, int))

    assert 0.0 <= metrics["accuracy"] <= 1.0
    assert 0.0 <= metrics["f1_score"] <= 1.0
    assert 0.0 <= metrics["roc_auc"] <= 1.0
    assert (
        metrics["true_negatives"]
        + metrics["false_positives"]
        + metrics["false_negatives"]
        + metrics["true_positives"]
        == len(y)
    )
