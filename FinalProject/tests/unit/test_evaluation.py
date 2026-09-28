import numpy as np
import pandas as pd
import pytest

from credit_risk.evaluation.business_cost import (
    calculate_financial_loss,
    cost_optimal_threshold,
    expected_financial_loss,
)
from credit_risk.evaluation.metrics import classification_report_from_proba, evaluate_model


class _ConstantModel:
    def __init__(self, label: int):
        self.label = label

    def predict(self, features):
        return np.full(len(features), self.label)


def test_financial_loss_weights_false_negatives():
    y_true = [1, 1, 0, 0]
    y_pred = [0, 1, 1, 0]
    assert calculate_financial_loss(y_true, y_pred) == pytest.approx(11.0)
    assert calculate_financial_loss(y_true, y_pred, cost_fn=5, cost_fp=2) == pytest.approx(7.0)


def test_financial_loss_handles_single_class():
    assert calculate_financial_loss([0, 0], [0, 0]) == 0.0


def test_evaluate_model_on_real_model(champion_model, settings):
    frame = pd.read_csv(settings.paths.normal_stream).head(500)
    from credit_risk.data.schema import ALL_FEATURES, TARGET_COLUMN

    metrics = evaluate_model(champion_model, frame[ALL_FEATURES], frame[TARGET_COLUMN])
    assert set(metrics) >= {"accuracy", "precision", "recall", "f1_score", "roc_auc"}
    assert metrics["true_negatives"] + metrics["false_positives"] + metrics["false_negatives"] + metrics[
        "true_positives"
    ] == len(frame)
    assert 0.5 < metrics["roc_auc"] <= 1.0


def test_evaluate_model_without_predict_proba_single_class():
    features = pd.DataFrame({"x": [1, 2, 3]})
    metrics = evaluate_model(_ConstantModel(0), features, pd.Series([0, 0, 0]))
    assert metrics["roc_auc"] == 0.5
    assert metrics["pr_auc"] == 0.0
    assert metrics["true_negatives"] == 3


def test_expected_financial_loss_is_per_applicant():
    assert expected_financial_loss([1, 1, 0, 0], [0, 1, 1, 0]) == pytest.approx(11.0 / 4)
    assert expected_financial_loss([], []) == 0.0


def test_classification_report_from_proba():
    y_true = [0, 0, 1, 1, 1]
    y_prob = [0.1, 0.6, 0.4, 0.8, 0.9]
    report = classification_report_from_proba(y_true, y_prob, threshold=0.5, cost_fn=10, cost_fp=1)
    assert report["true_positives"] == 2 and report["false_negatives"] == 1
    assert report["false_positives"] == 1 and report["true_negatives"] == 1
    assert report["recall"] == pytest.approx(2 / 3)
    assert report["financial_loss"] == pytest.approx(11.0)
    assert report["expected_loss"] == pytest.approx(11.0 / 5)
    assert report["roc_auc"] == pytest.approx(5 / 6)
    assert 0 < report["pr_auc"] <= 1
    assert 0 <= report["brier"] <= 1


def test_classification_report_threshold_changes_decisions():
    y_true, y_prob = [0, 1], [0.2, 0.3]
    assert classification_report_from_proba(y_true, y_prob, threshold=0.5)["recall"] == 0.0
    assert classification_report_from_proba(y_true, y_prob, threshold=0.25)["recall"] == 1.0


def test_classification_report_single_class():
    report = classification_report_from_proba([0, 0, 0], [0.1, 0.2, 0.9])
    assert report["roc_auc"] == 0.5
    assert report["false_positives"] == 1


def test_cost_optimal_threshold_prefers_recall_under_asymmetric_costs():
    rng = np.random.default_rng(0)
    y_true = rng.integers(0, 2, 400)
    y_prob = np.clip(y_true * 0.3 + rng.uniform(0, 0.7, 400), 0, 1)
    threshold, loss = cost_optimal_threshold(y_true, y_prob, cost_fn=10, cost_fp=1)
    assert threshold < 0.5
    assert loss <= calculate_financial_loss(y_true, (y_prob >= 0.5).astype(int))
    symmetric_threshold, _ = cost_optimal_threshold(y_true, y_prob, cost_fn=1, cost_fp=1)
    assert symmetric_threshold >= threshold
