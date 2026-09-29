"""Request/response examples rendered in the OpenAPI document and Swagger UI."""

from __future__ import annotations

from typing import Any

LOW_RISK_CARDHOLDER: dict[str, Any] = {
    "LIMIT_BAL": 200000.0,
    "SEX": 2,
    "EDUCATION": 1,
    "MARRIAGE": 1,
    "AGE": 38,
    "PAY_0": -1,
    "PAY_2": -1,
    "PAY_3": -1,
    "PAY_4": -1,
    "PAY_5": -1,
    "PAY_6": -1,
    "BILL_AMT1": 12000.0,
    "BILL_AMT2": 11500.0,
    "BILL_AMT3": 11000.0,
    "BILL_AMT4": 10500.0,
    "BILL_AMT5": 10000.0,
    "BILL_AMT6": 9500.0,
    "PAY_AMT1": 12000.0,
    "PAY_AMT2": 11500.0,
    "PAY_AMT3": 11000.0,
    "PAY_AMT4": 10500.0,
    "PAY_AMT5": 10000.0,
    "PAY_AMT6": 9500.0,
}

HIGH_RISK_CARDHOLDER: dict[str, Any] = {
    "LIMIT_BAL": 20000.0,
    "SEX": 1,
    "EDUCATION": 2,
    "MARRIAGE": 2,
    "AGE": 23,
    "PAY_0": 2,
    "PAY_2": 2,
    "PAY_3": 2,
    "PAY_4": 2,
    "PAY_5": 2,
    "PAY_6": 2,
    "BILL_AMT1": 19500.0,
    "BILL_AMT2": 19800.0,
    "BILL_AMT3": 19900.0,
    "BILL_AMT4": 20000.0,
    "BILL_AMT5": 20100.0,
    "BILL_AMT6": 20200.0,
    "PAY_AMT1": 0.0,
    "PAY_AMT2": 0.0,
    "PAY_AMT3": 0.0,
    "PAY_AMT4": 0.0,
    "PAY_AMT5": 0.0,
    "PAY_AMT6": 0.0,
}

PREDICT_REQUEST_EXAMPLES: dict[str, Any] = {
    "low_risk": {
        "summary": "Low-risk cardholder",
        "description": "Pays in full every month, low utilization.",
        "value": LOW_RISK_CARDHOLDER,
    },
    "high_risk": {
        "summary": "High-risk cardholder",
        "description": "Two months late on every statement, card maxed out.",
        "value": HIGH_RISK_CARDHOLDER,
    },
}

BATCH_REQUEST_EXAMPLES: dict[str, Any] = {
    "two_cardholders": {
        "summary": "Two cardholders",
        "description": "Post-statement limit review of two accounts.",
        "value": {"cardholders": [LOW_RISK_CARDHOLDER, HIGH_RISK_CARDHOLDER]},
    },
    "deprecated_alias": {
        "summary": "Deprecated `applicants` field",
        "description": "Same request with the deprecated field name; returns the same result. Prefer `cardholders`.",
        "value": {"applicants": [LOW_RISK_CARDHOLDER, HIGH_RISK_CARDHOLDER]},
    },
}

PREDICTION_RESPONSE: dict[str, Any] = {
    "request_id": "req_4f1c2b7e9a0d4c3b8e2f6a1d0c9b8a7e",
    "default_prediction": 1,
    "default_probability": 0.7812,
    "credit_score": 420,
    "credit_tier": "HIGH_RISK",
    "risk_decision": "DECLINE",
    "recommended_limit_ntd": 0.0,
    "top_risk_factors": [
        "Severe Delinquency: PAY_0=2 indicates 2+ months payment default",
        "Excessive Credit Line Utilization: 97.5% of limit consumed",
        "Demographic Cohort: Young cardholder profile (23yo) with short account history",
    ],
    "policy_guardrails": {
        "age_verification": "PASS",
        "utilization_ceiling_check": "OVER_UTILIZED_WARNING",
        "delinquency_guardrail": "ELEVATED_DEFAULT_RISK",
    },
    "model_version": "3",
    "served_by": "mlflow_registry",
    "latency_ms": 11.4,
}

BATCH_RESPONSE: dict[str, Any] = {
    "request_id": "req_9b8a7e4f1c2b7e9a0d4c3b8e2f6a1d0c",
    "count": 2,
    "decision_summary": {"APPROVE": 1, "REVIEW": 0, "DECLINE": 1},
    "predictions": [
        {
            "index": 0,
            "request_id": "req_9b8a7e4f1c2b7e9a0d4c3b8e2f6a1d0c-0",
            "default_prediction": 0,
            "default_probability": 0.1215,
            "credit_score": 783,
            "credit_tier": "PRIME",
            "risk_decision": "APPROVE",
            "recommended_limit_ntd": 250000.0,
            "top_risk_factors": ["Repayment Discipline: Timely and structured monthly repayments"],
            "policy_guardrails": {
                "age_verification": "PASS",
                "utilization_ceiling_check": "ACCEPTABLE",
                "delinquency_guardrail": "CLEAR",
            },
        },
        {
            "index": 1,
            "request_id": "req_9b8a7e4f1c2b7e9a0d4c3b8e2f6a1d0c-1",
            "default_prediction": 1,
            "default_probability": 0.7812,
            "credit_score": 420,
            "credit_tier": "HIGH_RISK",
            "risk_decision": "DECLINE",
            "recommended_limit_ntd": 0.0,
            "top_risk_factors": ["Severe Delinquency: PAY_0=2 indicates 2+ months payment default"],
            "policy_guardrails": {
                "age_verification": "PASS",
                "utilization_ceiling_check": "OVER_UTILIZED_WARNING",
                "delinquency_guardrail": "ELEVATED_DEFAULT_RISK",
            },
        },
    ],
    "model_version": "3",
    "served_by": "mlflow_registry",
    "latency_ms": 14.9,
}

EXPLAIN_RESPONSE: dict[str, Any] = {
    **{key: value for key, value in PREDICTION_RESPONSE.items() if key != "latency_ms"},
    "default_prediction": 1,
    "default_probability": 0.993453,
    "credit_score": 304,
    "credit_tier": "HIGH_RISK",
    "risk_decision": "DECLINE",
    "recommended_limit_ntd": 0.0,
    "top_risk_factors": [
        "PAY_0 = 2 (repayment status last month) increases default risk by +14.0 pp",
        "LIMIT_BAL = 20,000 NTD (credit limit) increases default risk by +10.4 pp",
        "PAY_AMT1 = 0 NTD (amount paid 1 month(s) ago) increases default risk by +5.8 pp",
    ],
    "method": "shap_permutation",
    "reference_probability": 0.438187,
    "contributions": [
        {
            "feature": "PAY_0",
            "value": 2.0,
            "reference_value": 0.0,
            "contribution": 0.140278,
            "direction": "increases_risk",
        },
        {
            "feature": "LIMIT_BAL",
            "value": 20000.0,
            "reference_value": 100000.0,
            "contribution": 0.103797,
            "direction": "increases_risk",
        },
        {
            "feature": "PAY_AMT1",
            "value": 0.0,
            "reference_value": 10823.0,
            "contribution": 0.058425,
            "direction": "increases_risk",
        },
    ],
    "latency_ms": 29.4,
}

MODEL_INFO_RESPONSE: dict[str, Any] = {
    "model_name": "credit-risk-model",
    "model_alias": "champion",
    "model_version": "3",
    "source": "mlflow_registry",
    "uri": "models:/credit-risk-model@champion",
    "run_id": "a1b2c3d4e5f60718293a4b5c6d7e8f90",
    "model_type": "RandomForestClassifier",
    "loaded_at": "2026-09-28T09:15:02.123000Z",
    "degraded": False,
    "feature_names": ["LIMIT_BAL", "AGE", "BILL_AMT1", "PAY_0"],
    "thresholds": {"review": 0.3, "decline": 0.6},
}

RELOAD_RESPONSE: dict[str, Any] = {
    "status": "reloaded",
    "message": "Model loaded.",
    "previous_version": "2",
    "model": MODEL_INFO_RESPONSE,
}

READINESS_READY: dict[str, Any] = {
    "status": "ready",
    "reasons": [],
    "checks": {
        "model": {"status": "ok", "detail": "mlflow_registry version 3"},
        "mlflow": {"status": "ok", "detail": None},
        "database": {"status": "ok", "detail": None},
    },
}

READINESS_DEGRADED: dict[str, Any] = {
    "status": "degraded",
    "reasons": ["model_served_from_local_fallback", "mlflow_unreachable"],
    "checks": {
        "model": {"status": "degraded", "detail": "local_artifact version credit_model_v1"},
        "mlflow": {"status": "down", "detail": "tracking server unreachable"},
        "database": {"status": "ok", "detail": None},
    },
}

READINESS_NOT_READY: dict[str, Any] = {
    "status": "not_ready",
    "reasons": ["model_not_loaded", "mlflow_unreachable"],
    "checks": {
        "model": {"status": "down", "detail": "No model could be loaded from MLflow or the local fallback."},
        "mlflow": {"status": "down", "detail": "tracking server unreachable"},
        "database": {"status": "ok", "detail": None},
    },
}

ERROR_VALIDATION: dict[str, Any] = {
    "code": "VALIDATION_ERROR",
    "message": "Request validation failed.",
    "details": [
        {
            "field": "AGE",
            "message": "Input should be greater than or equal to 18",
            "type": "greater_than_equal",
            "constraint": {"ge": "18"},
        }
    ],
    "request_id": "req_4f1c2b7e9a0d4c3b8e2f6a1d0c9b8a7e",
}


def _error(code: str, message: str, details: Any = None) -> dict[str, Any]:
    return {"code": code, "message": message, "details": details, "request_id": "req_4f1c2b7e9a0d4c3b8e2f6a1d0c9b8a7e"}


ERROR_MISSING_KEY = _error("MISSING_API_KEY", "Missing X-API-Key header.")
ERROR_INVALID_KEY = _error("INVALID_API_KEY", "The provided API key is not valid.")
ERROR_BATCH_TOO_LARGE = _error(
    "BATCH_TOO_LARGE", "Batch contains 800 cardholders; the maximum is 500.", {"max_size": 500, "received": 800}
)
ERROR_MODEL_UNAVAILABLE = _error("MODEL_UNAVAILABLE", "No model is loaded; check GET /health/ready.")
ERROR_INTERNAL = _error("INTERNAL_ERROR", "Internal server error.")


def _error_content(example: dict[str, Any]) -> dict[str, Any]:
    return {"application/json": {"example": example}}


def error_responses(*statuses: int) -> dict[int | str, dict[str, Any]]:
    """OpenAPI ``responses`` entries for the given error statuses."""
    catalog: dict[int, tuple[str, dict[str, Any]]] = {
        401: ("API key missing", ERROR_MISSING_KEY),
        403: ("API key invalid", ERROR_INVALID_KEY),
        413: ("Batch larger than the configured maximum", ERROR_BATCH_TOO_LARGE),
        422: ("Payload failed validation (types, domain bounds, unknown fields)", ERROR_VALIDATION),
        500: ("Unexpected server error", ERROR_INTERNAL),
        503: ("No model loaded", ERROR_MODEL_UNAVAILABLE),
    }
    from credit_risk.serving.schemas import ErrorResponse

    return {
        status: {
            "model": ErrorResponse,
            "description": catalog[status][0],
            "content": _error_content(catalog[status][1]),
        }
        for status in statuses
    }
