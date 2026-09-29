"""Shared fixtures. Forces the hermetic ``test`` environment before any import of the package."""

from __future__ import annotations

import os

os.environ["APP_ENV"] = "test"
for _var in (
    "MLFLOW_TRACKING_URI",
    "MLFLOW_S3_ENDPOINT_URL",
    "DATABASE_URL",
    "API_URL",
    "API_KEYS",
    "API_KEY",
    "API_AUTH_ENABLED",
    "LOG_FORMAT",
    "PROMETHEUS_MULTIPROC_DIR",
    "MODEL_SYNC_DIR",
    "API_MASTER_PID",
):
    os.environ.pop(_var, None)

import dataclasses  # noqa: E402
from collections.abc import Callable, Iterator  # noqa: E402
from typing import Any  # noqa: E402

import joblib  # noqa: E402
import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from credit_risk.config import Settings, get_settings  # noqa: E402

TEST_API_KEY = "test-api-key"


@pytest.fixture(scope="session")
def settings() -> Settings:
    return get_settings()


@pytest.fixture(scope="session")
def champion_model(settings: Settings) -> Any:
    return joblib.load(settings.paths.models_dir / settings.serving.fallback_model_artifact)


@pytest.fixture
def auth_headers() -> dict[str, str]:
    return {"X-API-Key": TEST_API_KEY}


@pytest.fixture
def make_client(settings: Settings) -> Iterator[Callable[..., TestClient]]:
    """Factory building a fresh app; keyword arguments override ``settings.serving`` fields."""
    from credit_risk.serving.app import create_app

    clients: list[TestClient] = []

    def _make(**serving_overrides: Any) -> TestClient:
        cfg = settings
        if serving_overrides:
            cfg = dataclasses.replace(settings, serving=dataclasses.replace(settings.serving, **serving_overrides))
        test_client = TestClient(create_app(cfg))
        test_client.__enter__()
        clients.append(test_client)
        return test_client

    yield _make
    for test_client in clients:
        test_client.__exit__(None, None, None)


@pytest.fixture
def client(make_client: Callable[..., TestClient], auth_headers: dict[str, str]) -> TestClient:
    """Client for a fresh app that sends a valid API key by default."""
    test_client = make_client()
    test_client.headers.update(auth_headers)
    return test_client


@pytest.fixture
def anon_client(make_client: Callable[..., TestClient]) -> TestClient:
    """Client for a fresh app without credentials."""
    return make_client()


@pytest.fixture
def valid_payload() -> dict[str, float | int]:
    return {
        "LIMIT_BAL": 50000.0,
        "SEX": 2,
        "EDUCATION": 2,
        "MARRIAGE": 1,
        "AGE": 35,
        "PAY_0": 0,
        "PAY_2": 0,
        "PAY_3": 0,
        "PAY_4": 0,
        "PAY_5": 0,
        "PAY_6": 0,
        "BILL_AMT1": 10000.0,
        "BILL_AMT2": 10000.0,
        "BILL_AMT3": 10000.0,
        "BILL_AMT4": 10000.0,
        "BILL_AMT5": 10000.0,
        "BILL_AMT6": 10000.0,
        "PAY_AMT1": 2000.0,
        "PAY_AMT2": 2000.0,
        "PAY_AMT3": 2000.0,
        "PAY_AMT4": 2000.0,
        "PAY_AMT5": 2000.0,
        "PAY_AMT6": 2000.0,
    }


@pytest.fixture
def high_risk_payload(valid_payload: dict[str, float | int]) -> dict[str, float | int]:
    return {
        **valid_payload,
        "LIMIT_BAL": 20000.0,
        "AGE": 23,
        "PAY_0": 2,
        "PAY_2": 2,
        "PAY_3": 2,
        "PAY_4": 2,
        "PAY_5": 2,
        "PAY_6": 2,
        "BILL_AMT1": 19500.0,
        "PAY_AMT1": 0.0,
    }
