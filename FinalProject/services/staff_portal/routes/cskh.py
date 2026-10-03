"""Customer service (card operations): find a cardholder, submit a request, show the realtime decision."""

from __future__ import annotations

from typing import Annotated
from urllib.parse import urlencode

from fastapi import APIRouter, Depends, Form, HTTPException, Query, Request, Response
from fastapi.responses import RedirectResponse

from credit_risk.config import get_logger
from staff_portal.auth import SessionUser, require_role, verify_csrf
from staff_portal.catalog import Cardholder
from staff_portal.context import PortalContext, get_portal
from staff_portal.store import LimitRequest
from staff_portal.views import REQUEST_TYPES, guardrails, is_htmx, reason_codes, render

_require_cskh = require_role("cskh")
router = APIRouter(prefix="/cskh", tags=["cskh"], dependencies=[Depends(_require_cskh)])
logger = get_logger(__name__)

CskhUser = Annotated[SessionUser, Depends(_require_cskh)]
Portal = Annotated[PortalContext, Depends(get_portal)]


def _cardholder(portal: PortalContext, customer_id: str) -> Cardholder:
    cardholder = portal.catalog.get(customer_id)
    if cardholder is None:
        raise HTTPException(status_code=404, detail="Không tìm thấy chủ thẻ.")
    return cardholder


def _result_context(portal: PortalContext, record: LimitRequest) -> dict[str, object]:
    return {
        "record": record,
        "cardholder": portal.catalog.get(record.customer_id),
        "reasons": reason_codes(record.top_risk_factors),
        "guardrails": guardrails(record.policy_guardrails),
    }


@router.get("")
def index(request: Request, user: CskhUser, portal: Portal, q: Annotated[str, Query(max_length=64)] = "") -> Response:
    return render(
        request,
        "cskh/index.html",
        {
            "q": q,
            "results": portal.catalog.search(q),
            "recent": portal.store.recent_requests(created_by=user.username),
            "catalog_size": len(portal.catalog),
        },
    )


@router.get("/search")
def search(request: Request, user: CskhUser, portal: Portal, q: Annotated[str, Query(max_length=64)] = "") -> Response:
    if not is_htmx(request):
        return RedirectResponse(f"/cskh?{urlencode({'q': q})}", status_code=303)
    return render(request, "cskh/_results.html", {"q": q, "results": portal.catalog.search(q)})


@router.get("/customers/{customer_id}")
def customer(request: Request, customer_id: str, user: CskhUser, portal: Portal) -> Response:
    cardholder = _cardholder(portal, customer_id)
    history = [item for item in portal.store.recent_requests(limit=50) if item.customer_id == customer_id]
    return render(request, "cskh/customer.html", {"cardholder": cardholder, "history": history[:5]})


@router.post("/customers/{customer_id}/requests", dependencies=[Depends(verify_csrf)])
def create_request(
    request: Request,
    customer_id: str,
    user: CskhUser,
    portal: Portal,
    request_type: Annotated[str, Form()] = "LIMIT_INCREASE",
    requested_amount: Annotated[str, Form(max_length=16)] = "",
    note: Annotated[str, Form(max_length=500)] = "",
) -> Response:
    cardholder = _cardholder(portal, customer_id)
    if request_type not in REQUEST_TYPES:
        raise HTTPException(status_code=400, detail="Loại yêu cầu không hợp lệ.")
    amount: float | None = None
    if requested_amount.strip():
        try:
            amount = float(requested_amount.replace(".", "").replace(",", ""))
        except ValueError:
            raise HTTPException(status_code=400, detail="Số tiền yêu cầu không hợp lệ.") from None
        if amount <= 0:
            raise HTTPException(status_code=400, detail="Số tiền yêu cầu phải lớn hơn 0.")

    result = portal.scoring.predict(cardholder.payload())
    body = result.body
    record = portal.store.add_limit_request(
        created_by=user.username,
        customer_id=cardholder.customer_id,
        request_type=request_type,
        requested_amount=amount,
        note=note.strip() or None,
        api_request_id=str(body["request_id"]),
        risk_decision=str(body["risk_decision"]),
        default_probability=float(body["default_probability"]),
        credit_score=int(body["credit_score"]),
        credit_tier=str(body["credit_tier"]),
        recommended_limit_ntd=float(body["recommended_limit_ntd"]),
        top_risk_factors=list(body.get("top_risk_factors", [])),
        policy_guardrails=dict(body.get("policy_guardrails", {})),
        model_version=str(body["model_version"]),
        api_latency_ms=float(body["latency_ms"]),
        roundtrip_ms=result.roundtrip_ms,
    )
    logger.info(
        "Limit request scored",
        extra={
            "event": "portal_request",
            "decision": record.risk_decision,
            "roundtrip_ms": record.roundtrip_ms,
            "actor": user.username,
        },
    )
    if is_htmx(request):
        return render(request, "cskh/_decision.html", _result_context(portal, record))
    return RedirectResponse(f"/cskh/requests/{record.id}", status_code=303)


@router.get("/requests/{record_id}")
def request_detail(request: Request, record_id: int, user: CskhUser, portal: Portal) -> Response:
    record = portal.store.get_limit_request(record_id)
    if record is None:
        raise HTTPException(status_code=404, detail="Không tìm thấy yêu cầu.")
    return render(request, "cskh/request.html", _result_context(portal, record))
