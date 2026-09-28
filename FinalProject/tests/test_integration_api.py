"""
Integration Tests for FastAPI Model Serving Engine and Endpoints.
Tests API validation, error schemas, risk tiering, model reload, and telemetry.
"""

from fastapi.testclient import TestClient
import pytest
from app.main import app


@pytest.fixture(scope="module")
def client():
    """Create FastAPI test client."""
    with TestClient(app) as test_client:
        yield test_client


def test_predict_schema_validation_error(client):
    """Verify malformed payload (missing fields or wrong types) returns HTTP 422."""
    bad_payload = {
        "LIMIT_BAL": "not-a-number",  # Invalid type
        "AGE": 30,
    }
    response = client.post("/predict", json=bad_payload)
    assert response.status_code == 422
    data = response.json()
    assert "detail" in data


def test_predict_risk_decision_structure(client):
    """Verify complete response schema for loan prediction."""
    valid_payload = {
        "LIMIT_BAL": 200000.0,
        "SEX": 1,
        "EDUCATION": 2,
        "MARRIAGE": 1,
        "AGE": 35,
        "PAY_0": 0,
        "PAY_2": 0,
        "PAY_3": 0,
        "PAY_4": 0,
        "PAY_5": 0,
        "PAY_6": 0,
        "BILL_AMT1": 15000.0,
        "BILL_AMT2": 14000.0,
        "BILL_AMT3": 13000.0,
        "BILL_AMT4": 12000.0,
        "BILL_AMT5": 11000.0,
        "BILL_AMT6": 10000.0,
        "PAY_AMT1": 2000.0,
        "PAY_AMT2": 2000.0,
        "PAY_AMT3": 2000.0,
        "PAY_AMT4": 2000.0,
        "PAY_AMT5": 2000.0,
        "PAY_AMT6": 2000.0,
    }

    response = client.post("/predict", json=valid_payload)
    assert response.status_code == 200
    data = response.json()

    required_fields = [
        "default_prediction",
        "default_probability",
        "risk_decision",
        "credit_score",
        "credit_tier",
        "request_id",
    ]
    for field in required_fields:
        assert field in data, f"Missing {field} in prediction response"

    assert data["risk_decision"] in ["APPROVE", "REVIEW", "DECLINE"]
    assert 0.0 <= data["default_probability"] <= 1.0
    assert 300 <= data["credit_score"] <= 850


def test_reload_model_fallback(client):
    """Verify reloading model handles request smoothly."""
    response = client.post("/reload-model")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ok"


def test_prometheus_metrics_integration(client):
    """Verify Prometheus metrics endpoint exposes custom credit risk telemetry."""
    # Send request to trigger metric accumulation
    test_predict_risk_decision_structure(client)

    response = client.get("/metrics")
    assert response.status_code == 200
    metrics_text = response.text

    assert "credit_prediction_requests_total" in metrics_text
    assert "credit_prediction_duration_seconds" in metrics_text
