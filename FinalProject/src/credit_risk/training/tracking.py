"""MLflow tracking bootstrap and data-lineage logging."""

from __future__ import annotations

import json
import warnings
from pathlib import Path
from typing import Any

import pandas as pd

from credit_risk.config import Settings, configure_mlflow_environment, get_logger, get_settings
from credit_risk.data.schema import TARGET_COLUMN
from credit_risk.utils.network import is_service_reachable

logger = get_logger(__name__)


def local_store_uri(settings: Settings) -> str:
    """SQLite tracking/registry URI of the local fallback store."""
    store = settings.mlflow.local_store_dir or settings.paths.project_root / "mlruns"
    store.mkdir(parents=True, exist_ok=True)
    return f"sqlite:///{(store / 'mlflow.db').resolve()}"


def resolve_tracking_uri(settings: Settings | None = None) -> str | None:
    """Tracking URI to use, or ``None`` when MLflow logging must be skipped.

    A reachable (or non-HTTP) configured URI wins; otherwise the local SQLite
    store is used when ``mlflow.local_fallback`` is enabled.
    """
    cfg = settings or get_settings()
    uri = cfg.mlflow.tracking_uri
    if not uri.startswith("http") or is_service_reachable(uri):
        return uri
    if cfg.mlflow.local_fallback:
        fallback = local_store_uri(cfg)
        logger.warning("MLflow server %s is unreachable; logging to local store %s", uri, fallback)
        return fallback
    logger.warning("MLflow tracking server %s is unreachable; skipping MLflow logging.", uri)
    return None


def init_mlflow(settings: Settings | None = None) -> str | None:
    """Point MLflow at the resolved tracking URI and select the experiment.

    Returns:
        The active tracking URI, or ``None`` when tracking is unavailable.
    """
    cfg = settings or get_settings()
    uri = resolve_tracking_uri(cfg)
    if uri is None:
        return None

    import mlflow
    from mlflow.tracking import MlflowClient

    configure_mlflow_environment(cfg)
    mlflow.set_tracking_uri(uri)
    if uri.startswith("sqlite:"):
        mlflow.set_registry_uri(uri)
        client = MlflowClient(tracking_uri=uri)
        if client.get_experiment_by_name(cfg.mlflow.experiment_name) is None:
            store = cfg.mlflow.local_store_dir or cfg.paths.project_root / "mlruns"
            client.create_experiment(
                cfg.mlflow.experiment_name, artifact_location=(store / "artifacts").resolve().as_uri()
            )
    mlflow.set_experiment(cfg.mlflow.experiment_name)
    return uri


def lineage_tags(manifest: dict[str, Any], used_files: list[str]) -> dict[str, str]:
    """MLflow tags linking a run to the dataset snapshot: fingerprint and per-file hashes."""
    tags = {"data_version": str(manifest.get("fingerprint", "unknown"))}
    by_path = {entry["path"]: entry for entry in manifest.get("files", [])}
    for relative in used_files:
        entry = by_path.get(relative)
        if entry:
            tags[f"data.{relative}.sha256"] = entry["sha256"]
            tags[f"data.{relative}.rows"] = str(entry["rows"])
    return tags


def log_lineage(manifest: dict[str, Any], datasets: dict[str, tuple[pd.DataFrame, Path, str]]) -> None:
    """Log the manifest artifact and MLflow dataset inputs to the active run.

    Args:
        manifest: parsed ``data/manifest.json``.
        datasets: ``name -> (frame, source_path, context)``; ``context`` is e.g. ``training``.
    """
    import mlflow
    from mlflow.data.pandas_dataset import from_pandas

    mlflow.log_dict(manifest, "data/manifest.json")
    with warnings.catch_warnings():
        warnings.filterwarnings("ignore", message=".*dataset source can be interpreted in multiple ways.*")
        warnings.filterwarnings("ignore", message=".*Inferred schema contains integer column.*")
        for name, (frame, source, context) in datasets.items():
            targets = TARGET_COLUMN if TARGET_COLUMN in frame.columns else None
            dataset = from_pandas(frame, source=str(source), name=name, targets=targets)
            mlflow.log_input(dataset, context=context)


def log_json(payload: dict[str, Any], artifact_file: str) -> None:
    """Log a JSON-serialisable mapping as a run artifact (non-JSON values are stringified)."""
    import mlflow

    mlflow.log_dict(json.loads(json.dumps(payload, default=str)), artifact_file)
