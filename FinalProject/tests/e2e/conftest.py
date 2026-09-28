"""Fixtures for end-to-end tests against the running Docker Compose stack (``make up``).

Endpoints and credentials come from ``.env`` (or ``.env.example``); ``E2E_*`` variables override them. The root
conftest strips ``API_URL``/``API_KEY`` to keep unit tests hermetic, hence the dedicated prefix. Every test is skipped
when the API is not reachable, so ``pytest tests/e2e`` is safe on a machine without the stack.
"""

from __future__ import annotations

import os
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest
import requests

PROJECT_ROOT = Path(__file__).resolve().parents[2]
TIMEOUT = 10


def _read_env_file() -> dict[str, str]:
    for name in (".env", ".env.example"):
        path = PROJECT_ROOT / name
        if path.is_file():
            values: dict[str, str] = {}
            for line in path.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    key, _, value = line.partition("=")
                    values[key.strip()] = value.strip()
            return values
    return {}


@dataclass(frozen=True)
class Stack:
    api_url: str
    api_key: str
    drift_url: str
    prometheus_url: str
    alertmanager_url: str
    webhook_url: str
    grafana_url: str
    grafana_auth: tuple[str, str]
    mlflow_url: str
    airflow_url: str
    airflow_auth: tuple[str, str]

    def get(self, url: str, **kwargs: Any) -> requests.Response:
        kwargs.setdefault("timeout", TIMEOUT)
        return requests.get(url, **kwargs)

    def post(self, url: str, **kwargs: Any) -> requests.Response:
        kwargs.setdefault("timeout", TIMEOUT)
        return requests.post(url, **kwargs)


def build_stack() -> Stack:
    env = _read_env_file()

    def setting(name: str, default: str) -> str:
        return os.environ.get(f"E2E_{name}") or env.get(name) or default

    def local(port_var: str, default_port: str) -> str:
        return f"http://localhost:{setting(port_var, default_port)}"

    return Stack(
        api_url=os.environ.get("E2E_API_URL", local("API_PORT", "18020")),
        api_key=os.environ.get("E2E_API_KEY") or env.get("API_KEYS", "").split(",")[0].strip(),
        drift_url=os.environ.get("E2E_DRIFT_URL", local("DRIFT_MONITOR_PORT", "18085")),
        prometheus_url=os.environ.get("E2E_PROMETHEUS_URL", local("PROMETHEUS_PORT", "19090")),
        alertmanager_url=os.environ.get("E2E_ALERTMANAGER_URL", local("ALERTMANAGER_PORT", "19093")),
        webhook_url=os.environ.get("E2E_WEBHOOK_URL", local("ALERT_WEBHOOK_PORT", "19095")),
        grafana_url=os.environ.get("E2E_GRAFANA_URL", local("GRAFANA_PORT", "13000")),
        grafana_auth=(setting("GRAFANA_ADMIN_USER", "admin"), setting("GRAFANA_ADMIN_PASSWORD", "admin")),
        mlflow_url=os.environ.get("E2E_MLFLOW_URL", local("MLFLOW_PORT", "15040")),
        airflow_url=os.environ.get("E2E_AIRFLOW_URL", local("AIRFLOW_PORT", "18080")),
        airflow_auth=(setting("AIRFLOW_ADMIN_USER", "admin"), setting("AIRFLOW_ADMIN_PASSWORD", "admin")),
    )


@pytest.fixture(scope="session")
def stack() -> Stack:
    target = build_stack()
    try:
        requests.get(f"{target.api_url}/health/live", timeout=3).raise_for_status()
    except requests.RequestException as exc:
        pytest.skip(f"Compose stack not reachable at {target.api_url} ({exc.__class__.__name__}); run `make up`")
    if not target.api_key:
        pytest.skip("No API key: set API_KEYS in .env or E2E_API_KEY")
    return target


def _service_up(url: str) -> bool:
    try:
        return requests.get(url, timeout=3).status_code < 500
    except requests.RequestException:
        return False


@pytest.fixture
def require(stack: Stack) -> Callable[[str], None]:
    """``require(url)`` skips the test when an optional service (profile not started) is down."""

    def _require(url: str) -> None:
        if not _service_up(url):
            pytest.skip(f"service not reachable: {url}")

    return _require


@pytest.fixture
def auth(stack: Stack) -> dict[str, str]:
    return {"X-API-Key": stack.api_key}


@pytest.fixture
def low_risk_applicant() -> dict[str, float]:
    return {
        "LIMIT_BAL": 200000.0,
        "SEX": 2,
        "EDUCATION": 1,
        "MARRIAGE": 2,
        "AGE": 38,
        **dict.fromkeys(("PAY_0", "PAY_2", "PAY_3", "PAY_4", "PAY_5", "PAY_6"), 0),
        **{f"BILL_AMT{i}": 15000.0 - 1000.0 * i for i in range(1, 7)},
        **{f"PAY_AMT{i}": 5000.0 for i in range(1, 7)},
    }


@pytest.fixture
def high_risk_applicant() -> dict[str, float]:
    return {
        "LIMIT_BAL": 20000.0,
        "SEX": 1,
        "EDUCATION": 2,
        "MARRIAGE": 1,
        "AGE": 23,
        **dict.fromkeys(("PAY_0", "PAY_2", "PAY_3", "PAY_4", "PAY_5", "PAY_6"), 2),
        **{f"BILL_AMT{i}": 19500.0 + 100.0 * i for i in range(1, 7)},
        **{f"PAY_AMT{i}": 0.0 for i in range(1, 7)},
    }
