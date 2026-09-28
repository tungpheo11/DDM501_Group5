import json
import logging
from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest

from credit_risk.config import load_settings
from credit_risk.config.logging import REDACTED, JsonFormatter
from credit_risk.monitoring.metrics import DEFAULT_RISK_RATIO, MODEL_DEGRADED, MODEL_LOADED, RollingFeatureStats
from credit_risk.serving import database
from credit_risk.serving import model_loader as loader_module
from credit_risk.serving.model_loader import SOURCE_LOCAL, SOURCE_MLFLOW, ModelManager
from credit_risk.serving.readiness import ReadinessProbe
from credit_risk.serving.scoring import Contribution, default_probabilities
from credit_risk.serving.security import is_valid_api_key
from credit_risk.utils.network import is_service_reachable
from credit_risk.utils.request_context import request_id_var


def test_rolling_stats_window_is_bounded():
    stats = RollingFeatureStats(window=3)
    for prediction in (1, 1, 0, 0):
        stats.observe(prediction, age=30, limit_bal=1000.0, utilization=0.5, pay_0=0)
    assert len(stats.predictions) == 3
    assert DEFAULT_RISK_RATIO._value.get() == 1 / 3


# --- ModelManager -------------------------------------------------------------


def test_model_manager_uses_local_fallback(settings):
    manager = ModelManager(settings)
    outcome = manager.load_champion()
    assert outcome.success
    assert manager.is_loaded
    assert manager.source == SOURCE_LOCAL
    assert manager.current.degraded is True
    assert manager.version_label == "credit_model_v1"
    assert "PAY_0" in manager.current.feature_names
    assert MODEL_LOADED._value.get() == 1
    assert MODEL_DEGRADED._value.get() == 1


def test_model_manager_unavailable_when_no_artifact(tmp_path, monkeypatch):
    monkeypatch.setenv("MODELS_DIR", str(tmp_path))
    manager = ModelManager(load_settings(env="test"))
    outcome = manager.load_champion()
    assert not outcome.success
    assert not manager.is_loaded
    assert manager.source == "unavailable"
    assert "not found" in manager.last_error
    assert MODEL_LOADED._value.get() == 0


def test_failed_reload_keeps_previous_model(settings, monkeypatch):
    manager = ModelManager(settings)
    manager.load_champion()
    served = manager.current
    monkeypatch.setattr(manager, "_load_from_local", lambda: None)
    outcome = manager.load_champion()
    assert not outcome.success
    assert manager.current is served
    assert outcome.current is served


class _FakeClient:
    def __init__(self, tracking_uri):
        self.tracking_uri = tracking_uri

    def get_model_version_by_alias(self, name, alias):
        return SimpleNamespace(version=7, run_id="run-123")


def _patch_mlflow(monkeypatch, champion_model, *, load_error=None):
    import mlflow.sklearn
    import mlflow.tracking

    def fake_load(uri):
        if load_error:
            raise load_error
        return champion_model

    monkeypatch.setattr(loader_module, "is_service_reachable", lambda *_a, **_k: True)
    monkeypatch.setattr(mlflow.tracking, "MlflowClient", _FakeClient)
    monkeypatch.setattr(mlflow.sklearn, "load_model", fake_load)
    monkeypatch.setattr(mlflow, "set_tracking_uri", lambda uri: None)


def test_model_manager_prefers_mlflow_registry(settings, champion_model, monkeypatch):
    _patch_mlflow(monkeypatch, champion_model)
    manager = ModelManager(settings)
    manager.load_champion()
    current = manager.current
    assert current.source == SOURCE_MLFLOW
    assert current.degraded is False
    assert current.version == "7"
    assert current.run_id == "run-123"
    assert current.uri == f"models:/{settings.mlflow.model_name}@{settings.mlflow.model_alias}"
    assert MODEL_DEGRADED._value.get() == 0


def test_reload_never_downgrades_registry_model_to_local(settings, champion_model, monkeypatch):
    _patch_mlflow(monkeypatch, champion_model)
    manager = ModelManager(settings)
    manager.load_champion()
    registry_model = manager.current
    monkeypatch.setattr(loader_module, "is_service_reachable", lambda *_a, **_k: False)
    outcome = manager.load_champion()
    assert not outcome.success
    assert manager.current is registry_model
    assert "keeping registry model version 7" in outcome.message


def test_model_manager_falls_back_when_registry_load_fails(settings, champion_model, monkeypatch):
    _patch_mlflow(monkeypatch, champion_model, load_error=RuntimeError("s3 down"))
    manager = ModelManager(settings)
    manager.load_champion()
    assert manager.source == SOURCE_LOCAL


# --- Readiness ------------------------------------------------------------------


def test_readiness_ready_when_registry_model_and_dependencies_up(settings, champion_model, monkeypatch):
    _patch_mlflow(monkeypatch, champion_model)
    import credit_risk.serving.readiness as readiness_module

    monkeypatch.setattr(readiness_module, "is_service_reachable", lambda *_a, **_k: True)
    database.init_db("sqlite://")
    manager = ModelManager(settings)
    manager.load_champion()
    report = ReadinessProbe(settings, manager).evaluate()
    assert report.status == "ready"
    assert report.reasons == []
    assert report.http_status == 200


def test_readiness_caches_dependency_probes(settings, monkeypatch):
    import credit_risk.serving.readiness as readiness_module

    calls = []
    monkeypatch.setattr(readiness_module, "is_service_reachable", lambda *_a, **_k: calls.append(1) or False)
    probe = ReadinessProbe(settings, ModelManager(settings))
    probe.evaluate()
    probe.evaluate()
    assert len(calls) == 1
    probe.invalidate()
    probe.evaluate()
    assert len(calls) == 2


def test_readiness_not_ready_without_model(settings):
    report = ReadinessProbe(settings, ModelManager(settings)).evaluate()
    assert report.status == "not_ready"
    assert report.http_status == 503


# --- Database ---------------------------------------------------------------------


def test_database_init_failure_disables_logging():
    assert database.init_db("postgresql://u:p@127.0.0.1:9/db") is False
    assert database.is_connected() is False
    assert database.ping() is False
    assert database.save_inference_log("r", {}, 0, 0.1, "APPROVE", 1.0) is False
    assert database.save_inference_logs([{"request_id": "r"}]) == 0
    assert database.count_inference_logs() == 0


def test_database_sqlite_roundtrip():
    assert database.init_db("sqlite://") is True
    assert database.ping() is True
    assert database.save_inference_log("req_1", {"AGE": 30}, 1, 0.7, "DECLINE", 2.5, "v9") is True
    record = {"features": {"AGE": 40}, "prediction": 0, "probability": 0.1, "risk_decision": "APPROVE", "latency_ms": 1}
    written = database.save_inference_logs([{**record, "request_id": "b-0"}, {**record, "request_id": "b-1"}], "v9")
    assert written == 2
    assert database.count_inference_logs() == 3


def test_is_service_reachable_closed_port():
    assert is_service_reachable("http://127.0.0.1:9", timeout=0.2) is False


# --- Scoring helpers ------------------------------------------------------------


def test_default_probabilities_without_predict_proba():
    class HardClassifier:
        def predict(self, frame):
            return np.array([1, 0])

    probabilities = default_probabilities(HardClassifier(), pd.DataFrame({"x": [1, 2]}))
    assert probabilities.tolist() == [1.0, 0.0]


@pytest.mark.parametrize(("value", "direction"), [(0.2, "increases_risk"), (-0.2, "decreases_risk"), (0.0, "neutral")])
def test_contribution_direction(value, direction):
    assert Contribution("AGE", 30, 37, value).direction == direction


# --- Security -------------------------------------------------------------------


def test_is_valid_api_key():
    assert is_valid_api_key("b", ("a", "b"))
    assert not is_valid_api_key("c", ("a", "b"))
    assert not is_valid_api_key("anything", ())


# --- Structured logging -----------------------------------------------------------


def _record(**extra):
    record = logging.LogRecord("credit_risk.test", logging.INFO, __file__, 1, "hello %s", ("world",), None)
    for key, value in extra.items():
        setattr(record, key, value)
    return record


def test_json_formatter_emits_structured_line_with_request_id():
    token = request_id_var.set("req_test")
    try:
        entry = json.loads(JsonFormatter().format(_record(event="prediction", latency_ms=3.2)))
    finally:
        request_id_var.reset(token)
    assert entry["message"] == "hello world"
    assert entry["level"] == "INFO"
    assert entry["request_id"] == "req_test"
    assert entry["event"] == "prediction"
    assert entry["latency_ms"] == 3.2


def test_json_formatter_redacts_pii_fields():
    line = JsonFormatter().format(_record(AGE=44, features={"LIMIT_BAL": 90000, "note": "ok"}, payload=[1, 2]))
    entry = json.loads(line)
    assert entry["AGE"] == REDACTED
    assert entry["features"] == REDACTED
    assert entry["payload"] == REDACTED
    assert "90000" not in line


def test_json_formatter_redacts_nested_pii():
    entry = json.loads(JsonFormatter().format(_record(context={"LIMIT_BAL": 1, "decision": "APPROVE"})))
    assert entry["context"] == {"LIMIT_BAL": REDACTED, "decision": "APPROVE"}


def test_json_formatter_includes_exception():
    try:
        raise ValueError("bad")
    except ValueError:
        import sys

        record = logging.LogRecord("x", logging.ERROR, __file__, 1, "failed", None, sys.exc_info())
    assert "ValueError: bad" in json.loads(JsonFormatter().format(record))["exception"]
