"""FastAPI scoring service (API v1).

Serves the champion model (MLflow registry, local artifact fallback in degraded
mode), exports Prometheus telemetry, and logs every inference for drift analysis.

Run with ``uvicorn credit_risk.serving.app:app``.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, Response
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest

from credit_risk import __version__
from credit_risk.config import Settings, get_logger, get_settings, setup_logging
from credit_risk.monitoring.metrics import RollingFeatureStats
from credit_risk.serving import database
from credit_risk.serving.errors import register_error_handlers
from credit_risk.serving.middleware import RequestContextMiddleware
from credit_risk.serving.model_loader import ModelManager
from credit_risk.serving.readiness import ReadinessProbe
from credit_risk.serving.routers import health, model, predict
from credit_risk.serving.scoring import ScoringService
from credit_risk.serving.security import require_api_key

logger = get_logger(__name__)

API_DESCRIPTION = """
Online scoring service for **credit default risk** (UCI Credit Default, 23 features).

* `/api/v1/*` requires the `X-API-Key` header.
* Every response carries `X-Request-ID` (send your own to correlate logs; otherwise one is generated).
* Errors share one schema: `{code, message, details, request_id}`.
* `/health/live`, `/health/ready` and `/metrics` are unauthenticated for orchestrators and Prometheus;
  keep them on the internal network.
"""

OPENAPI_TAGS = [
    {"name": "prediction", "description": "Score applicants and explain scores."},
    {"name": "model", "description": "Served-model metadata and hot reload."},
    {"name": "health", "description": "Liveness and readiness probes."},
    {"name": "observability", "description": "Prometheus metrics."},
]


def create_app(settings: Settings | None = None) -> FastAPI:
    """Build the FastAPI application with its own model manager, scoring service and probes."""
    cfg = settings or get_settings()
    setup_logging(cfg)
    model_manager = ModelManager(cfg)
    scoring_service = ScoringService(cfg, RollingFeatureStats(window=cfg.serving.rolling_window))
    readiness_probe = ReadinessProbe(cfg, model_manager)

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        if cfg.serving.auth_enabled and not cfg.serving.api_keys:
            logger.error("API auth is enabled but API_KEYS is empty: every /api/v1 request will be rejected.")
        elif not cfg.serving.auth_enabled:
            logger.warning("API auth is DISABLED (API_AUTH_ENABLED=false); never run like this outside local dev.")
        database.init_db(cfg.database.url)
        model_manager.load_champion()
        scoring_service.warm_up_explainer(model_manager.current)
        yield

    application = FastAPI(
        title="Credit Default Risk Scoring API",
        description=API_DESCRIPTION,
        version=__version__,
        lifespan=lifespan,
        openapi_tags=OPENAPI_TAGS,
        swagger_ui_parameters={"docExpansion": "list", "persistAuthorization": True},
    )
    application.state.settings = cfg
    application.state.model_manager = model_manager
    application.state.scoring_service = scoring_service
    application.state.readiness_probe = readiness_probe

    register_error_handlers(application)
    application.add_middleware(RequestContextMiddleware)

    protected = [Depends(require_api_key)]
    application.include_router(predict.router, dependencies=protected)
    application.include_router(model.router, dependencies=protected)
    application.include_router(health.router)

    @application.get(
        "/metrics",
        tags=["observability"],
        summary="Prometheus scrape endpoint",
        response_class=Response,
        responses={
            200: {
                "description": "Prometheus text exposition format",
                "content": {
                    "text/plain": {
                        "example": "# TYPE credit_model_loaded gauge\ncredit_model_loaded 1.0\n"
                        'credit_prediction_requests_total{decision="APPROVE",status="200"} 42.0\n'
                    }
                },
            }
        },
    )
    def metrics() -> Response:
        return Response(content=generate_latest(), media_type=CONTENT_TYPE_LATEST)

    return application


app = create_app()
