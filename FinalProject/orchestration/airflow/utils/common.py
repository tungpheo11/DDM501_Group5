"""Shared settings for the credit-risk DAGs (all overridable through the environment)."""

from __future__ import annotations

import os
from datetime import datetime, timedelta
from typing import Any

import requests


def _env_url(name: str, default: str) -> str:
    return os.getenv(name, default).rstrip("/")


API_URL = _env_url("API_URL", "http://api:8000")
API_KEY = os.getenv("API_KEY", "")
DRIFT_MONITOR_URL = _env_url("DRIFT_MONITOR_URL", "http://drift-monitor:8085")
MLFLOW_URL = _env_url("MLFLOW_TRACKING_URI", "http://mlflow:5000")
PROMETHEUS_URL = _env_url("PROMETHEUS_URL", "http://prometheus:9090")
ALERTMANAGER_URL = _env_url("ALERTMANAGER_URL", "http://alertmanager:9093")
MLFLOW_PUBLIC_URL = _env_url("MLFLOW_PUBLIC_URL", "http://localhost:15040")
AIRFLOW_PUBLIC_URL = _env_url("AIRFLOW_PUBLIC_URL", "http://localhost:18080")
DRIFT_MONITOR_PUBLIC_URL = _env_url("DRIFT_MONITOR_PUBLIC_URL", "http://localhost:18085")

# Interpreter with the project dependencies (see orchestration/airflow/Dockerfile).
CREDIT_PYTHON = os.getenv("CREDIT_PYTHON", "/opt/credit-venv/bin/python")

DRIFT_WINDOW_SIZE = int(os.getenv("DRIFT_WINDOW_SIZE", "500"))
DRIFT_MONITORING_SCHEDULE = os.getenv("DRIFT_MONITORING_SCHEDULE", "*/30 * * * *")
HEALTH_CHECK_SCHEDULE = os.getenv("HEALTH_CHECK_SCHEDULE", "*/5 * * * *")
RETRAIN_COOLDOWN_MINUTES = int(os.getenv("RETRAIN_COOLDOWN_MINUTES", "60"))
RETRAIN_MIN_ROC_AUC = float(os.getenv("RETRAIN_MIN_ROC_AUC", "0.70"))
HTTP_TIMEOUT_SECONDS = float(os.getenv("HTTP_TIMEOUT_SECONDS", "10"))

START_DATE = datetime(2026, 1, 1)

DEFAULT_ARGS: dict[str, Any] = {
    "owner": "mlops",
    "depends_on_past": False,
    "retries": 1,
    "retry_delay": timedelta(seconds=30),
}


def api_headers() -> dict[str, str]:
    """``X-API-Key`` header for the scoring API (empty when no key is configured)."""
    return {"X-API-Key": API_KEY} if API_KEY else {}


def http_json(method: str, url: str, *, timeout: float = HTTP_TIMEOUT_SECONDS, **kwargs: Any) -> dict[str, Any]:
    """Call ``url`` and return the decoded JSON body; raise on HTTP errors."""
    response = requests.request(method, url, timeout=timeout, **kwargs)
    response.raise_for_status()
    body = response.json()
    return body if isinstance(body, dict) else {"items": body}
