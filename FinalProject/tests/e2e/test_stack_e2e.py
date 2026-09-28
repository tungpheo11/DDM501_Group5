"""End-to-end tests on the running stack: API <-> MLflow registry <-> drift monitor <-> monitoring <-> Airflow.

Read-only apart from a handful of scoring requests (which land in ``inference_logs`` like normal traffic).
Run with ``make test-e2e``.
"""

from __future__ import annotations

from typing import Any

import pytest

Stack = Any  # fixture type lives in tests/e2e/conftest.py (not importable under --import-mode=importlib)

pytestmark = pytest.mark.e2e

ERROR_KEYS = {"code", "message", "details", "request_id"}
DECISIONS = {"APPROVE", "REVIEW", "DECLINE"}
EXPECTED_ALERTS = {
    "APIDown",
    "HighErrorRate",
    "HighLatencyP95",
    "DataDriftDetected",
    "DriftMonitorDown",
    "DriftAnalysisStale",
    "ModelNotLoaded",
    "ModelServedFromFallback",
    "PredictionDistributionShift",
    "RetrainFailed",
    "AirflowDagImportErrors",
}
EXPECTED_DAGS = {"drift_monitoring", "model_retrain", "service_health_check"}


# --- Serving API ---------------------------------------------------------------


def test_readiness_reports_every_dependency(stack: Stack) -> None:
    response = stack.get(f"{stack.api_url}/health/ready")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] in {"ready", "degraded"}
    assert set(body["checks"]) >= {"model", "mlflow", "database"}


def test_predict_returns_full_contract(stack: Stack, auth: dict[str, str], low_risk_applicant: dict) -> None:
    response = stack.post(f"{stack.api_url}/api/v1/predict", json=low_risk_applicant, headers=auth)
    assert response.status_code == 200
    body = response.json()
    assert 0.0 <= body["default_probability"] <= 1.0
    assert body["default_prediction"] in (0, 1)
    assert body["risk_decision"] in DECISIONS
    assert 300 <= body["credit_score"] <= 850
    assert body["served_by"] in {"mlflow_registry", "local_artifact"}
    assert body["request_id"] == response.headers["X-Request-ID"]


def test_high_risk_applicant_scores_worse(
    stack: Stack, auth: dict[str, str], low_risk_applicant: dict, high_risk_applicant: dict
) -> None:
    url = f"{stack.api_url}/api/v1/predict"
    low = stack.post(url, json=low_risk_applicant, headers=auth).json()
    high = stack.post(url, json=high_risk_applicant, headers=auth).json()
    assert high["default_probability"] > low["default_probability"]
    assert high["credit_score"] < low["credit_score"]
    assert high["risk_decision"] == "DECLINE"


def test_batch_predict_scores_every_applicant(
    stack: Stack, auth: dict[str, str], low_risk_applicant: dict, high_risk_applicant: dict
) -> None:
    payload = {"applicants": [low_risk_applicant, high_risk_applicant, low_risk_applicant]}
    response = stack.post(f"{stack.api_url}/api/v1/predict/batch", json=payload, headers=auth)
    assert response.status_code == 200
    body = response.json()
    results = body.get("predictions") or body.get("results")
    assert results is not None and len(results) == 3


@pytest.mark.parametrize(
    ("headers", "status", "code"),
    [({}, 401, "MISSING_API_KEY"), ({"X-API-Key": "wrong-key"}, 403, "INVALID_API_KEY")],
)
def test_auth_errors_use_error_contract(
    stack: Stack, low_risk_applicant: dict, headers: dict, status: int, code: str
) -> None:
    response = stack.post(f"{stack.api_url}/api/v1/predict", json=low_risk_applicant, headers=headers)
    assert response.status_code == status
    body = response.json()
    assert set(body) == ERROR_KEYS
    assert body["code"] == code


def test_validation_error_lists_fields_without_echoing_input(stack: Stack, auth: dict[str, str]) -> None:
    secret_value = 987654321.123
    response = stack.post(f"{stack.api_url}/api/v1/predict", json={"LIMIT_BAL": -secret_value, "AGE": 12}, headers=auth)
    assert response.status_code == 422
    body = response.json()
    assert set(body) == ERROR_KEYS
    assert body["details"], "every invalid field should be listed"
    assert str(secret_value) not in response.text


def test_oversized_batch_is_rejected(stack: Stack, auth: dict[str, str], low_risk_applicant: dict) -> None:
    payload = {"applicants": [low_risk_applicant] * 501}
    response = stack.post(f"{stack.api_url}/api/v1/predict/batch", json=payload, headers=auth)
    assert response.status_code == 413
    assert response.json()["code"] == "BATCH_TOO_LARGE"


def test_metrics_endpoint_exposes_service_and_model_metrics(stack: Stack) -> None:
    text = stack.get(f"{stack.api_url}/metrics").text
    for metric in ("credit_api_requests_total", "credit_api_auth_failures_total", "credit_model_loaded"):
        assert metric in text


# --- Model registry ------------------------------------------------------------


def test_api_serves_the_registry_champion(stack: Stack, auth: dict[str, str], require) -> None:
    require(f"{stack.mlflow_url}/health")
    info = stack.get(f"{stack.api_url}/api/v1/model/info", headers=auth).json()
    if info["source"] != "mlflow_registry":
        pytest.skip(f"API is serving from {info['source']} (degraded mode)")
    alias = stack.get(
        f"{stack.mlflow_url}/api/2.0/mlflow/registered-models/alias",
        params={"name": info["model_name"], "alias": info["model_alias"]},
    )
    assert alias.status_code == 200
    assert alias.json()["model_version"]["version"] == info["model_version"]


# --- Drift monitor -------------------------------------------------------------


def test_drift_monitor_analyzes_recent_traffic(stack: Stack, require) -> None:
    require(f"{stack.drift_url}/health")
    health = stack.get(f"{stack.drift_url}/health").json()
    assert health["reference_loaded"] is True
    result = stack.post(f"{stack.drift_url}/analyze", timeout=60).json()
    assert result["status"] == "success"
    assert {"is_drifted", "drift_share", "max_psi", "psi"} <= set(result)
    assert 0.0 <= result["drift_share"] <= 1.0


def test_drift_monitor_publishes_html_reports(stack: Stack, require) -> None:
    require(f"{stack.drift_url}/health")
    listing = stack.get(f"{stack.drift_url}/reports").json()
    assert listing["count"] >= 1
    latest = stack.get(f"{stack.drift_url}{listing['reports'][0]['url']}")
    assert latest.status_code == 200
    assert "<html" in latest.text[:2000].lower()


# --- Monitoring & alerting -----------------------------------------------------


def test_prometheus_scrapes_every_target(stack: Stack, require) -> None:
    require(f"{stack.prometheus_url}/-/ready")
    targets = stack.get(f"{stack.prometheus_url}/api/v1/targets").json()["data"]["activeTargets"]
    jobs = {t["labels"]["job"]: t["health"] for t in targets}
    assert jobs.get("credit-risk-api") == "up"
    assert jobs.get("drift-monitor") == "up"


def test_prometheus_loads_all_alert_rules(stack: Stack, require) -> None:
    require(f"{stack.prometheus_url}/-/ready")
    groups = stack.get(f"{stack.prometheus_url}/api/v1/rules").json()["data"]["groups"]
    alerts = {r["name"] for g in groups for r in g["rules"] if r["type"] == "alerting"}
    assert alerts >= EXPECTED_ALERTS


def test_alertmanager_routes_to_webhook_receiver(stack: Stack, require) -> None:
    require(f"{stack.alertmanager_url}/-/ready")
    status = stack.get(f"{stack.alertmanager_url}/api/v2/status").json()
    assert status["cluster"]["status"] == "ready"
    assert "webhook" in status["config"]["original"]
    assert stack.get(f"{stack.webhook_url}/alerts/state").status_code == 200


def test_grafana_provisions_four_dashboards(stack: Stack, require) -> None:
    require(f"{stack.grafana_url}/api/health")
    dashboards = stack.get(
        f"{stack.grafana_url}/api/search", params={"type": "dash-db"}, auth=stack.grafana_auth
    ).json()
    uids = {d["uid"] for d in dashboards}
    assert {"credit-business", "credit-drift", "credit-infra-sla", "credit-ml-model"} <= uids


# --- Orchestration -------------------------------------------------------------


def test_airflow_registers_all_dags_without_import_errors(stack: Stack, require) -> None:
    require(f"{stack.airflow_url}/health")
    dags = stack.get(f"{stack.airflow_url}/api/v1/dags", auth=stack.airflow_auth).json()["dags"]
    assert {d["dag_id"] for d in dags} >= EXPECTED_DAGS
    errors = stack.get(f"{stack.airflow_url}/api/v1/importErrors", auth=stack.airflow_auth).json()
    assert errors["total_entries"] == 0
