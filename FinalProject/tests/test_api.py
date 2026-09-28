"""
Unit tests for FastAPI Serving endpoints.
"""

import pytest
from fastapi.testclient import TestClient
from app.main import app


@pytest.fixture
def client():
    with TestClient(app) as test_client:
        yield test_client


def test_health_endpoint(client):
    response = client.get("/health")
    assert response.status_code == 200
    data = response.json()
    assert "status" in data
    assert data["model_loaded"] is True


def test_metrics_endpoint(client):
    response = client.get("/metrics")
    assert response.status_code == 200
    assert "credit_prediction_requests_total" in response.text


def test_predict_endpoint(client):
    payload = {
        "LIMIT_BAL": 50000.0,
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
        "BILL_AMT1": 20000.0,
        "BILL_AMT2": 19000.0,
        "BILL_AMT3": 18000.0,
        "BILL_AMT4": 15000.0,
        "BILL_AMT5": 14000.0,
        "BILL_AMT6": 13000.0,
        "PAY_AMT1": 2000.0,
        "PAY_AMT2": 2000.0,
        "PAY_AMT3": 2000.0,
        "PAY_AMT4": 2000.0,
        "PAY_AMT5": 2000.0,
        "PAY_AMT6": 2000.0,
    }
    response = client.post("/predict", json=payload)
    assert response.status_code == 200
    data = response.json()
    assert "default_prediction" in data
    assert data["default_prediction"] in [0, 1]
    assert "default_probability" in data
    assert 0.0 <= data["default_probability"] <= 1.0
    assert data["risk_decision"] in ["APPROVE", "REVIEW", "DECLINE"]
    assert "request_id" in data
    assert "credit_score" in data
    assert 300 <= data["credit_score"] <= 850
    assert data["credit_tier"] in ["PRIME", "NEAR_PRIME", "SUBPRIME", "HIGH_RISK"]
    assert "recommended_limit_ntd" in data
    assert isinstance(data["top_risk_factors"], list)
    assert "policy_guardrails" in data


def test_reload_model_endpoint(client):

    response = client.post("/reload-model")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ok"
    assert "model_source" in data
