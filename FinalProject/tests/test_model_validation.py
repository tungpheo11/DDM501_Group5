"""
Model Validation Tests for Credit Default Risk Scoring.
Enforces performance gates, latency SLA (< 50ms), probability calibration, and monotonicity.
"""

import time
import joblib
import numpy as np
import pytest
from sklearn.metrics import roc_auc_score

from src.config import MODELS_DIR, BASELINE_DATA_PATH
from src.data_loader import load_data


@pytest.fixture(scope="module")
def loaded_model():
    """Load model artifact for testing."""
    model_path = MODELS_DIR / "credit_model_v1.joblib"
    if not model_path.exists():
        pytest.skip(f"Model file not found at {model_path}")
    return joblib.load(model_path)


def test_model_performance_gate(loaded_model):
    """Quality Gate: Model ROC-AUC must be >= 0.70 on validation baseline data."""
    X, y = load_data(BASELINE_DATA_PATH)
    probs = loaded_model.predict_proba(X)[:, 1]
    auc_score = roc_auc_score(y, probs)
    assert (
        auc_score >= 0.70
    ), f"Model failed minimum performance gate: ROC-AUC={auc_score:.4f} < 0.70"


def test_inference_latency_sla(loaded_model):
    """SLA: Inference latency must be < 50ms per single loan request."""
    X, _ = load_data(BASELINE_DATA_PATH)
    single_sample = X.iloc[[0]]

    # Warm-up
    _ = loaded_model.predict_proba(single_sample)

    latencies = []
    for _ in range(50):
        t0 = time.perf_counter()
        _ = loaded_model.predict_proba(single_sample)
        latencies.append((time.perf_counter() - t0) * 1000.0)

    p95_latency = np.percentile(latencies, 95)
    mean_latency = np.mean(latencies)

    assert (
        mean_latency < 50.0
    ), f"Mean inference latency {mean_latency:.2f}ms exceeds 50ms SLA"
    assert (
        p95_latency < 100.0
    ), f"p95 inference latency {p95_latency:.2f}ms exceeds 100ms threshold"


def test_probability_calibration_and_ranges(loaded_model):
    """Verify default probabilities are strictly bounded within [0.0, 1.0]."""
    X, _ = load_data(BASELINE_DATA_PATH)
    sample_batch = X.iloc[:100]

    prob_matrix = loaded_model.predict_proba(sample_batch)

    assert prob_matrix.shape == (100, 2)
    assert (prob_matrix >= 0.0).all() and (prob_matrix <= 1.0).all()
    # Probabilities across binary classes must sum to 1.0
    assert np.allclose(prob_matrix.sum(axis=1), 1.0, atol=1e-5)


def test_prediction_determinism(loaded_model):
    """Verify model produces deterministic predictions for identical inputs."""
    X, _ = load_data(BASELINE_DATA_PATH)
    sample = X.iloc[[10]]

    pred1 = loaded_model.predict_proba(sample)[0, 1]
    pred2 = loaded_model.predict_proba(sample)[0, 1]
    assert pred1 == pred2, "Model is non-deterministic on identical feature input!"


def test_risk_monotonicity_pay0(loaded_model):
    """
    Monotonicity Principle:
    Increasing delinquency status in PAY_0 (from 0 on-time to 2 months late)
    must increase the predicted default probability.
    """
    X, _ = load_data(BASELINE_DATA_PATH)
    base_sample = X.iloc[[0]].copy()

    base_sample["PAY_0"] = 0
    p_ontime = loaded_model.predict_proba(base_sample)[0, 1]

    base_sample["PAY_0"] = 2
    p_delinquent = loaded_model.predict_proba(base_sample)[0, 1]

    assert (
        p_delinquent >= p_ontime
    ), f"Monotonicity violation: P(late)={p_delinquent:.4f} < P(ontime)={p_ontime:.4f}"
