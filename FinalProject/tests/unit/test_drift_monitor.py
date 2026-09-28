from __future__ import annotations

import dataclasses
from collections.abc import Callable
from typing import Any

import pandas as pd
import pytest
from fastapi.testclient import TestClient
from prometheus_client import generate_latest

from credit_risk.config import Settings
from credit_risk.data.schema import ALL_FEATURES, REQUEST_ID_COLUMN
from drift_monitor.app import create_app
from drift_monitor.monitor import DriftMonitor


def _window(settings: Settings, model: Any, source: str, rows: int = 300) -> pd.DataFrame:
    path = settings.paths.normal_stream if source == "normal" else settings.paths.drifted_stream
    frame = pd.read_csv(path).drop(columns=[REQUEST_ID_COLUMN], errors="ignore")[ALL_FEATURES].head(rows)
    frame["probability"] = model.predict_proba(frame[list(model.feature_names_in_)])[:, 1]
    return frame


@pytest.fixture
def fast_settings(settings: Settings, tmp_path) -> Settings:
    drift = dataclasses.replace(settings.drift, reference_sample_size=2000, min_current_samples=50)
    paths = dataclasses.replace(settings.paths, reports_dir=tmp_path / "reports")
    return dataclasses.replace(settings, drift=drift, paths=paths)


@pytest.fixture
def make_monitor(fast_settings: Settings, champion_model: Any) -> Callable[..., DriftMonitor]:
    def _make(window: pd.DataFrame | None) -> DriftMonitor:
        return DriftMonitor(
            fast_settings,
            log_loader=lambda _cfg, limit: None if window is None else window.tail(limit),
            model_loader=lambda _cfg: (champion_model, "test-v1", "local_artifact"),
        )

    return _make


def _metric(name: str) -> float:
    for line in generate_latest().decode().splitlines():
        if line.startswith(name + " "):
            return float(line.split()[-1])
    raise AssertionError(f"metric {name} not exported")


def test_normal_traffic_is_not_drift(make_monitor, fast_settings, champion_model):
    monitor = make_monitor(_window(fast_settings, champion_model, "normal"))

    result = monitor.analyze()

    assert result["status"] == "success"
    assert result["is_drifted"] is False
    assert result["max_psi"] < 0.25
    assert result["prediction_psi"] < 0.25
    assert _metric("credit_drift_detected") == 0.0


def test_genz_campaign_is_drift(make_monitor, fast_settings, champion_model):
    monitor = make_monitor(_window(fast_settings, champion_model, "drifted"))

    result = monitor.analyze(save_report=True)

    assert result["is_drifted"] is True
    assert any(reason.startswith("psi_critical") and "AGE" in reason for reason in result["reasons"])
    assert result["psi"]["AGE"] >= 0.25
    assert _metric("credit_drift_detected") == 1.0
    assert _metric("credit_drift_max_psi") >= 0.25
    assert monitor.report_path(result["report"]) is not None


def test_insufficient_samples_and_database_down_are_skipped(make_monitor, fast_settings, champion_model):
    small = make_monitor(_window(fast_settings, champion_model, "normal", rows=10)).analyze()
    down = make_monitor(None).analyze()

    assert small == {**small, "status": "skipped", "reason": "insufficient_samples", "is_drifted": False}
    assert down["status"] == "skipped"
    assert down["reason"] == "database_unavailable"


def test_reference_without_model_skips_prediction_psi(fast_settings, champion_model):
    window = _window(fast_settings, champion_model, "normal")
    monitor = DriftMonitor(
        fast_settings,
        log_loader=lambda _cfg, limit: window.tail(limit),
        model_loader=lambda _cfg: (None, "none", "unavailable"),
    )

    result = monitor.analyze()

    assert result["status"] == "success"
    assert result["prediction_psi"] is None


def test_http_endpoints(make_monitor, fast_settings, champion_model):
    monitor = make_monitor(_window(fast_settings, champion_model, "drifted"))
    with TestClient(create_app(fast_settings, monitor=monitor, run_scheduler=False)) as client:
        health = client.get("/health")
        assert health.status_code == 200
        assert health.json()["reference_model_version"] == "test-v1"

        assert client.get("/drift/latest").status_code == 404
        analysis = client.post("/analyze", json={"window_size": 200, "save_report": True}).json()
        assert analysis["is_drifted"] is True
        assert analysis["current_samples"] == 200
        assert client.get("/drift/latest").json()["report"] == analysis["report"]

        reports = client.get("/reports").json()
        assert reports["count"] == 1
        report = client.get(reports["reports"][0]["url"])
        assert report.status_code == 200
        assert "text/html" in report.headers["content-type"]
        assert client.get("/reports/..%2Fsecrets.html").status_code == 404
        assert client.get("/reports/drift_report_20990101T000000Z.html").status_code == 404

        assert client.get("/reference").json()["samples"] == 2000
        assert client.post("/reference/refresh").json()["model_version"] == "test-v1"
        assert "credit_drift_share" in client.get("/metrics").text
        assert client.post("/analyze", json={"window_size": 1}).status_code == 422


def test_health_is_unhealthy_without_reference(fast_settings, tmp_path):
    missing = dataclasses.replace(fast_settings.paths, baseline_data=tmp_path / "missing.csv")
    cfg = dataclasses.replace(fast_settings, paths=missing)
    monitor = DriftMonitor(cfg, log_loader=lambda _cfg, _limit: None, model_loader=lambda _cfg: (None, "none", "x"))
    with TestClient(create_app(cfg, monitor=monitor, run_scheduler=False)) as client:
        response = client.get("/health")
    assert response.status_code == 503
    assert response.json()["status"] == "unhealthy"
