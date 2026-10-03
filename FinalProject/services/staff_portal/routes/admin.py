"""System admin: inference-log browser, traffic simulation, demo data reset, system status and links.

These operations exist only in the portal; the public scoring API has no admin endpoints.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Annotated, Any
from urllib.parse import urlencode

import httpx
from fastapi import APIRouter, Depends, Form, HTTPException, Query, Request, Response
from fastapi.responses import RedirectResponse

from credit_risk.config import get_logger
from staff_portal.auth import SessionUser, require_role, verify_csrf
from staff_portal.context import PortalContext, get_portal
from staff_portal.scoring_client import ScoringApiError
from staff_portal.simulator import SOURCE_LABELS, SimulationBusyError, SimulationRejectedError
from staff_portal.store import DECISIONS, LogFilters
from staff_portal.views import is_htmx, render

_require_admin = require_role("admin")
router = APIRouter(prefix="/admin", tags=["admin"], dependencies=[Depends(_require_admin)])
logger = get_logger(__name__)

AdminUser = Annotated[SessionUser, Depends(_require_admin)]
Portal = Annotated[PortalContext, Depends(get_portal)]

DELETE_CONFIRMATION = "XOA"


def _parse_local(value: str, portal: PortalContext) -> datetime | None:
    """``datetime-local`` input in the staff time zone -> naive UTC."""
    if not value:
        return None
    try:
        local = datetime.fromisoformat(value)
    except ValueError:
        raise HTTPException(status_code=400, detail="Thời gian lọc không hợp lệ.") from None
    if local.tzinfo is None:
        local = local.replace(tzinfo=portal.settings.tz)
    return local.astimezone(UTC).replace(tzinfo=None)


class LogQuery:
    """Query-string filters of the log table (kept as strings to refill the form)."""

    def __init__(
        self,
        decision: Annotated[str, Query(max_length=16)] = "",
        model_version: Annotated[str, Query(max_length=128)] = "",
        start: Annotated[str, Query(max_length=32)] = "",
        end: Annotated[str, Query(max_length=32)] = "",
        page: Annotated[int, Query(ge=1, le=100_000)] = 1,
    ) -> None:
        if decision and decision not in DECISIONS:
            raise HTTPException(status_code=400, detail="Quyết định lọc không hợp lệ.")
        self.decision = decision
        self.model_version = model_version
        self.start = start
        self.end = end
        self.page = page

    def filters(self, portal: PortalContext) -> LogFilters:
        """Database filters."""
        return LogFilters(
            risk_decision=self.decision or None,
            model_version=self.model_version or None,
            start=_parse_local(self.start, portal),
            end=_parse_local(self.end, portal),
        )

    def as_dict(self) -> dict[str, str]:
        """Non-empty filters (for pagination links)."""
        values = {"decision": self.decision, "model_version": self.model_version, "start": self.start, "end": self.end}
        return {key: value for key, value in values.items() if value}

    def url(self, page: int) -> str:
        """Partial URL of another page with the same filters."""
        return "/admin/logs?" + urlencode({**self.as_dict(), "page": page})


def _logs_context(portal: PortalContext, query: LogQuery) -> dict[str, Any]:
    filters = query.filters(portal)
    page = portal.store.query_logs(filters, query.page, portal.settings.page_size)
    return {
        "page": page,
        "stats": portal.store.log_stats(filters),
        "query": query,
        "versions": portal.store.model_versions(),
        "decisions": DECISIONS,
        "prev_url": query.url(page.page - 1) if page.page > 1 else None,
        "next_url": query.url(page.page + 1) if page.page < page.pages else None,
    }


def _simulation_context(portal: PortalContext) -> dict[str, Any]:
    return {
        "job": portal.simulator.current(),
        "sources": SOURCE_LABELS,
        "default_count": portal.settings.simulate_default_count,
        "max_count": portal.simulator.max_count,
        "rate": portal.settings.simulate_rate_per_second,
    }


def _parse_iso(value: Any) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


def _system_status(portal: PortalContext) -> dict[str, Any]:
    readiness = portal.scoring.readiness()
    try:
        model: dict[str, Any] | None = portal.scoring.model_info().body
    except ScoringApiError as exc:
        model = None
        logger.warning("Model info unavailable: %s", exc.code)
    if model is not None:
        model["loaded_at_dt"] = _parse_iso(model.get("loaded_at"))
    drift: dict[str, Any] | None = None
    drift_error: str | None = None
    if portal.settings.drift_monitor_url:
        try:
            response = portal.http.get(f"{portal.settings.drift_monitor_url}/drift/latest")
            if response.status_code == 200:
                drift = response.json()
                drift["analyzed_at_dt"] = _parse_iso(drift.get("analyzed_at"))
            else:
                drift_error = (
                    "Chưa có lần phân tích nào" if response.status_code == 404 else f"HTTP {response.status_code}"
                )
        except httpx.HTTPError:
            drift_error = "Không kết nối được drift monitor"
    return {
        "readiness": readiness,
        "model": model,
        "drift": drift,
        "drift_error": drift_error,
        "database_ok": portal.store.ping(),
    }


@router.get("")
def dashboard(request: Request, user: AdminUser, portal: Portal, query: Annotated[LogQuery, Depends()]) -> Response:
    return render(
        request,
        "admin/index.html",
        {
            **_logs_context(portal, query),
            **_simulation_context(portal),
            "links": portal.settings.links,
            "audit": portal.store.audit_entries(),
            "log_count": portal.store.count_logs(),
            "confirmation_word": DELETE_CONFIRMATION,
        },
    )


@router.get("/status")
def status(request: Request, user: AdminUser, portal: Portal) -> Response:
    return render(request, "admin/_status.html", _system_status(portal))


@router.get("/logs")
def logs(request: Request, user: AdminUser, portal: Portal, query: Annotated[LogQuery, Depends()]) -> Response:
    if not is_htmx(request):
        params = urlencode({**query.as_dict(), "page": query.page})
        return RedirectResponse(f"/admin?{params}", status_code=303)
    return render(request, "admin/_logs.html", _logs_context(portal, query))


@router.get("/logs/{log_id}")
def log_detail(request: Request, log_id: int, user: AdminUser, portal: Portal) -> Response:
    row = portal.store.get_log(log_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Không tìm thấy dòng log.")
    raw = str(row.features_json)
    try:
        features = json.dumps(json.loads(raw), indent=2, ensure_ascii=False)
    except ValueError:
        features = raw
    return render(request, "admin/_log_detail.html", {"row": row, "features": features})


@router.get("/simulate/status")
def simulation_status(request: Request, user: AdminUser, portal: Portal) -> Response:
    context = _simulation_context(portal)
    # Only polled while a job runs, so the log table refreshes in step, including the final poll.
    headers = {"HX-Trigger": "logs-changed"} if context["job"] is not None else None
    return render(request, "admin/_simulation.html", context, headers=headers)


@router.post("/simulate", dependencies=[Depends(verify_csrf)])
def start_simulation(
    request: Request,
    user: AdminUser,
    portal: Portal,
    source: Annotated[str, Form()] = "normal",
    count: Annotated[int, Form()] = 200,
) -> Response:
    try:
        job = portal.simulator.start(source, count, user.username)
    except SimulationBusyError:
        raise HTTPException(status_code=409, detail="Đang có một job simulate chạy. Dừng job đó trước.") from None
    except SimulationRejectedError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from None
    portal.store.audit(user.username, "simulation_started", detail=f"{job['source_label']}: {count} request")
    if is_htmx(request):
        return render(request, "admin/_simulation.html", _simulation_context(portal))
    return RedirectResponse("/admin", status_code=303)


@router.post("/simulate/stop", dependencies=[Depends(verify_csrf)])
def stop_simulation(request: Request, user: AdminUser, portal: Portal) -> Response:
    if not portal.simulator.stop(user.username):
        raise HTTPException(status_code=409, detail="Không có job simulate nào đang chạy.")
    portal.simulator.wait(timeout=5)
    if is_htmx(request):
        return render(request, "admin/_simulation.html", _simulation_context(portal))
    return RedirectResponse("/admin", status_code=303)


@router.post("/logs/delete", dependencies=[Depends(verify_csrf)])
def delete_logs(
    request: Request,
    user: AdminUser,
    portal: Portal,
    confirmation: Annotated[str, Form(max_length=16)] = "",
) -> Response:
    if not portal.settings.demo_mode:
        logger.warning("Blocked inference-log deletion outside demo mode", extra={"actor": user.username})
        raise HTTPException(status_code=403, detail="Xoá dữ liệu chỉ được bật khi PORTAL_DEMO_MODE=true.")
    if confirmation.strip() != DELETE_CONFIRMATION:
        raise HTTPException(status_code=400, detail=f"Hãy gõ đúng chữ {DELETE_CONFIRMATION} để xác nhận.")
    if portal.simulator.is_running():
        raise HTTPException(status_code=409, detail="Đang chạy simulate. Dừng job trước khi xoá dữ liệu.")
    deleted = portal.store.delete_all_logs(user.username)
    context = {"deleted": deleted, "audit": portal.store.audit_entries(), "remaining": portal.store.count_logs()}
    if is_htmx(request):
        return render(request, "admin/_delete_result.html", context, headers={"HX-Trigger": "logs-changed"})
    return RedirectResponse("/admin", status_code=303)
