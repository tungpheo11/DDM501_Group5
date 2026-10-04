import json
import shutil
from unittest.mock import Mock

import pandas as pd
import pytest

from credit_risk.config import load_settings
from credit_risk.data.schema import ALL_FEATURES
from credit_risk.training.models import LGBMClassifier
from credit_risk.training.registry import describe_registry, log_model_run
from credit_risk.training.retrain import (
    load_champion_spec,
    load_combined_training_data,
    run_retraining_pipeline,
    trigger_hot_reload,
)
from credit_risk.training.train import run_training_pipeline

FAST_CANDIDATES = ["logistic_regression"] if LGBMClassifier is None else ["logistic_regression", "lightgbm"]


@pytest.fixture
def small_workspace(tmp_path, monkeypatch, settings):
    """Small copies of the datasets and the champion model in an isolated directory."""
    pd.read_csv(settings.paths.baseline_data).head(1500).to_csv(tmp_path / "baseline.csv", index=False)
    pd.read_csv(settings.paths.normal_stream).head(300).to_csv(tmp_path / "normal.csv", index=False)
    drifted = pd.read_csv(settings.paths.drifted_stream).head(600)
    drifted.to_csv(tmp_path / "drifted.csv", index=False)
    labels = pd.read_csv(settings.paths.ground_truth)
    labels[labels["request_id"].isin(drifted["request_id"])].to_csv(tmp_path / "labels.csv", index=False)
    models = tmp_path / "models"
    models.mkdir()
    shutil.copy(settings.paths.models_dir / "credit_model_v1.joblib", models / "credit_model_v1.joblib")

    monkeypatch.setenv("BASELINE_DATA_PATH", str(tmp_path / "baseline.csv"))
    monkeypatch.setenv("NORMAL_STREAM_PATH", str(tmp_path / "normal.csv"))
    monkeypatch.setenv("DRIFTED_STREAM_PATH", str(tmp_path / "drifted.csv"))
    monkeypatch.setenv("GROUND_TRUTH_PATH", str(tmp_path / "labels.csv"))
    monkeypatch.setenv("MODELS_DIR", str(models))
    monkeypatch.setenv("REPORTS_DIR", str(tmp_path / "reports"))
    return load_settings(env="test")


@pytest.fixture
def tracked_workspace(small_workspace, tmp_path, monkeypatch):
    """Same workspace with a throwaway SQLite MLflow tracking + registry store."""
    monkeypatch.setenv("MLFLOW_TRACKING_URI", f"sqlite:///{tmp_path / 'mlflow.db'}")
    monkeypatch.setenv("MLFLOW_LOCAL_STORE_DIR", str(tmp_path / "mlruns"))
    return load_settings(env="test")


def test_training_offline_writes_reports_and_respects_gate(small_workspace):
    champion_path = small_workspace.paths.models_dir / "credit_model_v1.joblib"
    before = champion_path.read_bytes()
    outcome = run_training_pipeline(small_workspace, n_trials=1, candidates=FAST_CANDIDATES, sync_readme=False)

    assert outcome.tracking_uri is None
    assert [c.name for c in outcome.candidates] == FAST_CANDIDATES
    assert outcome.gate.champion is not None, "local champion artifact must be used as the incumbent offline"
    report = json.loads(outcome.report_paths["json"].read_text())
    assert report["selected_model"] == outcome.selected.name
    assert {m["name"] for m in report["models"]} == set(FAST_CANDIDATES)
    for model in report["models"]:
        assert {"roc_auc", "pr_auc", "f1_score", "recall", "expected_loss"} <= set(model["holdout"])
        assert len(model["cv_fold_roc_auc"]) == small_workspace.training.cv_folds
    assert "| Model |" in outcome.report_paths["markdown"].read_text()
    assert (small_workspace.paths.reports_dir / "figures" / "roc_comparison.png").exists()
    assert (champion_path.read_bytes() != before) == outcome.gate.promote


def test_training_with_registry_registers_and_gates_idempotently(tracked_workspace):
    import mlflow

    first = run_training_pipeline(tracked_workspace, n_trials=1, candidates=FAST_CANDIDATES, sync_readme=False)
    assert first.tracking_uri.startswith("sqlite:")
    assert first.registered_version == "1" and first.champion_version == "1"
    assert first.gate.promote and first.gate.champion is None
    spec = json.loads((tracked_workspace.paths.models_dir / "model_spec.json").read_text())
    assert spec["candidate"] == first.selected.name

    runs = mlflow.search_runs(experiment_names=[tracked_workspace.mlflow.experiment_name])
    assert len(runs) >= 2 * len(FAST_CANDIDATES)
    assert set(runs["tags.run_type"]) == {"candidate", "hpo_trial"}
    candidate_runs = runs[runs["tags.run_type"] == "candidate"]
    assert candidate_runs["metrics.holdout_roc_auc"].notna().all()
    assert candidate_runs["tags.data_version"].notna().all()
    artifacts = {a.path for a in mlflow.MlflowClient().list_artifacts(first.selected.run_id, "plots")}
    assert {"plots/confusion_matrix.png", "plots/roc_curve.png", "plots/feature_importance.png"} <= artifacts

    second = run_training_pipeline(tracked_workspace, n_trials=1, candidates=FAST_CANDIDATES, sync_readme=False)
    assert second.registered_version == "2"
    assert not second.gate.promote, "an identical deterministic retrain must not replace the champion"
    registry = describe_registry(tracked_workspace)
    assert registry["aliases"]["champion"] == "1"
    assert registry["aliases"]["challenger"] == "2"


def test_combined_training_data_replays_baseline(small_workspace):
    features, target, drifted = load_combined_training_data(small_workspace)
    assert len(features) == 1500 + len(drifted)
    assert len(target) == len(features)
    assert "request_id" not in drifted.columns


def test_champion_spec_falls_back_to_config(small_workspace):
    candidate, params, source = load_champion_spec(small_workspace)
    assert candidate == "random_forest"
    assert params["n_estimators"] == small_workspace.training.challenger.params["n_estimators"]
    assert source == "configs/training.yaml"


def test_retraining_pipeline_offline(small_workspace):
    result = run_retraining_pipeline(small_workspace, reload_api=False)
    assert (small_workspace.paths.models_dir / "credit_model_v2.joblib").exists()
    assert result.gate is not None
    assert result.promoted == result.gate.promote
    assert result.challenger_loss >= 0
    assert result.challenger_metrics["roc_auc"] > 0.5


def test_retraining_reuses_champion_spec(small_workspace):
    spec = {"candidate": "logistic_regression", "params": {"C": 0.2}}
    (small_workspace.paths.models_dir / "model_spec.json").write_text(json.dumps(spec))
    result = run_retraining_pipeline(small_workspace, reload_api=False)
    assert result.candidate == "logistic_regression"
    assert result.challenger.named_steps["classifier"].C == 0.2


def test_registry_skips_when_tracking_unreachable(settings, champion_model):
    frame = pd.read_csv(settings.paths.normal_stream).head(5)
    result = log_model_run(
        champion_model, run_name="t", params={}, metrics={}, sample_input=frame[ALL_FEATURES], settings=settings
    )
    assert result is None


def test_hot_reload_unreachable_api_returns_false():
    assert trigger_hot_reload("http://127.0.0.1:9", timeout=0.2) is False


@pytest.mark.parametrize(
    ("body", "expected"),
    [
        ({"status": "reloaded", "model": {"model_version": "1", "degraded": False}}, True),
        ({"status": "reloaded", "model": {"model_version": "5", "degraded": False}}, False),
        ({"status": "reloaded", "model": {"model_version": "1", "degraded": True}}, False),
        ({"status": "unchanged", "model": {"model_version": "1", "degraded": False}}, False),
    ],
)
def test_hot_reload_verifies_expected_model_version(monkeypatch, body, expected):
    response = Mock(status_code=200)
    response.json.return_value = body
    monkeypatch.setattr("credit_risk.training.retrain.requests.post", lambda *args, **kwargs: response)

    assert trigger_hot_reload("http://api:8000", expected_version="1") is expected
