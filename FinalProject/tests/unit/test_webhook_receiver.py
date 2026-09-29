"""Tests for the internal Alertmanager webhook receiver."""

from __future__ import annotations

import importlib.util
import json
import threading
from collections.abc import Iterator
from http.server import ThreadingHTTPServer
from pathlib import Path
from types import ModuleType
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import pytest

RECEIVER_PATH = Path(__file__).resolve().parents[2] / "monitoring" / "alertmanager" / "webhook_receiver.py"


def _load_module() -> ModuleType:
    spec = importlib.util.spec_from_file_location("webhook_receiver", RECEIVER_PATH)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture()
def base_url() -> Iterator[str]:
    module = _load_module()
    server = ThreadingHTTPServer(("127.0.0.1", 0), module.make_handler(module.AlertStore()))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_address[1]}"
    finally:
        server.shutdown()
        server.server_close()


def _payload(status: str) -> dict:
    return {
        "version": "4",
        "receiver": "webhook",
        "status": status,
        "groupLabels": {"alertname": "APIDown"},
        "alerts": [
            {
                "status": status,
                "fingerprint": "abc123",
                "labels": {"alertname": "APIDown", "severity": "critical"},
                "annotations": {"summary": "Scoring API is down"},
                "startsAt": "2026-01-01T00:00:00Z",
                "endsAt": "0001-01-01T00:00:00Z",
            }
        ],
    }


def _post(url: str, body: object) -> int:
    request = Request(url, data=json.dumps(body).encode(), headers={"Content-Type": "application/json"})
    with urlopen(request, timeout=5) as response:  # noqa: S310 - local test server
        return response.status


def _get(url: str) -> object:
    with urlopen(url, timeout=5) as response:  # noqa: S310 - local test server
        return json.loads(response.read())


def test_alert_fire_then_resolve_is_tracked(base_url: str) -> None:
    assert _post(f"{base_url}/alerts", _payload("firing")) == 200
    assert _post(f"{base_url}/alerts", _payload("resolved")) == 200

    notifications = _get(f"{base_url}/alerts?alertname=APIDown")
    assert [n["status"] for n in notifications] == ["resolved", "firing"]

    [state] = _get(f"{base_url}/alerts/state")
    assert state["alertname"] == "APIDown"
    assert state["fired"] is True
    assert state["resolved"] is True


def test_one_shot_events_are_logged_but_not_tracked_as_alert_state(base_url: str) -> None:
    event = {
        "version": "4",
        "receiver": "airflow",
        "status": "firing",
        "groupLabels": {"alertname": "RetrainFailed"},
        "alerts": [
            {
                "status": "firing",
                "labels": {"alertname": "RetrainFailed", "severity": "critical", "source": "airflow", "kind": "event"},
                "annotations": {"summary": "model_retrain failed"},
                "startsAt": "2026-01-01T00:00:00Z",
                "endsAt": "2026-01-01T00:00:00Z",
            }
        ],
    }
    assert _post(f"{base_url}/alerts", _payload("firing")) == 200
    assert _post(f"{base_url}/alerts", event) == 200

    [logged] = _get(f"{base_url}/alerts?alertname=RetrainFailed")
    assert logged["receiver"] == "airflow"

    assert [s["alertname"] for s in _get(f"{base_url}/alerts/state")] == ["APIDown"]


def test_rejects_invalid_payload(base_url: str) -> None:
    with pytest.raises(HTTPError) as excinfo:
        _post(f"{base_url}/alerts", {"alerts": "not-a-list"})
    assert excinfo.value.code == 400


def test_health_and_unknown_path(base_url: str) -> None:
    assert _get(f"{base_url}/health") == {"status": "healthy"}
    with pytest.raises(HTTPError) as excinfo:
        _get(f"{base_url}/nope")
    assert excinfo.value.code == 404
