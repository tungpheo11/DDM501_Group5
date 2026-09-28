"""FastAPI dependencies resolving per-app singletons from ``app.state``."""

from __future__ import annotations

from fastapi import Request

from credit_risk.config import Settings
from credit_risk.serving.errors import ApiError
from credit_risk.serving.model_loader import LoadedModel, ModelManager
from credit_risk.serving.readiness import ReadinessProbe
from credit_risk.serving.scoring import ScoringService


def get_settings_dep(request: Request) -> Settings:
    """Settings the app was built with."""
    settings: Settings = request.app.state.settings
    return settings


def get_model_manager(request: Request) -> ModelManager:
    """The app's model manager."""
    manager: ModelManager = request.app.state.model_manager
    return manager


def get_scoring_service(request: Request) -> ScoringService:
    """The app's scoring service."""
    service: ScoringService = request.app.state.scoring_service
    return service


def get_readiness_probe(request: Request) -> ReadinessProbe:
    """The app's readiness probe."""
    probe: ReadinessProbe = request.app.state.readiness_probe
    return probe


def get_request_id(request: Request) -> str:
    """Request id assigned by :class:`~credit_risk.serving.middleware.RequestContextMiddleware`."""
    return str(request.scope.get("state", {}).get("request_id", ""))


def require_model(request: Request) -> LoadedModel:
    """Snapshot of the served model; HTTP 503 when none is loaded."""
    loaded = get_model_manager(request).current
    if loaded is None:
        raise ApiError(503, "MODEL_UNAVAILABLE", "No model is loaded; check GET /health/ready.")
    return loaded
