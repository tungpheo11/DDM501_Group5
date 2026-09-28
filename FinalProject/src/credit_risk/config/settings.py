"""Layered application settings.

Precedence (lowest to highest):

1. Defaults defined in this module.
2. Domain files ``configs/training.yaml``, ``configs/serving.yaml``, ``configs/drift.yaml``.
3. Environment overlay ``configs/environments/<APP_ENV>.yaml`` (``local`` | ``docker`` | ``test``).
4. Process environment variables (names are kept backward compatible with ``.env.example``).
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

DEFAULT_ENV = "local"
PROJECT_ROOT_ENV_VAR = "CREDIT_RISK_HOME"


def _default_project_root() -> Path:
    override = os.getenv(PROJECT_ROOT_ENV_VAR)
    if override:
        return Path(override).resolve()
    # src/credit_risk/config/settings.py -> project root is three levels above the package.
    return Path(__file__).resolve().parents[3]


def _load_yaml(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    with path.open("r", encoding="utf-8") as handle:
        content = yaml.safe_load(handle) or {}
    if not isinstance(content, dict):
        raise ValueError(f"Configuration file {path} must contain a mapping at top level.")
    return content


def _env(name: str, default: str) -> str:
    value = os.getenv(name)
    return value if value not in (None, "") else default


@dataclass(frozen=True)
class PathSettings:
    """Filesystem locations used by the pipeline."""

    project_root: Path
    configs_dir: Path
    data_dir: Path
    raw_dir: Path
    processed_dir: Path
    reference_dir: Path
    models_dir: Path
    reports_dir: Path
    raw_data: Path
    baseline_data: Path
    normal_stream: Path
    drifted_stream: Path
    ground_truth: Path
    data_manifest: Path

    def ensure_output_dirs(self) -> None:
        """Create directories that the pipeline writes into."""
        for directory in (self.models_dir, self.reports_dir, self.processed_dir, self.reference_dir):
            directory.mkdir(parents=True, exist_ok=True)


@dataclass(frozen=True)
class MlflowSettings:
    """MLflow tracking server and model registry settings."""

    tracking_uri: str
    s3_endpoint_url: str
    experiment_name: str
    model_name: str
    model_alias: str
    local_fallback: bool = False
    local_store_dir: Path | None = None


@dataclass(frozen=True)
class DatabaseSettings:
    """Inference-log database settings."""

    url: str


@dataclass(frozen=True)
class ServingSettings:
    """Online scoring service settings."""

    review_threshold: float
    decline_threshold: float
    rolling_window: int
    fallback_model_artifact: str
    mlflow_probe_timeout_seconds: float
    api_url: str
    auth_enabled: bool = True
    api_keys: tuple[str, ...] = ()
    client_api_key: str = ""
    batch_max_size: int = 500
    readiness_cache_seconds: float = 10.0
    explain_top_k: int = 5
    explain_reference: dict[str, float] = field(default_factory=dict)
    explain_method: str = "shap"
    explain_shap_max_evals: int = 240
    explain_seed: int = 42
    loss_given_default: float = 0.45


def _split_keys(raw: str) -> tuple[str, ...]:
    return tuple(key.strip() for key in raw.split(",") if key.strip())


def _as_bool(raw: str) -> bool:
    return raw.strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class ModelSpec:
    """Hyperparameters and registry metadata for one model variant."""

    run_name: str
    artifact_name: str
    model_type: str
    params: dict[str, Any] = field(default_factory=dict)
    strategy: str | None = None


@dataclass(frozen=True)
class PromotionSettings:
    """Champion/challenger gate thresholds (see ``credit_risk.evaluation.model_validation``)."""

    min_roc_auc: float = 0.70
    max_roc_auc_drop: float = 0.005
    min_loss_improvement: float = 0.0


@dataclass(frozen=True)
class TrainingSettings:
    """Training and champion/challenger evaluation settings."""

    random_state: int
    test_size: float
    baseline: ModelSpec
    challenger: ModelSpec
    cost_false_negative: float
    cost_false_positive: float
    cv_folds: int = 5
    decision_threshold: float = 0.5
    candidates: tuple[str, ...] = ("logistic_regression", "random_forest", "xgboost", "lightgbm")
    n_trials: int = 20
    tuning_timeout_seconds: float | None = None
    selection_metric: str = "roc_auc"
    champion_artifact_name: str = "credit_model_v1.joblib"
    promotion: PromotionSettings = field(default_factory=PromotionSettings)


@dataclass(frozen=True)
class DriftSettings:
    """Drift detection settings."""

    num_buckets: int
    moderate_threshold: float
    critical_threshold: float
    key_features: tuple[str, ...]
    min_current_samples: int
    db_query_limit: int
    report_html: str
    summary_json: str
    drift_share_threshold: float = 0.5
    reference_sample_size: int = 5000
    window_size: int = 500
    analysis_interval_seconds: float = 60.0
    max_saved_reports: int = 20


@dataclass(frozen=True)
class Settings:
    """Top-level settings object; obtain it through :func:`get_settings`."""

    env: str
    log_level: str
    logging_config: Path
    paths: PathSettings
    mlflow: MlflowSettings
    database: DatabaseSettings
    serving: ServingSettings
    training: TrainingSettings
    drift: DriftSettings


def _build_paths(root: Path) -> PathSettings:
    data_dir = root / "data"
    raw_dir = data_dir / "raw"
    processed_dir = data_dir / "processed"
    reference_dir = data_dir / "reference"
    return PathSettings(
        project_root=root,
        configs_dir=root / "configs",
        data_dir=data_dir,
        raw_dir=raw_dir,
        processed_dir=processed_dir,
        reference_dir=reference_dir,
        models_dir=Path(_env("MODELS_DIR", str(root / "models"))),
        reports_dir=Path(_env("REPORTS_DIR", str(root / "reports"))),
        raw_data=Path(_env("RAW_DATA_PATH", str(raw_dir / "credit_default.csv"))),
        baseline_data=Path(_env("BASELINE_DATA_PATH", str(reference_dir / "train_baseline.csv"))),
        normal_stream=Path(_env("NORMAL_STREAM_PATH", str(processed_dir / "stream_normal.csv"))),
        drifted_stream=Path(_env("DRIFTED_STREAM_PATH", str(processed_dir / "stream_drifted.csv"))),
        ground_truth=Path(_env("GROUND_TRUTH_PATH", str(processed_dir / "ground_truth_feedback.csv"))),
        data_manifest=data_dir / "manifest.json",
    )


def _build_database(overlay: dict[str, Any]) -> DatabaseSettings:
    explicit_url = os.getenv("DATABASE_URL") or overlay.get("url")
    if explicit_url:
        return DatabaseSettings(url=str(explicit_url))
    user = _env("POSTGRES_USER", "mlops")
    password = _env("POSTGRES_PASSWORD", "mlopspass")
    database = _env("POSTGRES_DB", "credit_mlops_db")
    host = _env("POSTGRES_HOST", str(overlay.get("host", "localhost")))
    port = _env("POSTGRES_PORT", str(overlay.get("port", 15434)))
    return DatabaseSettings(url=f"postgresql://{user}:{password}@{host}:{port}/{database}")


def _build_model_spec(raw: dict[str, Any], fallback: ModelSpec) -> ModelSpec:
    return ModelSpec(
        run_name=str(raw.get("run_name", fallback.run_name)),
        artifact_name=str(raw.get("artifact_name", fallback.artifact_name)),
        model_type=str(raw.get("model_type", fallback.model_type)),
        params=dict(raw.get("params", fallback.params)),
        strategy=raw.get("strategy", fallback.strategy),
    )


_DEFAULT_BASELINE = ModelSpec(
    run_name="baseline-rf-v1.0",
    artifact_name="credit_model_v1.joblib",
    model_type="RandomForestClassifier",
    params={"n_estimators": 100, "max_depth": 6, "class_weight": "balanced"},
)
_DEFAULT_CHALLENGER = ModelSpec(
    run_name="retrain-rf-v2.0-challenger",
    artifact_name="credit_model_v2.joblib",
    model_type="RandomForestClassifier-V2",
    params={"n_estimators": 150, "max_depth": 8, "min_samples_split": 8, "class_weight": "balanced"},
    strategy="Replay-15k-baseline-plus-5k-feedback",
)


def load_settings(env: str | None = None, project_root: Path | None = None) -> Settings:
    """Build a fresh :class:`Settings` instance without caching."""
    app_env = env or _env("APP_ENV", DEFAULT_ENV)
    root = project_root or _default_project_root()
    configs_dir = root / "configs"

    training_raw = _load_yaml(configs_dir / "training.yaml")
    serving_raw = _load_yaml(configs_dir / "serving.yaml")
    drift_raw = _load_yaml(configs_dir / "drift.yaml")
    overlay = _load_yaml(configs_dir / "environments" / f"{app_env}.yaml")
    mlflow_overlay: dict[str, Any] = overlay.get("mlflow", {}) or {}
    database_overlay: dict[str, Any] = overlay.get("database", {}) or {}
    serving_overlay: dict[str, Any] = overlay.get("serving", {}) or {}

    thresholds = serving_raw.get("thresholds", {}) or {}
    auth_raw: dict[str, Any] = serving_raw.get("auth", {}) or {}
    explain_raw: dict[str, Any] = serving_raw.get("explain", {}) or {}
    overlay_keys = ",".join(str(key) for key in (serving_overlay.get("api_keys") or []))
    api_keys = _split_keys(_env("API_KEYS", overlay_keys))
    serving = ServingSettings(
        review_threshold=float(_env("REVIEW_THRESHOLD", str(thresholds.get("review", 0.30)))),
        decline_threshold=float(_env("DECLINE_THRESHOLD", str(thresholds.get("decline", 0.60)))),
        rolling_window=int(serving_raw.get("rolling_window", 200)),
        fallback_model_artifact=str(serving_raw.get("fallback_model_artifact", "credit_model_v1.joblib")),
        mlflow_probe_timeout_seconds=float(serving_raw.get("mlflow_probe_timeout_seconds", 0.5)),
        api_url=_env("API_URL", str(serving_overlay.get("api_url", "http://localhost:18020"))),
        auth_enabled=_as_bool(_env("API_AUTH_ENABLED", str(auth_raw.get("enabled", True)))),
        api_keys=api_keys,
        client_api_key=_env("API_KEY", api_keys[0] if api_keys else ""),
        batch_max_size=int(serving_raw.get("batch_max_size", 500)),
        readiness_cache_seconds=float(serving_raw.get("readiness_cache_seconds", 10.0)),
        explain_top_k=int(explain_raw.get("top_k", 5)),
        explain_reference={str(k): float(v) for k, v in (explain_raw.get("reference_profile") or {}).items()},
        explain_method=str(explain_raw.get("method", "shap")),
        explain_shap_max_evals=int(explain_raw.get("shap_max_evals", 240)),
        explain_seed=int(explain_raw.get("seed", 42)),
        loss_given_default=float((serving_raw.get("business", {}) or {}).get("loss_given_default", 0.45)),
    )
    if serving.explain_method not in ("shap", "reference_substitution"):
        raise ValueError("serving.explain.method must be 'shap' or 'reference_substitution'.")
    if serving.review_threshold > serving.decline_threshold:
        raise ValueError("REVIEW_THRESHOLD must be lower than or equal to DECLINE_THRESHOLD.")

    mlflow_settings = MlflowSettings(
        tracking_uri=_env("MLFLOW_TRACKING_URI", str(mlflow_overlay.get("tracking_uri", "http://localhost:15040"))),
        s3_endpoint_url=_env(
            "MLFLOW_S3_ENDPOINT_URL", str(mlflow_overlay.get("s3_endpoint_url", "http://localhost:19040"))
        ),
        experiment_name=_env("EXPERIMENT_NAME", "credit-default-risk-scoring"),
        model_name=_env("MODEL_NAME", "credit-risk-model"),
        model_alias=_env("MODEL_ALIAS", "champion"),
        local_fallback=_as_bool(_env("MLFLOW_LOCAL_FALLBACK", str(mlflow_overlay.get("local_fallback", False)))),
        local_store_dir=Path(_env("MLFLOW_LOCAL_STORE_DIR", str(root / "mlruns"))),
    )

    cost_raw = training_raw.get("business_cost", {}) or {}
    tuning_raw: dict[str, Any] = training_raw.get("tuning", {}) or {}
    promotion_raw: dict[str, Any] = training_raw.get("promotion", {}) or {}
    timeout_raw = _env("OPTUNA_TIMEOUT_SECONDS", str(tuning_raw.get("timeout_seconds") or ""))
    training = TrainingSettings(
        random_state=int(training_raw.get("random_state", 42)),
        test_size=float((training_raw.get("split", {}) or {}).get("test_size", 0.2)),
        baseline=_build_model_spec(training_raw.get("baseline", {}) or {}, _DEFAULT_BASELINE),
        challenger=_build_model_spec(training_raw.get("challenger", {}) or {}, _DEFAULT_CHALLENGER),
        cost_false_negative=float(cost_raw.get("false_negative", 10.0)),
        cost_false_positive=float(cost_raw.get("false_positive", 1.0)),
        cv_folds=int(tuning_raw.get("cv_folds", 5)),
        decision_threshold=float(training_raw.get("decision_threshold", 0.5)),
        candidates=tuple(training_raw.get("candidates", TrainingSettings.candidates)),
        n_trials=int(_env("OPTUNA_N_TRIALS", str(tuning_raw.get("n_trials", 20)))),
        tuning_timeout_seconds=float(timeout_raw) if timeout_raw else None,
        selection_metric=str(tuning_raw.get("metric", "roc_auc")),
        champion_artifact_name=str(training_raw.get("champion_artifact_name", "credit_model_v1.joblib")),
        promotion=PromotionSettings(
            min_roc_auc=float(promotion_raw.get("min_roc_auc", 0.70)),
            max_roc_auc_drop=float(promotion_raw.get("max_roc_auc_drop", 0.005)),
            min_loss_improvement=float(promotion_raw.get("min_loss_improvement", 0.0)),
        ),
    )

    psi_raw = drift_raw.get("psi", {}) or {}
    evidently_raw: dict[str, Any] = drift_raw.get("evidently", {}) or {}
    service_raw: dict[str, Any] = drift_raw.get("service", {}) or {}
    drift = DriftSettings(
        num_buckets=int(psi_raw.get("num_buckets", 10)),
        moderate_threshold=float(psi_raw.get("moderate_threshold", 0.10)),
        critical_threshold=float(psi_raw.get("critical_threshold", 0.25)),
        key_features=tuple(drift_raw.get("key_features", ["AGE", "LIMIT_BAL", "PAY_0", "BILL_AMT1"])),
        min_current_samples=int(drift_raw.get("min_current_samples", 50)),
        db_query_limit=int(drift_raw.get("db_query_limit", 5000)),
        report_html=str(drift_raw.get("report_html", "drift_report.html")),
        summary_json=str(drift_raw.get("summary_json", "drift_summary.json")),
        drift_share_threshold=float(evidently_raw.get("drift_share_threshold", 0.5)),
        reference_sample_size=int(service_raw.get("reference_sample_size", 5000)),
        window_size=int(_env("DRIFT_WINDOW_SIZE", str(service_raw.get("window_size", 500)))),
        analysis_interval_seconds=float(
            _env("DRIFT_ANALYSIS_INTERVAL_SECONDS", str(service_raw.get("analysis_interval_seconds", 60)))
        ),
        max_saved_reports=int(service_raw.get("max_saved_reports", 20)),
    )

    return Settings(
        env=app_env,
        log_level=_env("LOG_LEVEL", "INFO").upper(),
        logging_config=Path(_env("LOGGING_CONFIG", str(configs_dir / "logging.yaml"))),
        paths=_build_paths(root),
        mlflow=mlflow_settings,
        database=_build_database(database_overlay),
        serving=serving,
        training=training,
        drift=drift,
    )


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return the process-wide cached settings."""
    return load_settings()


def reset_settings_cache() -> None:
    """Drop cached settings so the next :func:`get_settings` call re-reads config and env."""
    get_settings.cache_clear()


def configure_mlflow_environment(settings: Settings | None = None) -> None:
    """Export the S3/MinIO variables MLflow's artifact client reads from the environment.

    Existing values are never overwritten. The MinIO fallback credentials are the
    documented local-development defaults from ``.env.example``; production must
    inject real values through the environment.
    """
    cfg = settings or get_settings()
    os.environ.setdefault("AWS_ACCESS_KEY_ID", _env("MINIO_ROOT_USER", "minioadmin"))
    os.environ.setdefault("AWS_SECRET_ACCESS_KEY", _env("MINIO_ROOT_PASSWORD", "miniopassword"))
    os.environ.setdefault("MLFLOW_S3_ENDPOINT_URL", cfg.mlflow.s3_endpoint_url)
