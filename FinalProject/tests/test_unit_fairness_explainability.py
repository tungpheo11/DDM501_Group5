"""
Unit tests for Responsible AI (Fairness & Explainability)
"""

import numpy as np
import pandas as pd
from sklearn.dummy import DummyClassifier

from src.fairness import (
    disparate_impact_ratio,
    demographic_parity_difference,
    evaluate_fairness,
)
from src.explainability import (
    get_global_feature_importance,
    explain_single_prediction,
)
from src.config import ALL_FEATURES


def test_fairness_metrics():
    """Test selection rate, disparate impact ratio, and demographic parity difference."""
    y_pred = np.array([0, 0, 1, 0, 1, 0, 1, 1])  # 0 is approve/good
    protected = np.array([1, 1, 1, 1, 2, 2, 2, 2])

    dir_score = disparate_impact_ratio(
        y_pred, protected, privileged_value=1, unprivileged_value=2
    )
    assert isinstance(dir_score, float)
    assert dir_score > 0.0

    dpd_score = demographic_parity_difference(
        y_pred, protected, privileged_value=1, unprivileged_value=2
    )
    assert isinstance(dpd_score, float)
    assert 0.0 <= dpd_score <= 1.0


def test_evaluate_fairness_end_to_end():
    """Test full fairness evaluation on model with demographic features."""
    n_samples = 40
    data = {feat: np.random.uniform(1, 10, n_samples) for feat in ALL_FEATURES}
    data["SEX"] = np.random.choice([1, 2], n_samples)
    data["EDUCATION"] = np.random.choice([1, 2, 3], n_samples)
    data["AGE"] = np.random.choice([25, 45], n_samples)

    X = pd.DataFrame(data)
    y = pd.Series(np.random.choice([0, 1], n_samples))

    model = DummyClassifier(strategy="most_frequent")
    model.fit(X, y)

    report = evaluate_fairness(model, X, y)
    assert "status" in report
    assert "attributes" in report
    assert "SEX (Gender)" in report["attributes"]
    assert "EDUCATION (Level)" in report["attributes"]
    assert "AGE (Cohort)" in report["attributes"]


def test_explainability_methods():
    """Test global importance extraction and local adverse action codes."""
    n_samples = 20
    data = {feat: np.random.uniform(1, 10, n_samples) for feat in ALL_FEATURES}
    X = pd.DataFrame(data)
    y = pd.Series(np.random.choice([0, 1], n_samples))

    model = DummyClassifier(strategy="uniform", random_state=42)
    model.fit(X, y)

    # 1. Global feature importance
    importances = get_global_feature_importance(model, ALL_FEATURES)
    assert len(importances) == len(ALL_FEATURES)
    assert importances[0]["importance_weight"] >= importances[-1]["importance_weight"]

    # 2. Local explanation
    row = X.iloc[0].to_dict()
    explanation = explain_single_prediction(model, row, ALL_FEATURES)
    assert "default_probability" in explanation
    assert "risk_tier" in explanation
    assert explanation["risk_tier"] in ["APPROVE", "REVIEW", "DECLINE"]
    assert len(explanation["primary_risk_drivers"]) <= 4
