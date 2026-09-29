"""Integration tests for the v1 scoring API (fixtures live in tests/conftest.py)."""

from __future__ import annotations

import pytest
from prometheus_client import REGISTRY

from credit_risk.serving import database

pytestmark = pytest.mark.integration

ERROR_KEYS = {"code", "message", "details", "request_id"}


def assert_error(response, status: int, code: str) -> dict:
    assert response.status_code == status
    body = response.json()
    assert set(body) == ERROR_KEYS
    assert body["code"] == code
    assert body["request_id"] == response.headers["X-Request-ID"]
    return body


# --- Health -----------------------------------------------------------------


def test_liveness_needs_no_auth(anon_client):
    response = anon_client.get("/health/live")
    assert response.status_code == 200
    assert response.json()["status"] == "alive"


def test_readiness_is_degraded_on_local_fallback(anon_client):
    response = anon_client.get("/health/ready")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "degraded"
    assert "model_served_from_local_fallback" in body["reasons"]
    assert "mlflow_unreachable" in body["reasons"]
    assert body["checks"]["model"]["status"] == "degraded"
    assert body["checks"]["database"]["status"] == "ok"


def test_readiness_is_503_without_model(anon_client, monkeypatch):
    monkeypatch.setattr(anon_client.app.state.model_manager, "_current", None)
    response = anon_client.get("/health/ready")
    assert response.status_code == 503
    body = response.json()
    assert body["status"] == "not_ready"
    assert "model_not_loaded" in body["reasons"]


def test_readiness_reports_database_down(anon_client, monkeypatch):
    probe = anon_client.app.state.readiness_probe
    monkeypatch.setattr(database, "_engine", None)
    probe.invalidate()
    body = anon_client.get("/health/ready").json()
    assert body["status"] == "degraded"
    assert "database_unavailable" in body["reasons"]


# --- Auth -------------------------------------------------------------------


@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("post", "/api/v1/predict"),
        ("post", "/api/v1/predict/batch"),
        ("post", "/api/v1/explain"),
        ("get", "/api/v1/model/info"),
        ("post", "/api/v1/model/reload"),
    ],
)
def test_protected_routes_require_api_key(anon_client, method, path):
    response = getattr(anon_client, method)(path)
    assert_error(response, 401, "MISSING_API_KEY")
    assert response.headers["WWW-Authenticate"] == "ApiKey"


def test_invalid_api_key_is_forbidden(anon_client, valid_payload):
    response = anon_client.post("/api/v1/predict", json=valid_payload, headers={"X-API-Key": "wrong"})
    assert_error(response, 403, "INVALID_API_KEY")


def test_auth_fails_closed_when_no_key_configured(make_client, valid_payload, auth_headers):
    test_client = make_client(api_keys=())
    response = test_client.post("/api/v1/predict", json=valid_payload, headers=auth_headers)
    assert_error(response, 403, "INVALID_API_KEY")


def test_auth_can_be_disabled_for_local_dev(make_client, valid_payload):
    test_client = make_client(auth_enabled=False)
    assert test_client.post("/api/v1/predict", json=valid_payload).status_code == 200


def test_key_rotation_accepts_every_configured_key(make_client, valid_payload):
    test_client = make_client(api_keys=("old-key", "new-key"))
    for key in ("old-key", "new-key"):
        response = test_client.post("/api/v1/predict", json=valid_payload, headers={"X-API-Key": key})
        assert response.status_code == 200


# --- Predict ----------------------------------------------------------------


def test_predict_returns_full_contract(client, valid_payload):
    response = client.post("/api/v1/predict", json=valid_payload)
    assert response.status_code == 200
    data = response.json()
    assert data["request_id"] == response.headers["X-Request-ID"]
    assert data["default_prediction"] in (0, 1)
    assert 0.0 <= data["default_probability"] <= 1.0
    assert data["risk_decision"] in {"APPROVE", "REVIEW", "DECLINE"}
    assert 300 <= data["credit_score"] <= 850
    assert data["credit_tier"] in {"PRIME", "NEAR_PRIME", "SUBPRIME", "HIGH_RISK"}
    assert data["recommended_limit_ntd"] >= 0
    assert isinstance(data["top_risk_factors"], list)
    assert set(data["policy_guardrails"]) == {"age_verification", "utilization_ceiling_check", "delinquency_guardrail"}
    assert data["served_by"] == "local_artifact"
    assert data["model_version"] == "credit_model_v1"


def test_predict_matches_model_probability(client, valid_payload, champion_model):
    import pandas as pd

    expected = champion_model.predict_proba(pd.DataFrame([valid_payload]))[0][1]
    data = client.post("/api/v1/predict", json=valid_payload).json()
    assert data["default_probability"] == pytest.approx(expected, abs=1e-6)
    assert data["default_prediction"] == int(champion_model.predict(pd.DataFrame([valid_payload]))[0])


def test_predict_propagates_client_request_id(client, valid_payload):
    response = client.post("/api/v1/predict", json=valid_payload, headers={"X-Request-ID": "trace-abc_123"})
    assert response.headers["X-Request-ID"] == "trace-abc_123"
    assert response.json()["request_id"] == "trace-abc_123"


def test_malformed_request_id_is_replaced(client, valid_payload):
    response = client.post("/api/v1/predict", json=valid_payload, headers={"X-Request-ID": "bad id\twith spaces"})
    assert response.headers["X-Request-ID"].startswith("req_")


def test_high_risk_applicant_is_not_approved(client, high_risk_payload):
    data = client.post("/api/v1/predict", json=high_risk_payload).json()
    assert data["risk_decision"] in {"REVIEW", "DECLINE"}
    assert data["policy_guardrails"]["delinquency_guardrail"] == "ELEVATED_DEFAULT_RISK"


def test_predict_persists_inference_log(client, valid_payload):
    before = database.count_inference_logs()
    assert client.post("/api/v1/predict", json=valid_payload).status_code == 200
    assert database.count_inference_logs() == before + 1


def test_predict_returns_503_when_no_model(client, valid_payload, monkeypatch):
    monkeypatch.setattr(client.app.state.model_manager, "_current", None)
    assert_error(client.post("/api/v1/predict", json=valid_payload), 503, "MODEL_UNAVAILABLE")


def test_unhandled_error_returns_generic_500(client, valid_payload, monkeypatch):
    def boom(*_args, **_kwargs):
        raise RuntimeError("secret internal detail")

    monkeypatch.setattr(client.app.state.scoring_service, "score", boom)
    response = client.post("/api/v1/predict", json=valid_payload)
    body = assert_error(response, 500, "INTERNAL_ERROR")
    assert "secret" not in response.text
    assert body["details"] is None


# --- Validation (4xx) -------------------------------------------------------


def test_missing_field_is_rejected(client, valid_payload):
    payload = dict(valid_payload)
    payload.pop("AGE")
    body = assert_error(client.post("/api/v1/predict", json=payload), 422, "VALIDATION_ERROR")
    assert body["details"][0]["field"] == "AGE"
    assert body["details"][0]["type"] == "missing"


def test_wrong_type_is_rejected(client, valid_payload):
    assert_error(client.post("/api/v1/predict", json={**valid_payload, "LIMIT_BAL": "a lot"}), 422, "VALIDATION_ERROR")


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("AGE", 17),
        ("AGE", 101),
        ("SEX", 3),
        ("EDUCATION", 7),
        ("MARRIAGE", -1),
        ("PAY_0", 10),
        ("PAY_6", -3),
        ("LIMIT_BAL", 0),
        ("LIMIT_BAL", 50_000_000),
        ("PAY_AMT1", -1),
        ("BILL_AMT1", -20_000_000),
    ],
)
def test_out_of_domain_values_are_rejected(client, valid_payload, field, value):
    body = assert_error(client.post("/api/v1/predict", json={**valid_payload, field: value}), 422, "VALIDATION_ERROR")
    assert body["details"][0]["field"] == field
    assert "constraint" in body["details"][0]


def test_unknown_field_is_rejected(client, valid_payload):
    body = assert_error(client.post("/api/v1/predict", json={**valid_payload, "SSN": "123"}), 422, "VALIDATION_ERROR")
    assert body["details"][0]["type"] == "extra_forbidden"


def test_validation_errors_do_not_echo_input(client, valid_payload):
    response = client.post("/api/v1/predict", json={**valid_payload, "AGE": 12345})
    assert "12345" not in response.text


def test_malformed_json_is_rejected(client):
    response = client.post("/api/v1/predict", content=b"{not json", headers={"Content-Type": "application/json"})
    assert_error(response, 422, "VALIDATION_ERROR")


def test_unknown_route_uses_error_schema(client):
    assert_error(client.get("/api/v1/does-not-exist"), 404, "NOT_FOUND")


def test_wrong_method_uses_error_schema(client):
    assert_error(client.get("/api/v1/predict"), 405, "METHOD_NOT_ALLOWED")


# --- Batch ------------------------------------------------------------------


def test_batch_scores_in_request_order(client, valid_payload, high_risk_payload):
    before = database.count_inference_logs()
    response = client.post("/api/v1/predict/batch", json={"applicants": [valid_payload, high_risk_payload]})
    assert response.status_code == 200
    data = response.json()
    request_id = response.headers["X-Request-ID"]
    assert data["count"] == 2
    assert [item["index"] for item in data["predictions"]] == [0, 1]
    assert [item["request_id"] for item in data["predictions"]] == [f"{request_id}-0", f"{request_id}-1"]
    assert sum(data["decision_summary"].values()) == 2
    assert data["predictions"][1]["risk_decision"] in {"REVIEW", "DECLINE"}
    assert database.count_inference_logs() == before + 2


def test_batch_matches_single_predictions(client, valid_payload, high_risk_payload):
    batch = client.post("/api/v1/predict/batch", json={"applicants": [valid_payload, high_risk_payload]}).json()
    for item, payload in zip(batch["predictions"], (valid_payload, high_risk_payload), strict=True):
        single = client.post("/api/v1/predict", json=payload).json()
        assert item["default_probability"] == pytest.approx(single["default_probability"])


def test_empty_batch_is_rejected(client):
    assert_error(client.post("/api/v1/predict/batch", json={"applicants": []}), 422, "VALIDATION_ERROR")


def test_oversized_batch_is_rejected(make_client, auth_headers, valid_payload):
    test_client = make_client(batch_max_size=2)
    response = test_client.post("/api/v1/predict/batch", json={"applicants": [valid_payload] * 3}, headers=auth_headers)
    body = assert_error(response, 413, "BATCH_TOO_LARGE")
    assert body["details"] == {"max_size": 2, "received": 3}


def test_batch_reports_invalid_item_position(client, valid_payload):
    response = client.post("/api/v1/predict/batch", json={"applicants": [valid_payload, {**valid_payload, "SEX": 9}]})
    body = assert_error(response, 422, "VALIDATION_ERROR")
    assert body["details"][0]["field"] == "applicants.1.SEX"


# --- Explain ----------------------------------------------------------------


def test_explain_returns_ranked_contributions(client, high_risk_payload, settings):
    response = client.post("/api/v1/explain", json=high_risk_payload)
    assert response.status_code == 200
    data = response.json()
    contributions = data["contributions"]
    assert data["method"] == "shap_permutation"
    assert 0 < len(contributions) <= settings.serving.explain_top_k
    magnitudes = [abs(item["contribution"]) for item in contributions]
    assert magnitudes == sorted(magnitudes, reverse=True)
    assert 0.0 <= data["reference_probability"] <= 1.0
    assert data["default_probability"] > data["reference_probability"]
    assert any(item["direction"] == "increases_risk" for item in contributions)


def test_explain_matches_predict(client, valid_payload):
    explained = client.post("/api/v1/explain", json=valid_payload).json()
    predicted = client.post("/api/v1/predict", json=valid_payload).json()
    assert explained["default_probability"] == pytest.approx(predicted["default_probability"])
    assert explained["risk_decision"] == predicted["risk_decision"]


def test_explain_shap_is_additive_and_drives_risk_factors(make_client, auth_headers, high_risk_payload):
    client = make_client(explain_top_k=23)
    client.headers.update(auth_headers)
    data = client.post("/api/v1/explain", json=high_risk_payload).json()
    total = sum(item["contribution"] for item in data["contributions"])
    assert data["reference_probability"] + total == pytest.approx(data["default_probability"], abs=1e-4)
    top = data["contributions"][0]
    assert data["top_risk_factors"][0].startswith(f"{top['feature']} = ")
    assert "pp" in data["top_risk_factors"][0]


def test_explain_is_deterministic(client, high_risk_payload):
    first = client.post("/api/v1/explain", json=high_risk_payload).json()
    second = client.post("/api/v1/explain", json=high_risk_payload).json()
    assert first["contributions"] == second["contributions"]


def test_explain_substitution_mode(make_client, auth_headers, high_risk_payload):
    client = make_client(explain_method="reference_substitution")
    client.headers.update(auth_headers)
    data = client.post("/api/v1/explain", json=high_risk_payload).json()
    assert data["method"] == "reference_substitution"
    assert data["top_risk_factors"][0].startswith("Severe Delinquency")


def test_explain_falls_back_when_shap_fails(client, high_risk_payload, monkeypatch):
    from credit_risk.serving import scoring

    def _boom(*args, **kwargs):
        raise RuntimeError("shap unavailable")

    monkeypatch.setattr(scoring, "explain_against_reference", _boom)
    response = client.post("/api/v1/explain", json=high_risk_payload)
    assert response.status_code == 200
    assert response.json()["method"] == "reference_substitution"


def test_explain_does_not_write_inference_log(client, valid_payload):
    before = database.count_inference_logs()
    client.post("/api/v1/explain", json=valid_payload)
    assert database.count_inference_logs() == before


# --- Model info / reload ------------------------------------------------------


def test_model_info_describes_fallback_model(client, settings):
    data = client.get("/api/v1/model/info").json()
    assert data["model_name"] == settings.mlflow.model_name
    assert data["model_alias"] == settings.mlflow.model_alias
    assert data["source"] == "local_artifact"
    assert data["degraded"] is True
    assert data["model_type"] in {
        "LogisticRegression",
        "RandomForestClassifier",
        "XGBClassifier",
        "LGBMClassifier",
    }
    assert "PAY_0" in data["feature_names"]
    assert data["thresholds"] == {"review": 0.30, "decline": 0.60}


def test_model_info_503_without_model(client, monkeypatch):
    monkeypatch.setattr(client.app.state.model_manager, "_current", None)
    assert_error(client.get("/api/v1/model/info"), 503, "MODEL_UNAVAILABLE")


def test_reload_is_idempotent(client):
    first = client.post("/api/v1/model/reload")
    second = client.post("/api/v1/model/reload")
    assert first.status_code == second.status_code == 200
    assert second.json()["status"] == "reloaded"
    assert second.json()["previous_version"] == first.json()["model"]["model_version"]


def test_failed_reload_keeps_serving_previous_model(client, valid_payload, monkeypatch):
    manager = client.app.state.model_manager
    monkeypatch.setattr(manager, "_load_from_mlflow", lambda: None)
    monkeypatch.setattr(manager, "_load_from_local", lambda: None)
    response = client.post("/api/v1/model/reload")
    assert response.status_code == 200
    assert response.json()["status"] == "unchanged_on_failure"
    assert client.post("/api/v1/predict", json=valid_payload).status_code == 200


def test_reload_503_when_nothing_can_be_loaded(client, monkeypatch):
    manager = client.app.state.model_manager
    monkeypatch.setattr(manager, "_current", None)
    monkeypatch.setattr(manager, "_load_from_mlflow", lambda: None)
    monkeypatch.setattr(manager, "_load_from_local", lambda: None)
    assert_error(client.post("/api/v1/model/reload"), 503, "MODEL_UNAVAILABLE")


# --- Metrics ----------------------------------------------------------------


def test_metrics_expose_custom_series(client, valid_payload):
    client.post("/api/v1/predict", json=valid_payload)
    client.post("/api/v1/predict", json={})
    body = client.get("/metrics").text
    assert 'credit_api_requests_total{endpoint="/api/v1/predict",method="POST",status="200"}' in body
    assert 'credit_api_requests_total{endpoint="/api/v1/predict",method="POST",status="422"}' in body
    assert "credit_api_request_duration_seconds_bucket" in body
    assert "credit_prediction_requests_total" in body
    assert "credit_prediction_default_probability_bucket" in body
    assert (
        'credit_model_info{model_name="credit-risk-model",model_version="credit_model_v1",source="local_artifact"}'
        in body
    )
    assert "credit_model_loaded 1.0" in body
    assert "credit_model_degraded 1.0" in body
    assert "credit_customer_age_rolling_mean" in body
    assert "credit_applicant_score_distribution_bucket" in body


def test_model_inference_latency_is_observed_once_per_model_call(client, valid_payload, high_risk_payload):
    def inference_count() -> float:
        return REGISTRY.get_sample_value("credit_prediction_duration_seconds_count") or 0.0

    before = inference_count()
    assert client.post("/api/v1/predict", json=valid_payload).status_code == 200
    assert inference_count() == before + 1

    batch = {"applicants": [valid_payload, high_risk_payload]}
    assert client.post("/api/v1/predict/batch", json=batch).status_code == 200
    assert inference_count() == before + 2
    assert "credit_prediction_duration_seconds_bucket" in client.get("/metrics").text


def test_metrics_need_no_auth(anon_client):
    assert anon_client.get("/metrics").status_code == 200


# --- OpenAPI ----------------------------------------------------------------


def test_every_operation_documents_examples(anon_client):
    spec = anon_client.get("/openapi.json").json()
    for path, operations in spec["paths"].items():
        for method, operation in operations.items():
            body = operation.get("requestBody")
            if body:
                media = body["content"]["application/json"]
                assert "examples" in media or "example" in media, f"{method} {path} lacks request examples"
            ok = operation["responses"]["200"]
            content = next(iter(ok.get("content", {}).values()), {})
            schema_ref = content.get("schema", {}).get("$ref", "")
            schema = spec["components"]["schemas"].get(schema_ref.split("/")[-1], {})
            assert (
                "example" in content or "examples" in content or "examples" in schema
            ), f"{method} {path} lacks a 200 example"


def test_api_key_security_scheme_is_documented(anon_client):
    spec = anon_client.get("/openapi.json").json()
    assert spec["components"]["securitySchemes"]["ApiKeyAuth"] == {
        "type": "apiKey",
        "in": "header",
        "name": "X-API-Key",
        "description": spec["components"]["securitySchemes"]["ApiKeyAuth"]["description"],
    }
    assert spec["paths"]["/api/v1/predict"]["post"]["security"] == [{"ApiKeyAuth": []}]
    assert "security" not in spec["paths"]["/health/ready"]["get"]


def test_committed_openapi_document_is_up_to_date(anon_client, settings):
    import yaml

    committed = yaml.safe_load((settings.paths.project_root / "docs" / "openapi.yaml").read_text(encoding="utf-8"))
    assert committed == anon_client.app.openapi(), "Run `make openapi` to refresh docs/openapi.yaml"
