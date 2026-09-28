import pandas as pd
import pytest

from credit_risk.config import load_settings
from credit_risk.data.schema import ALL_FEATURES, TARGET_COLUMN
from credit_risk.training.pipeline import build_model_pipeline
from credit_risk.training.registry import (
    PREVIOUS_CHAMPION_ALIAS,
    describe_registry,
    get_alias_version,
    get_registry_client,
    load_model_by_alias,
    log_model_run,
    promote_model_version,
    rollback_champion,
)
from credit_risk.training.tracking import local_store_uri, resolve_tracking_uri


@pytest.fixture
def registry_settings(tmp_path, monkeypatch):
    monkeypatch.setenv("MLFLOW_TRACKING_URI", f"sqlite:///{tmp_path / 'mlflow.db'}")
    monkeypatch.setenv("MLFLOW_LOCAL_STORE_DIR", str(tmp_path / "mlruns"))
    monkeypatch.setenv("MODEL_NAME", "registry-test-model")
    return load_settings(env="test")


@pytest.fixture(scope="module")
def tiny_model(settings):
    frame = pd.read_csv(settings.paths.baseline_data).head(300)
    model = build_model_pipeline({"C": 0.5}, random_state=0, model_name="logistic_regression")
    model.fit(frame[ALL_FEATURES], frame[TARGET_COLUMN])
    return model, frame[ALL_FEATURES]


def _register(model, sample, settings, promote=True):
    return log_model_run(
        model,
        run_name="registry-test",
        params={"C": 0.5},
        metrics={"roc_auc": 0.7},
        sample_input=sample,
        register=True,
        promote=promote,
        settings=settings,
    )


def test_promote_and_rollback_cycle(registry_settings, tiny_model):
    model, sample = tiny_model
    first = _register(model, sample, registry_settings)
    second = _register(model, sample, registry_settings)
    assert (first.registered_version, second.registered_version) == ("1", "2")
    assert second.promoted

    client = get_registry_client(registry_settings)
    name = registry_settings.mlflow.model_name
    assert get_alias_version(client, name, "champion") == "2"
    assert get_alias_version(client, name, PREVIOUS_CHAMPION_ALIAS) == "1"

    change = rollback_champion(settings=registry_settings)
    assert (change.champion_version, change.previous_champion_version) == ("1", "2")
    assert get_alias_version(client, name, PREVIOUS_CHAMPION_ALIAS) == "2"
    assert client.get_model_version(name, "2").tags["rolled_back"] == "true"

    change = promote_model_version("2", settings=registry_settings, reason="re-promote")
    assert change.action == "promote" and change.previous_champion_version == "1"
    assert client.get_model_version(name, "2").tags["promotion_reason"] == "re-promote"

    rollback_champion(settings=registry_settings, to_version="1")
    info = describe_registry(registry_settings)
    assert info["aliases"]["champion"] == "1"
    assert [v["version"] for v in info["versions"]] == ["1", "2"]


def test_registered_model_is_loadable_with_signature(registry_settings, tiny_model):
    model, sample = tiny_model
    _register(model, sample, registry_settings)
    loaded = load_model_by_alias(settings=registry_settings)
    assert loaded is not None
    assert loaded.predict_proba(sample.head(3)).shape == (3, 2)
    assert load_model_by_alias("does-not-exist", settings=registry_settings) is None


def test_challenger_only_registration_does_not_touch_champion(registry_settings, tiny_model):
    model, sample = tiny_model
    _register(model, sample, registry_settings, promote=True)
    result = _register(model, sample, registry_settings, promote=False)
    assert not result.promoted
    aliases = describe_registry(registry_settings)["aliases"]
    assert aliases == {"champion": "1", "challenger": "2"}


def test_rollback_without_target_fails(registry_settings, tiny_model):
    model, sample = tiny_model
    _register(model, sample, registry_settings)
    with pytest.raises(RuntimeError, match="No rollback target"):
        rollback_champion(settings=registry_settings)


def test_registry_unreachable_is_reported(settings):
    assert describe_registry(settings) == {"reachable": False}
    with pytest.raises(RuntimeError):
        promote_model_version("1", settings=settings)
    with pytest.raises(RuntimeError):
        rollback_champion(settings=settings)


def test_local_fallback_store(tmp_path, monkeypatch):
    monkeypatch.setenv("MLFLOW_LOCAL_FALLBACK", "true")
    monkeypatch.setenv("MLFLOW_LOCAL_STORE_DIR", str(tmp_path / "store"))
    cfg = load_settings(env="test")
    uri = resolve_tracking_uri(cfg)
    assert uri == local_store_uri(cfg)
    assert uri.startswith("sqlite:///") and uri.endswith("store/mlflow.db")
