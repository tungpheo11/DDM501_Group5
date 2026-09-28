"""Acceptance thresholds for the served champion artifact (offline evaluation)."""

import pytest

from credit_risk.data.loader import load_data
from credit_risk.evaluation.business_cost import calculate_financial_loss
from credit_risk.evaluation.metrics import evaluate_model

pytestmark = pytest.mark.model_validation

MIN_ROC_AUC = 0.70
MIN_RECALL = 0.45


@pytest.fixture(scope="module")
def normal_stream(settings):
    features, target = load_data(settings.paths.normal_stream)
    assert target is not None
    return features, target


def test_champion_meets_roc_auc_threshold(champion_model, normal_stream):
    metrics = evaluate_model(champion_model, *normal_stream)
    assert metrics["roc_auc"] >= MIN_ROC_AUC


def test_champion_meets_recall_threshold(champion_model, normal_stream):
    metrics = evaluate_model(champion_model, *normal_stream)
    assert metrics["recall"] >= MIN_RECALL


def test_champion_beats_always_approve_on_business_cost(champion_model, normal_stream):
    features, target = normal_stream
    model_loss = calculate_financial_loss(target, champion_model.predict(features))
    always_approve_loss = calculate_financial_loss(target, [0] * len(target))
    assert model_loss < always_approve_loss


def test_probabilities_are_monotonic_in_delinquency(champion_model, normal_stream):
    features, _ = normal_stream
    sample = features.head(200).copy()
    on_time = champion_model.predict_proba(sample.assign(PAY_0=0))[:, 1].mean()
    delinquent = champion_model.predict_proba(sample.assign(PAY_0=3))[:, 1].mean()
    assert delinquent > on_time
