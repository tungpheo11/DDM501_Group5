"""Credit risk analyst: REVIEW queue with SHAP explanations, final decisions, batch limit review, early warning."""

from __future__ import annotations

import csv
import io
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Form, HTTPException, Request, Response
from fastapi.responses import RedirectResponse

from credit_risk.config import get_logger
from staff_portal.auth import SessionUser, require_role, verify_csrf
from staff_portal.catalog import STATEMENT_DAYS, Cardholder
from staff_portal.context import PortalContext, get_portal
from staff_portal.store import ANALYST_ACTIONS, DECISIONS, AlreadyDecidedError, BatchReview, LimitRequest
from staff_portal.views import DECISION_LABELS, TIER_LABELS, guardrails, is_htmx, reason_codes, render

_require_analyst = require_role("analyst")
router = APIRouter(prefix="/analyst", tags=["analyst"], dependencies=[Depends(_require_analyst)])
logger = get_logger(__name__)

AnalystUser = Annotated[SessionUser, Depends(_require_analyst)]
Portal = Annotated[PortalContext, Depends(get_portal)]

COHORTS: dict[str, str] = {"all": "Toàn bộ danh mục demo"} | {
    f"day-{day}": f"Kỳ sao kê ngày {day:02d}" for day in STATEMENT_DAYS
}
CSV_COLUMNS = (
    "customer_id",
    "full_name",
    "card_masked",
    "statement_day",
    "limit_bal_ntd",
    "risk_decision",
    "default_probability",
    "credit_score",
    "credit_tier",
    "recommended_limit_ntd",
    "top_risk_factors",
)


def _case(portal: PortalContext, case_id: int) -> tuple[LimitRequest, Cardholder]:
    record = portal.store.get_limit_request(case_id)
    cardholder = portal.catalog.get(record.customer_id) if record else None
    if record is None or cardholder is None:
        raise HTTPException(status_code=404, detail="Không tìm thấy ca cần xem xét.")
    return record, cardholder


def _cohort_members(portal: PortalContext, cohort: str) -> list[Cardholder]:
    if cohort not in COHORTS:
        raise HTTPException(status_code=400, detail="Lô rà soát không hợp lệ.")
    day = None if cohort == "all" else int(cohort.removeprefix("day-"))
    return portal.catalog.by_statement_day(day)


@router.get("")
def queue(request: Request, user: AnalystUser, portal: Portal) -> Response:
    cases = [(record, portal.catalog.get(record.customer_id)) for record in portal.store.review_queue()]
    return render(
        request,
        "analyst/queue.html",
        {"cases": cases, "decided": portal.store.recent_decisions(), "actions": ANALYST_ACTIONS},
    )


@router.get("/cases/{case_id}")
def case_detail(request: Request, case_id: int, user: AnalystUser, portal: Portal) -> Response:
    record, cardholder = _case(portal, case_id)
    return render(
        request,
        "analyst/case.html",
        {
            "record": record,
            "cardholder": cardholder,
            "decision": portal.store.decision_for(record.id),
            "reasons": reason_codes(record.top_risk_factors),
            "guardrails": guardrails(record.policy_guardrails),
            "actions": ANALYST_ACTIONS,
            "error": None,
        },
    )


@router.get("/cases/{case_id}/explain")
def case_explain(request: Request, case_id: int, user: AnalystUser, portal: Portal) -> Response:
    _, cardholder = _case(portal, case_id)
    result = portal.scoring.explain(cardholder.payload())
    body = result.body
    contributions = body.get("contributions", [])
    scale = max((abs(float(item["contribution"])) for item in contributions), default=0.0) or 1.0
    return render(
        request,
        "analyst/_explain.html",
        {
            "explain": body,
            "roundtrip_ms": result.roundtrip_ms,
            "contributions": [
                {**item, "magnitude": round(abs(float(item["contribution"])) / scale * 100)} for item in contributions
            ],
        },
    )


@router.post("/cases/{case_id}/decision", dependencies=[Depends(verify_csrf)])
def decide(
    request: Request,
    case_id: int,
    user: AnalystUser,
    portal: Portal,
    action: Annotated[str, Form()] = "",
    new_limit: Annotated[str, Form(max_length=16)] = "",
    note: Annotated[str, Form(max_length=1000)] = "",
) -> Response:
    record, cardholder = _case(portal, case_id)
    if action not in ANALYST_ACTIONS:
        raise HTTPException(status_code=400, detail="Hãy chọn quyết định cuối.")
    limit: float | None = None
    if action == "REDUCE":
        try:
            limit = float(new_limit.replace(".", "").replace(",", ""))
        except ValueError:
            raise HTTPException(status_code=400, detail="Nhập hạn mức mới (số tiền).") from None
        if not 0 < limit < cardholder.limit_bal:
            raise HTTPException(status_code=400, detail="Hạn mức mới phải lớn hơn 0 và thấp hơn hạn mức hiện tại.")
    elif action == "SUSPEND":
        limit = 0.0
    else:
        limit = cardholder.limit_bal
    try:
        portal.store.record_decision(record.id, user.username, action, limit, note.strip() or None)
    except AlreadyDecidedError:
        raise HTTPException(status_code=409, detail="Ca này đã có quyết định cuối.") from None
    logger.info("Analyst decision recorded", extra={"event": "analyst_decision", "action": action})
    if is_htmx(request):
        return Response(status_code=200, headers={"HX-Redirect": "/analyst"})
    return RedirectResponse("/analyst", status_code=303)


def _batch_rows(members: list[Cardholder], predictions: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows = []
    for member, item in zip(members, predictions, strict=True):
        rows.append(
            {
                "customer_id": member.customer_id,
                "full_name": member.full_name,
                "card_masked": member.card_masked,
                "statement_day": member.statement_day,
                "limit_bal_ntd": member.limit_bal,
                "risk_decision": item["risk_decision"],
                "default_probability": item["default_probability"],
                "credit_score": item["credit_score"],
                "credit_tier": item["credit_tier"],
                "recommended_limit_ntd": item["recommended_limit_ntd"],
                "top_risk_factors": item.get("top_risk_factors", []),
            }
        )
    return rows


def _batch_context(review: BatchReview | None) -> dict[str, Any]:
    if review is None:
        return {"review": None}
    summary = review.decision_summary
    total = max(review.count, 1)
    return {
        "review": review,
        "summary": [
            (decision, summary.get(decision, 0), round(summary.get(decision, 0) / total * 100))
            for decision in DECISIONS
        ],
        "rows": review.results,
        "cohort_label": COHORTS.get(review.cohort, review.cohort),
    }


@router.get("/batch")
def batch_page(request: Request, user: AnalystUser, portal: Portal) -> Response:
    latest = portal.store.latest_batch_review()
    return render(
        request,
        "analyst/batch.html",
        {
            "cohorts": [(key, label, len(_cohort_members(portal, key))) for key, label in COHORTS.items()],
            "history": portal.store.recent_batch_reviews(),
            "max_size": portal.settings.batch_max_size,
            **_batch_context(latest),
        },
    )


@router.post("/batch", dependencies=[Depends(verify_csrf)])
def run_batch(request: Request, user: AnalystUser, portal: Portal, cohort: Annotated[str, Form()] = "all") -> Response:
    members = _cohort_members(portal, cohort)
    if not members:
        raise HTTPException(status_code=400, detail="Lô rà soát không có chủ thẻ nào.")
    if len(members) > portal.settings.batch_max_size:
        raise HTTPException(status_code=400, detail=f"Một lô tối đa {portal.settings.batch_max_size} chủ thẻ.")
    result = portal.scoring.predict_batch([member.payload() for member in members])
    body = result.body
    review = portal.store.save_batch_review(
        created_by=user.username,
        cohort=cohort,
        api_request_id=str(body["request_id"]),
        model_version=str(body["model_version"]),
        latency_ms=float(body["latency_ms"]),
        decision_summary={decision: int(body["decision_summary"].get(decision, 0)) for decision in DECISIONS},
        results=_batch_rows(members, list(body["predictions"])),
    )
    logger.info("Batch review completed", extra={"event": "batch_review", "count": review.count})
    if is_htmx(request):
        return render(request, "analyst/_batch_result.html", _batch_context(review))
    return RedirectResponse(f"/analyst/batch/{review.id}", status_code=303)


@router.get("/batch/{review_id}")
def batch_detail(request: Request, review_id: int, user: AnalystUser, portal: Portal) -> Response:
    review = portal.store.get_batch_review(review_id)
    if review is None:
        raise HTTPException(status_code=404, detail="Không tìm thấy lô rà soát.")
    return render(request, "analyst/batch_detail.html", _batch_context(review))


@router.get("/batch/{review_id}/csv")
def batch_csv(review_id: int, user: AnalystUser, portal: Portal) -> Response:
    review = portal.store.get_batch_review(review_id)
    if review is None:
        raise HTTPException(status_code=404, detail="Không tìm thấy lô rà soát.")
    buffer = io.StringIO()
    writer = csv.DictWriter(buffer, fieldnames=CSV_COLUMNS, extrasaction="ignore")
    writer.writeheader()
    for row in review.results:
        writer.writerow({**row, "top_risk_factors": " | ".join(row.get("top_risk_factors", []))})
    filename = f"ra-soat-han-muc-lo-{review.id}.csv"
    return Response(
        content="\ufeff" + buffer.getvalue(),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/early-warning")
def early_warning(request: Request, user: AnalystUser, portal: Portal) -> Response:
    review = portal.store.latest_batch_review()
    rows = []
    if review is not None:
        rows = sorted(
            (row for row in review.results if row["risk_decision"] != "APPROVE"),
            key=lambda row: float(row["default_probability"]),
            reverse=True,
        )
    return render(
        request,
        "analyst/early_warning.html",
        {"review": review, "rows": rows, "decision_labels": DECISION_LABELS, "tier_labels": TIER_LABELS},
    )
