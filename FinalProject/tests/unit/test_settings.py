import pytest

from credit_risk.config import load_settings


def test_test_environment_is_hermetic(settings):
    assert settings.env == "test"
    assert settings.database.url == "sqlite://"
    assert settings.mlflow.tracking_uri == "http://127.0.0.1:9"


def test_paths_point_to_new_layout(settings):
    paths = settings.paths
    assert paths.baseline_data == paths.data_dir / "reference" / "train_baseline.csv"
    assert paths.normal_stream.parent == paths.data_dir / "processed"
    assert paths.baseline_data.exists()


def test_yaml_values_are_loaded(settings):
    assert settings.serving.review_threshold == pytest.approx(0.30)
    assert settings.serving.decline_threshold == pytest.approx(0.60)
    assert settings.training.baseline.params["n_estimators"] == 100
    assert settings.training.challenger.params["max_depth"] == 8
    assert "AGE" in settings.drift.key_features


def test_env_vars_override_yaml(monkeypatch):
    monkeypatch.setenv("REVIEW_THRESHOLD", "0.25")
    monkeypatch.setenv("MODEL_ALIAS", "challenger")
    monkeypatch.setenv("MLFLOW_TRACKING_URI", "http://mlflow.example:5000")
    cfg = load_settings(env="test")
    assert cfg.serving.review_threshold == pytest.approx(0.25)
    assert cfg.mlflow.model_alias == "challenger"
    assert cfg.mlflow.tracking_uri == "http://mlflow.example:5000"


def test_environment_overlays_differ(monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    local = load_settings(env="local")
    docker = load_settings(env="docker")
    assert "localhost:15434" in local.database.url
    assert "@postgres:5432/" in docker.database.url
    assert docker.mlflow.tracking_uri == "http://mlflow:5000"


def test_invalid_thresholds_are_rejected(monkeypatch):
    monkeypatch.setenv("REVIEW_THRESHOLD", "0.9")
    monkeypatch.setenv("DECLINE_THRESHOLD", "0.5")
    with pytest.raises(ValueError):
        load_settings(env="test")


def test_configure_mlflow_environment_does_not_override(monkeypatch, settings):
    from credit_risk.config import configure_mlflow_environment

    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "already-set")
    monkeypatch.delenv("MLFLOW_S3_ENDPOINT_URL", raising=False)
    configure_mlflow_environment(settings)
    import os

    assert os.environ["AWS_ACCESS_KEY_ID"] == "already-set"
    assert os.environ["MLFLOW_S3_ENDPOINT_URL"] == settings.mlflow.s3_endpoint_url


def test_serving_auth_defaults(settings):
    assert settings.serving.auth_enabled is True
    assert settings.serving.api_keys == ("test-api-key",)
    assert settings.serving.client_api_key == "test-api-key"
    assert settings.serving.batch_max_size == 500
    assert settings.serving.explain_reference["LIMIT_BAL"] == pytest.approx(100000.0)


def test_api_keys_env_overrides_and_trims(monkeypatch):
    monkeypatch.setenv("API_KEYS", " key-a , key-b ,, ")
    monkeypatch.setenv("API_AUTH_ENABLED", "false")
    cfg = load_settings(env="test")
    assert cfg.serving.api_keys == ("key-a", "key-b")
    assert cfg.serving.client_api_key == "key-a"
    assert cfg.serving.auth_enabled is False


def test_client_api_key_env_wins(monkeypatch):
    monkeypatch.setenv("API_KEY", "client-key")
    assert load_settings(env="test").serving.client_api_key == "client-key"


def test_log_format_selects_formatter(settings, monkeypatch):
    import logging

    from credit_risk.config import setup_logging
    from credit_risk.config.logging import JsonFormatter

    monkeypatch.setenv("LOG_FORMAT", "text")
    setup_logging(settings, force=True)
    assert not isinstance(logging.getLogger("credit_risk").handlers[0].formatter, JsonFormatter)
    monkeypatch.setenv("LOG_FORMAT", "json")
    setup_logging(settings, force=True)
    assert isinstance(logging.getLogger("credit_risk").handlers[0].formatter, JsonFormatter)


def test_setup_logging_is_idempotent(settings):
    import logging

    from credit_risk.config import setup_logging

    setup_logging(settings, force=True)
    setup_logging(settings)
    assert logging.getLogger("credit_risk").level == logging.getLevelName(settings.log_level)
