"""``/api/v1/model`` routes: served-model metadata and hot reload."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends

from credit_risk.config import Settings
from credit_risk.serving import openapi_examples as ex
from credit_risk.serving.dependencies import get_model_manager, get_readiness_probe, get_settings_dep, require_model
from credit_risk.serving.errors import ApiError
from credit_risk.serving.model_loader import LoadedModel, ModelManager
from credit_risk.serving.readiness import ReadinessProbe
from credit_risk.serving.schemas import ModelInfoResponse, ReloadResponse

router = APIRouter(prefix="/api/v1/model", tags=["model"])


def model_info(loaded: LoadedModel, settings: Settings) -> ModelInfoResponse:
    """Build the metadata response for a model snapshot."""
    return ModelInfoResponse(
        model_name=settings.mlflow.model_name,
        model_alias=settings.mlflow.model_alias,
        model_version=loaded.version,
        source=loaded.source,
        uri=loaded.uri,
        run_id=loaded.run_id,
        model_type=loaded.model_type,
        loaded_at=loaded.loaded_at,
        degraded=loaded.degraded,
        feature_names=list(loaded.feature_names),
        thresholds={"review": settings.serving.review_threshold, "decline": settings.serving.decline_threshold},
    )


@router.get(
    "/info",
    response_model=ModelInfoResponse,
    summary="Describe the served model",
    description="Registry name/alias/version, source (MLflow registry or local fallback), load time, "
    "estimator type, expected features and decision thresholds.",
    responses=ex.error_responses(401, 403, 503),
)
def get_model_info(
    loaded: Annotated[LoadedModel, Depends(require_model)],
    settings: Annotated[Settings, Depends(get_settings_dep)],
) -> ModelInfoResponse:
    return model_info(loaded, settings)


@router.post(
    "/reload",
    response_model=ReloadResponse,
    summary="Hot-reload the champion model",
    description="Reloads `models:/<name>@<alias>` from MLflow (local artifact if MLflow is unreachable) without "
    "downtime. Idempotent. If loading fails the previous model keeps serving "
    "(`status=unchanged_on_failure`); 503 only when no model is available at all. "
    "The worker answering the call reloads synchronously; after a successful reload the other API workers "
    "follow within a few seconds.",
    responses=ex.error_responses(401, 403, 503),
)
def reload_model(
    manager: Annotated[ModelManager, Depends(get_model_manager)],
    probe: Annotated[ReadinessProbe, Depends(get_readiness_probe)],
    settings: Annotated[Settings, Depends(get_settings_dep)],
) -> ReloadResponse:
    outcome = manager.load_champion(broadcast=True)
    probe.invalidate()
    if outcome.current is None:
        raise ApiError(503, "MODEL_UNAVAILABLE", outcome.message, {"last_error": manager.last_error})
    return ReloadResponse(
        status="reloaded" if outcome.success else "unchanged_on_failure",
        message=outcome.message,
        previous_version=outcome.previous.version if outcome.previous else None,
        model=model_info(outcome.current, settings),
    )
