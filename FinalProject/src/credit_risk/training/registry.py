"""MLflow tracking and model-registry helpers (promote / rollback reusable from Airflow).

Alias convention on the registered model ``MODEL_NAME``:

* ``@champion`` (``MODEL_ALIAS``) — version served by the API;
* ``@previous_champion`` — version demoted by the last promotion (rollback target);
* ``@challenger`` — latest candidate that went through the gate.
"""

from __future__ import annotations

import warnings
from dataclasses import dataclass
from typing import Any

import pandas as pd

from credit_risk.config import Settings, get_logger, get_settings
from credit_risk.training.tracking import init_mlflow

logger = get_logger(__name__)

PREVIOUS_CHAMPION_ALIAS = "previous_champion"
CHALLENGER_ALIAS = "challenger"


@dataclass(frozen=True)
class RegistryResult:
    """Outcome of logging a model run to MLflow."""

    run_id: str
    model_uri: str
    registered_version: str | None
    promoted: bool


@dataclass(frozen=True)
class AliasChange:
    """Champion alias move performed by :func:`promote_model_version` or :func:`rollback_champion`."""

    model_name: str
    champion_version: str
    previous_champion_version: str | None
    action: str


def get_registry_client(settings: Settings | None = None) -> Any | None:
    """``MlflowClient`` bound to the resolved tracking/registry URI, or ``None`` if unavailable."""
    uri = init_mlflow(settings)
    if uri is None:
        return None
    from mlflow.tracking import MlflowClient

    return MlflowClient(tracking_uri=uri, registry_uri=uri if uri.startswith("sqlite:") else None)


def get_alias_version(client: Any, model_name: str, alias: str) -> str | None:
    """Version currently holding ``alias`` (``None`` if the model or alias does not exist)."""
    from mlflow.exceptions import MlflowException

    try:
        return str(client.get_model_version_by_alias(model_name, alias).version)
    except MlflowException:
        return None


def promote_model_version(
    version: str,
    *,
    settings: Settings | None = None,
    client: Any | None = None,
    reason: str = "",
) -> AliasChange:
    """Move ``@champion`` to ``version``; the demoted version keeps ``@previous_champion``.

    Raises:
        RuntimeError: when the registry is unreachable.
    """
    cfg = settings or get_settings()
    registry = client or get_registry_client(cfg)
    if registry is None:
        raise RuntimeError("MLflow registry is unreachable; cannot promote.")
    name, alias = cfg.mlflow.model_name, cfg.mlflow.model_alias

    current = get_alias_version(registry, name, alias)
    if current is not None and current != str(version):
        registry.set_registered_model_alias(name, PREVIOUS_CHAMPION_ALIAS, current)
    registry.set_registered_model_alias(name, alias, str(version))
    registry.set_model_version_tag(name, str(version), "promotion_reason", reason or "manual promotion")
    logger.info("Promoted %s version %s to @%s (previous: %s)", name, version, alias, current)
    return AliasChange(name, str(version), current, "promote")


def rollback_champion(
    *,
    settings: Settings | None = None,
    client: Any | None = None,
    to_version: str | None = None,
) -> AliasChange:
    """Point ``@champion`` back to ``to_version`` (default: ``@previous_champion``).

    The version being rolled back becomes ``@previous_champion`` so a second
    rollback restores it.

    Raises:
        RuntimeError: when the registry is unreachable or there is no rollback target.
    """
    cfg = settings or get_settings()
    registry = client or get_registry_client(cfg)
    if registry is None:
        raise RuntimeError("MLflow registry is unreachable; cannot roll back.")
    name, alias = cfg.mlflow.model_name, cfg.mlflow.model_alias

    target = str(to_version) if to_version is not None else get_alias_version(registry, name, PREVIOUS_CHAMPION_ALIAS)
    if target is None:
        raise RuntimeError(f"No rollback target: '{name}' has no @{PREVIOUS_CHAMPION_ALIAS} alias.")
    current = get_alias_version(registry, name, alias)
    if current is not None and current != target:
        registry.set_registered_model_alias(name, PREVIOUS_CHAMPION_ALIAS, current)
        registry.set_model_version_tag(name, current, "rolled_back", "true")
    registry.set_registered_model_alias(name, alias, target)
    logger.warning("Rolled back %s @%s from version %s to %s", name, alias, current, target)
    return AliasChange(name, target, current, "rollback")


def bootstrap_champion(settings: Settings | None = None, client: Any | None = None) -> AliasChange | None:
    """Register the local champion artifact as ``@champion`` when the registry has none.

    Lets a freshly started stack serve from the registry (not the degraded local
    fallback) before the first ``make train``. No-op when ``@champion`` exists.

    Returns:
        The alias change, or ``None`` when a champion was already registered.

    Raises:
        RuntimeError: when the registry is unreachable or the local artifact is missing.
    """
    import joblib

    from credit_risk.data.schema import ALL_FEATURES

    cfg = settings or get_settings()
    registry = client or get_registry_client(cfg)
    if registry is None:
        raise RuntimeError("MLflow registry is unreachable; cannot bootstrap.")
    existing = get_alias_version(registry, cfg.mlflow.model_name, cfg.mlflow.model_alias)
    if existing is not None:
        logger.info("Registry already has %s@%s (version %s).", cfg.mlflow.model_name, cfg.mlflow.model_alias, existing)
        return None

    artifact = cfg.paths.models_dir / cfg.training.champion_artifact_name
    if not artifact.exists():
        raise RuntimeError(f"Local champion artifact {artifact} not found; run `make train` first.")
    model = joblib.load(artifact)
    sample = pd.read_csv(cfg.paths.baseline_data, nrows=50)[ALL_FEATURES]
    result = log_model_run(
        model,
        run_name="bootstrap-local-champion",
        params={"source": "local_artifact", "artifact": artifact.name},
        metrics={},
        sample_input=sample,
        register=True,
        promote=True,
        settings=cfg,
        tags={"run_type": "bootstrap"},
    )
    if result is None or result.registered_version is None:
        raise RuntimeError("Bootstrap could not register the local champion artifact.")
    logger.info("Bootstrapped %s@%s from %s", cfg.mlflow.model_name, cfg.mlflow.model_alias, artifact.name)
    return AliasChange(cfg.mlflow.model_name, result.registered_version, None, "bootstrap")


def load_model_by_alias(alias: str | None = None, settings: Settings | None = None) -> Any | None:
    """Load ``models:/<name>@<alias>`` as a scikit-learn model, or ``None`` if unavailable."""
    cfg = settings or get_settings()
    client = get_registry_client(cfg)
    if client is None:
        return None
    alias = alias or cfg.mlflow.model_alias
    if get_alias_version(client, cfg.mlflow.model_name, alias) is None:
        return None
    import mlflow.sklearn

    return mlflow.sklearn.load_model(f"models:/{cfg.mlflow.model_name}@{alias}")


def describe_registry(settings: Settings | None = None) -> dict[str, Any]:
    """Versions and aliases of the registered model (for CLI/Airflow status checks)."""
    cfg = settings or get_settings()
    client = get_registry_client(cfg)
    if client is None:
        return {"reachable": False}
    from mlflow.exceptions import MlflowException

    try:
        model = client.get_registered_model(cfg.mlflow.model_name)
    except MlflowException:
        return {"reachable": True, "model_name": cfg.mlflow.model_name, "versions": [], "aliases": {}}
    versions = client.search_model_versions(f"name='{cfg.mlflow.model_name}'")
    return {
        "reachable": True,
        "model_name": cfg.mlflow.model_name,
        "aliases": {alias: str(version) for alias, version in (model.aliases or {}).items()},
        "versions": sorted(
            ({"version": str(v.version), "run_id": v.run_id, "tags": dict(v.tags or {})} for v in versions),
            key=lambda v: int(v["version"]),
        ),
    }


def log_model_run(
    model: Any,
    *,
    run_name: str,
    params: dict[str, Any],
    metrics: dict[str, float],
    sample_input: pd.DataFrame,
    register: bool = True,
    promote: bool = True,
    settings: Settings | None = None,
    tags: dict[str, str] | None = None,
) -> RegistryResult | None:
    """Log params/metrics/model to MLflow, optionally register and move ``@champion``.

    Returns ``None`` (after logging a warning) when tracking is unavailable, so
    offline training still produces the local artifact.
    """
    cfg = settings or get_settings()
    try:
        if init_mlflow(cfg) is None:
            return None
        import mlflow

        with mlflow.start_run(run_name=run_name) as run:
            if tags:
                mlflow.set_tags(tags)
            mlflow.log_params(params)
            mlflow.log_metrics(metrics)
            info = log_sklearn_model(model, sample_input, register=register, settings=cfg)
            version = info.get("version")
            promoted = False
            client = get_registry_client(cfg) if register and version is not None else None
            if client is not None and version is not None:
                client.set_registered_model_alias(cfg.mlflow.model_name, CHALLENGER_ALIAS, version)
                if promote:
                    promote_model_version(version, settings=cfg, client=client, reason=run_name)
                    promoted = True
            return RegistryResult(
                run_id=run.info.run_id, model_uri=info["model_uri"], registered_version=version, promoted=promoted
            )
    except Exception as exc:  # MLflow raises many unrelated exception types for connectivity issues.
        logger.warning("Could not log to MLflow (%s). Local artifact is kept.", exc)
        return None


def log_sklearn_model(
    model: Any, sample_input: pd.DataFrame, *, register: bool, settings: Settings | None = None
) -> dict[str, Any]:
    """Log ``model`` with signature + input example inside the active run; optionally register it."""
    import mlflow
    import mlflow.sklearn
    from mlflow.models.signature import infer_signature

    cfg = settings or get_settings()
    example = sample_input.head(5)
    with warnings.catch_warnings():
        warnings.filterwarnings("ignore", message=".*Inferred schema contains integer column.*")
        signature = infer_signature(example, model.predict(example))
        model_info = mlflow.sklearn.log_model(
            sk_model=model,
            name="model",
            signature=signature,
            input_example=example,
            registered_model_name=cfg.mlflow.model_name if register else None,
            serialization_format=mlflow.sklearn.SERIALIZATION_FORMAT_CLOUDPICKLE,
        )
    version = getattr(model_info, "registered_model_version", None)
    return {"model_uri": model_info.model_uri, "version": str(version) if version is not None else None}
