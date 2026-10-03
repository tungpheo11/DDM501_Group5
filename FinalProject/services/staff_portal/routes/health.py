"""Unauthenticated liveness/readiness probes for Docker, Compose and the smoke test.

* ``/health/live``: the process answers HTTP; touches no dependency.
* ``/health/ready``: 503 when the portal database is down (nothing works without it).
  An unreachable or not-ready scoring API only degrades the portal (still 200): login,
  the log browser and the audit trail keep working, and the API has its own probe.
* ``/health``: summary for operators; 503 when the database is down.
"""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse

from staff_portal import __version__
from staff_portal.context import PortalContext, get_portal

router = APIRouter(prefix="/health", include_in_schema=False)

Portal = Annotated[PortalContext, Depends(get_portal)]

SERVICE_NAME = "staff-portal"
# Kept below the 4 s urlopen timeout of the container healthcheck.
SCORING_PROBE_TIMEOUT_SECONDS = 2.0
_SERVING_STATES = {"ready", "degraded"}


def _database_check(portal: PortalContext) -> dict[str, Any]:
    return {"status": "up" if portal.store.ping() else "down"}


def _scoring_check(portal: PortalContext) -> dict[str, Any]:
    body = portal.scoring.readiness(timeout_seconds=SCORING_PROBE_TIMEOUT_SECONDS)
    api_status = str(body.get("status", "unknown"))
    check: dict[str, Any] = {"status": "up" if api_status in _SERVING_STATES else "down", "detail": api_status}
    reasons = body.get("reasons")
    if api_status not in _SERVING_STATES and isinstance(reasons, list) and reasons:
        check["reasons"] = [str(reason) for reason in reasons]
    return check


@router.get("")
def summary(portal: Portal) -> JSONResponse:
    database = _database_check(portal)
    database_up = database["status"] == "up"
    body: dict[str, Any] = {
        "status": "ok" if database_up else "down",
        "service": SERVICE_NAME,
        "version": __version__,
        "demo_mode": portal.settings.demo_mode,
        "database": "ok" if database_up else "down",
        "catalog_size": len(portal.catalog),
        "accounts": len(portal.settings.users),
    }
    return JSONResponse(status_code=200 if database_up else 503, content=body)


@router.get("/live")
def live() -> dict[str, str]:
    return {"status": "alive", "service": SERVICE_NAME, "version": __version__}


@router.get("/ready")
def ready(portal: Portal) -> JSONResponse:
    checks = {"database": _database_check(portal), "scoring_api": _scoring_check(portal)}
    reasons: list[str] = []
    if checks["database"]["status"] != "up":
        reasons.append("portal database is unreachable")
    if checks["scoring_api"]["status"] != "up":
        reasons.append(f"scoring API is {checks['scoring_api']['detail']}")

    if checks["database"]["status"] != "up":
        status, http_status = "not_ready", 503
    elif reasons:
        status, http_status = "degraded", 200
    else:
        status, http_status = "ready", 200
    body = {"status": status, "service": SERVICE_NAME, "version": __version__, "reasons": reasons, "checks": checks}
    return JSONResponse(status_code=http_status, content=body)
