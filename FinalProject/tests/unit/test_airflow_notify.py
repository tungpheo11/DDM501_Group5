"""Tests for the Airflow DAG notification helper (webhook fallback path)."""

from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

NOTIFY_PATH = Path(__file__).resolve().parents[2] / "orchestration" / "airflow" / "utils" / "notify.py"


def _load_module() -> ModuleType:
    spec = importlib.util.spec_from_file_location("airflow_notify", NOTIFY_PATH)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class _Response:
    status_code = 200

    def raise_for_status(self) -> None:
        return None


@pytest.fixture()
def notify_module(monkeypatch: pytest.MonkeyPatch) -> tuple[ModuleType, list[dict[str, Any]]]:
    monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)
    monkeypatch.delenv("TELEGRAM_CHAT_ID", raising=False)
    module = _load_module()
    sent: list[dict[str, Any]] = []

    def fake_post(url: str, json: dict[str, Any], timeout: int) -> _Response:
        sent.append(json)
        return _Response()

    monkeypatch.setattr(module.requests, "post", fake_post)
    return module, sent


@pytest.mark.parametrize("status", ["firing", "resolved"])
def test_webhook_events_are_one_shot(notify_module: tuple[ModuleType, list[dict[str, Any]]], status: str) -> None:
    module, sent = notify_module

    channel = module.notify(
        "RetrainFailed",
        "[RETRAIN] failed",
        ["Run: manual__1"],
        status=status,
        severity="critical",
        labels={"dag_id": "model_retrain", "kind": "alert"},
    )

    assert channel == "webhook"
    [payload] = sent
    [alert] = payload["alerts"]
    assert payload["receiver"] == "airflow"
    assert alert["status"] == status
    assert alert["labels"]["kind"] == "event"
    assert alert["labels"]["dag_id"] == "model_retrain"
    assert alert["endsAt"] == alert["startsAt"]
