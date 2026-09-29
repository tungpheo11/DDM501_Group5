"""Champion model loading: MLflow registry first, local artifact fallback (degraded mode).

The served model is an immutable :class:`LoadedModel` snapshot swapped atomically
under a lock, so in-flight requests keep scoring with the snapshot they started
with and a failed reload never drops a model that is already serving.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import joblib

from credit_risk.config import Settings, configure_mlflow_environment, get_logger, get_settings
from credit_risk.monitoring.metrics import MODEL_RELOADS, set_model_unavailable, set_served_model
from credit_risk.serving.model_sync import ModelGenerationSync
from credit_risk.utils.network import is_service_reachable

logger = get_logger(__name__)

SOURCE_MLFLOW = "mlflow_registry"
SOURCE_LOCAL = "local_artifact"
SOURCE_NONE = "unavailable"


@dataclass(frozen=True)
class LoadedModel:
    """A model ready to score plus the metadata describing where it came from."""

    model: Any
    source: str
    uri: str
    version: str
    loaded_at: datetime
    run_id: str | None = None
    feature_names: tuple[str, ...] = field(default_factory=tuple)

    @property
    def degraded(self) -> bool:
        """True when serving the local fallback instead of the registry champion."""
        return self.source != SOURCE_MLFLOW

    @property
    def model_type(self) -> str:
        """Class name of the estimator (last step for sklearn pipelines)."""
        steps = getattr(self.model, "steps", None)
        estimator = steps[-1][1] if steps else self.model
        return type(estimator).__name__


@dataclass(frozen=True)
class ReloadOutcome:
    """Result of one (re)load attempt."""

    success: bool
    previous: LoadedModel | None
    current: LoadedModel | None
    message: str


def _feature_names(model: Any) -> tuple[str, ...]:
    names = getattr(model, "feature_names_in_", None)
    return tuple(str(name) for name in names) if names is not None else ()


class ModelManager:
    """Owns the currently served model snapshot."""

    def __init__(self, settings: Settings | None = None, sync: ModelGenerationSync | None = None) -> None:
        self._settings = settings or get_settings()
        self._sync = sync
        self._current: LoadedModel | None = None
        self._lock = threading.Lock()
        self.last_error: str | None = None

    @property
    def current(self) -> LoadedModel | None:
        """Snapshot to score with; read it once per request."""
        return self._current

    @property
    def model(self) -> Any | None:
        """The served estimator, or None."""
        current = self._current
        return current.model if current else None

    @property
    def is_loaded(self) -> bool:
        """Whether a model is available for scoring."""
        return self._current is not None

    @property
    def source(self) -> str:
        """``mlflow_registry``, ``local_artifact`` or ``unavailable``."""
        current = self._current
        return current.source if current else SOURCE_NONE

    @property
    def version_label(self) -> str:
        """Version stored with each inference log."""
        current = self._current
        return current.version if current else "none"

    def load_champion(self, *, broadcast: bool = False) -> ReloadOutcome:
        """Load ``models:/<name>@<alias>`` from MLflow, else the local fallback artifact.

        On failure the previously served model (if any) stays in place.

        Args:
            broadcast: After a successful load, publish a new generation marker so the
                other workers reload too (only for operator-requested reloads).
        """
        with self._lock:
            previous = self._current
            loaded = self._load_from_mlflow()
            if loaded is None and previous is not None and not previous.degraded:
                # Never downgrade a registry champion to the (older) local artifact
                # just because MLflow is briefly unavailable.
                MODEL_RELOADS.labels(result="failure").inc()
                message = f"MLflow unavailable; keeping registry model version {previous.version}."
                logger.warning(message, extra={"event": "model_reload_kept_registry", "error": self.last_error})
                return ReloadOutcome(False, previous, previous, message)
            if loaded is None:
                loaded = self._load_from_local()
            if loaded is None:
                MODEL_RELOADS.labels(result="failure").inc()
                if previous is None:
                    set_model_unavailable()
                    message = "No model could be loaded from MLflow or the local fallback."
                else:
                    message = "Reload failed; keeping the previously served model."
                logger.error(message, extra={"event": "model_load_failed", "error": self.last_error})
                return ReloadOutcome(False, previous, previous, message)

            self._current = loaded
            self.last_error = None
            MODEL_RELOADS.labels(result="success").inc()
            set_served_model(self._settings.mlflow.model_name, loaded.version, loaded.source, degraded=loaded.degraded)
            logger.info(
                "Model loaded",
                extra={
                    "event": "model_loaded",
                    "model_source": loaded.source,
                    "model_version": loaded.version,
                    "degraded": loaded.degraded,
                },
            )
            if broadcast and self._sync is not None:
                try:
                    self._sync.publish(loaded.version)
                except OSError as exc:  # This worker already serves the new model; keep the reload successful.
                    logger.error(
                        "Could not publish model generation: %s", exc, extra={"event": "model_generation_failed"}
                    )
            return ReloadOutcome(True, previous, loaded, "Model loaded.")

    def _load_from_mlflow(self) -> LoadedModel | None:
        cfg = self._settings
        registry_uri = f"models:/{cfg.mlflow.model_name}@{cfg.mlflow.model_alias}"
        tracking_uri = cfg.mlflow.tracking_uri
        if not is_service_reachable(tracking_uri, timeout=cfg.serving.mlflow_probe_timeout_seconds):
            self.last_error = f"MLflow tracking server {tracking_uri} is unreachable"
            logger.warning("MLflow unreachable; falling back to local artifact", extra={"event": "mlflow_unreachable"})
            return None
        try:
            import mlflow
            import mlflow.sklearn
            from mlflow.tracking import MlflowClient

            configure_mlflow_environment(cfg)
            mlflow.set_tracking_uri(tracking_uri)
            model_version = MlflowClient(tracking_uri=tracking_uri).get_model_version_by_alias(
                cfg.mlflow.model_name, cfg.mlflow.model_alias
            )
            model = mlflow.sklearn.load_model(registry_uri)
        except Exception as exc:  # Registry/artifact store failures of any kind fall back to local.
            self.last_error = f"MLflow load failed: {type(exc).__name__}"
            logger.warning("Could not load model from MLflow (%s); falling back to local artifact.", exc)
            return None
        return LoadedModel(
            model=model,
            source=SOURCE_MLFLOW,
            uri=registry_uri,
            version=str(model_version.version),
            loaded_at=datetime.now(UTC),
            run_id=model_version.run_id,
            feature_names=_feature_names(model),
        )

    def _load_from_local(self) -> LoadedModel | None:
        local_path: Path = self._settings.paths.models_dir / self._settings.serving.fallback_model_artifact
        if not local_path.exists():
            self.last_error = f"Local artifact {local_path.name} not found"
            return None
        try:
            model = joblib.load(local_path)
        except Exception as exc:  # Corrupt or incompatible pickle.
            self.last_error = f"Local artifact load failed: {type(exc).__name__}"
            logger.error("Failed to load local model %s: %s", local_path, exc)
            return None
        return LoadedModel(
            model=model,
            source=SOURCE_LOCAL,
            uri=f"local:{local_path.name}",
            version=local_path.stem,
            loaded_at=datetime.now(UTC),
            feature_names=_feature_names(model),
        )
