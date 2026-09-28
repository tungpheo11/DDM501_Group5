"""Unauthenticated liveness/readiness probes for Docker, Compose and Airflow."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse

from credit_risk import __version__
from credit_risk.serving import openapi_examples as ex
from credit_risk.serving.dependencies import get_readiness_probe
from credit_risk.serving.readiness import ReadinessProbe
from credit_risk.serving.schemas import DependencyCheck, LivenessResponse, ReadinessResponse

router = APIRouter(prefix="/health", tags=["health"])


@router.get(
    "/live",
    response_model=LivenessResponse,
    summary="Liveness probe",
    description="200 while the process can handle HTTP. Does not touch the model or any dependency.",
)
def live() -> LivenessResponse:
    return LivenessResponse(status="alive", version=__version__)


@router.get(
    "/ready",
    response_model=ReadinessResponse,
    summary="Readiness probe",
    description="`ready`: champion from MLflow and all dependencies up. `degraded` (still 200): serving the local "
    "fallback model and/or MLflow or the database is down. `not_ready` (503): no model loaded. "
    "Dependency probes are cached for `readiness_cache_seconds`.",
    responses={
        200: {
            "description": "Instance can serve predictions",
            "content": {
                "application/json": {
                    "examples": {
                        "ready": {"summary": "All dependencies up", "value": ex.READINESS_READY},
                        "degraded": {"summary": "Local fallback model", "value": ex.READINESS_DEGRADED},
                    }
                }
            },
        },
        503: {
            "model": ReadinessResponse,
            "description": "No model loaded",
            "content": {"application/json": {"example": ex.READINESS_NOT_READY}},
        },
    },
)
def ready(probe: Annotated[ReadinessProbe, Depends(get_readiness_probe)]) -> JSONResponse:
    report = probe.evaluate()
    body = ReadinessResponse(
        status=report.status,
        reasons=report.reasons,
        checks={
            name: DependencyCheck(status=check.status, detail=check.detail) for name, check in report.checks.items()
        },
    )
    return JSONResponse(status_code=report.http_status, content=body.model_dump())
