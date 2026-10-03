"""Template rendering: Jinja2 environment, Vietnamese labels and display formatters."""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime, timezone
from pathlib import Path
from typing import Any

from fastapi import Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from staff_portal import __version__
from staff_portal.auth import current_user, ensure_csrf_token
from staff_portal.config import ROLE_HOME, ROLE_LABELS, PortalSettings

PACKAGE_DIR = Path(__file__).resolve().parent
TEMPLATES_DIR = PACKAGE_DIR / "templates"
STATIC_DIR = PACKAGE_DIR / "static"

DECISION_LABELS: dict[str, str] = {"APPROVE": "Chấp thuận", "REVIEW": "Chuyển xem xét", "DECLINE": "Từ chối"}
TIER_LABELS: dict[str, str] = {
    "PRIME": "Prime",
    "NEAR_PRIME": "Near-prime",
    "SUBPRIME": "Subprime",
    "HIGH_RISK": "Rủi ro cao",
}
REQUEST_TYPES: dict[str, str] = {
    "LIMIT_INCREASE": "Tăng hạn mức",
    "CASH_ADVANCE": "Rút tiền mặt",
    "INSTALMENT": "Chuyển trả góp",
}
FEATURE_LABELS: dict[str, str] = {
    "LIMIT_BAL": "Hạn mức hiện tại",
    "SEX": "Giới tính",
    "EDUCATION": "Học vấn",
    "MARRIAGE": "Tình trạng hôn nhân",
    "AGE": "Tuổi",
    "PAY_0": "Trả nợ kỳ T9",
    "PAY_2": "Trả nợ kỳ T8",
    "PAY_3": "Trả nợ kỳ T7",
    "PAY_4": "Trả nợ kỳ T6",
    "PAY_5": "Trả nợ kỳ T5",
    "PAY_6": "Trả nợ kỳ T4",
    "BILL_AMT1": "Dư nợ sao kê T9",
    "BILL_AMT2": "Dư nợ sao kê T8",
    "BILL_AMT3": "Dư nợ sao kê T7",
    "BILL_AMT4": "Dư nợ sao kê T6",
    "BILL_AMT5": "Dư nợ sao kê T5",
    "BILL_AMT6": "Dư nợ sao kê T4",
    "PAY_AMT1": "Đã thanh toán T9",
    "PAY_AMT2": "Đã thanh toán T8",
    "PAY_AMT3": "Đã thanh toán T7",
    "PAY_AMT4": "Đã thanh toán T6",
    "PAY_AMT5": "Đã thanh toán T5",
    "PAY_AMT6": "Đã thanh toán T4",
}

# (prefix of the API's top_risk_factors string, code, Vietnamese text, raises risk?)
_REASON_CODES: tuple[tuple[str, str, str, bool], ...] = (
    ("Severe Delinquency", "R01", "Trễ hạn thanh toán từ 2 kỳ trở lên ở kỳ sao kê gần nhất", True),
    ("Payment Lag", "R02", "Có kỳ thanh toán trễ 1 tháng gần đây", True),
    ("Excessive Credit Line Utilization", "R03", "Dư nợ sử dụng gần hết hạn mức (≥ 90%)", True),
    ("Sub-prime Credit Ceiling", "R04", "Hạn mức hiện tại thấp", True),
    ("Demographic Cohort: Young", "R05", "Lịch sử tín dụng còn ngắn", True),
    ("Moderate Debt Utilization", "R06", "Mức sử dụng hạn mức trung bình", True),
    ("Repayment Discipline", "P01", "Thanh toán đúng hạn đều đặn", False),
    ("Conservative Debt Ratio", "P02", "Mức sử dụng hạn mức thấp", False),
    ("Demographic Cohort: Mature", "P03", "Lịch sử tín dụng dài", False),
)
GUARDRAIL_LABELS: dict[str, str] = {
    "age_verification": "Xác minh tuổi",
    "utilization_ceiling_check": "Trần sử dụng hạn mức",
    "delinquency_guardrail": "Kiểm soát trễ hạn",
}
GUARDRAIL_VALUES: dict[str, tuple[str, bool]] = {
    "PASS": ("Đạt", True),
    "ACCEPTABLE": ("Trong ngưỡng", True),
    "CLEAR": ("Không có", True),
    "FAIL": ("Không đạt", False),
    "OVER_UTILIZED_WARNING": ("Vượt 95% hạn mức", False),
    "ELEVATED_DEFAULT_RISK": ("Rủi ro vỡ nợ cao", False),
}


def reason_codes(factors: list[str]) -> list[dict[str, Any]]:
    """Map the API's English risk factors to coded Vietnamese reasons (unknown ones are kept verbatim)."""
    reasons = []
    for factor in factors:
        match = next((entry for entry in _REASON_CODES if factor.startswith(entry[0])), None)
        if match:
            reasons.append({"code": match[1], "text": match[2], "adverse": match[3], "source": factor})
        else:
            reasons.append({"code": "R99", "text": factor, "adverse": True, "source": factor})
    return reasons


def guardrails(checks: dict[str, str]) -> list[dict[str, Any]]:
    """Guardrail checks with Vietnamese labels."""
    rows = []
    for key, value in checks.items():
        label, ok = GUARDRAIL_VALUES.get(value, (value, value in {"PASS", "CLEAR", "ACCEPTABLE"}))
        rows.append({"name": GUARDRAIL_LABELS.get(key, key), "value": label, "ok": ok})
    return rows


def format_money(value: Any) -> str:
    """``200000`` -> ``200.000 NT$``."""
    if value is None or value == "":
        return "—"
    return f"{float(value):,.0f}".replace(",", ".") + " NT$"


def format_number(value: Any, digits: int = 0) -> str:
    """Thousands with dots, decimals with a comma (Vietnamese convention)."""
    if value is None:
        return "—"
    text = f"{float(value):,.{digits}f}"
    return text.replace(",", "_").replace(".", ",").replace("_", ".")


def format_percent(value: Any, digits: int = 1) -> str:
    """``0.4231`` -> ``42,3%``."""
    if value is None:
        return "—"
    return format_number(float(value) * 100, digits) + "%"


def static_fingerprint(directory: Path = STATIC_DIR) -> str:
    """Content hash of the bundled assets, appended to their URLs so a new build bypasses the 1 h browser cache."""
    digest = hashlib.sha256()
    for path in sorted(p for p in directory.rglob("*") if p.is_file()):
        digest.update(path.relative_to(directory).as_posix().encode())
        digest.update(path.read_bytes())
    return digest.hexdigest()[:12]


def build_templates(settings: PortalSettings) -> Jinja2Templates:
    """Jinja2 environment (autoescape on) with the portal filters and globals."""
    templates = Jinja2Templates(directory=str(TEMPLATES_DIR))
    tz: timezone = settings.tz

    def format_datetime(value: datetime | None, seconds: bool = True) -> str:
        if value is None:
            return "—"
        aware = value.replace(tzinfo=UTC) if value.tzinfo is None else value
        return aware.astimezone(tz).strftime("%d/%m/%Y %H:%M:%S" if seconds else "%d/%m/%Y %H:%M")

    env = templates.env
    env.filters.update(
        money=format_money,
        number=format_number,
        percent=format_percent,
        dt=format_datetime,
        decision_label=lambda value: DECISION_LABELS.get(str(value), str(value)),
        tier_label=lambda value: TIER_LABELS.get(str(value), str(value)),
        request_type_label=lambda value: REQUEST_TYPES.get(str(value), str(value)),
        feature_label=lambda value: FEATURE_LABELS.get(str(value), str(value)),
    )
    env.globals.update(
        portal_version=__version__,
        static_version=static_fingerprint(),
        role_labels=ROLE_LABELS,
        decision_labels=DECISION_LABELS,
        request_types=REQUEST_TYPES,
        feature_labels=FEATURE_LABELS,
        utc_offset=settings.utc_offset_hours,
    )
    return templates


def is_htmx(request: Request) -> bool:
    """Whether the request was sent by HTMX (partial response expected)."""
    return request.headers.get("HX-Request") == "true"


def render(
    request: Request,
    template: str,
    context: dict[str, Any] | None = None,
    status_code: int = 200,
    headers: dict[str, str] | None = None,
) -> HTMLResponse:
    """Render ``template`` with the common context (user, CSRF token, navigation)."""
    templates: Jinja2Templates = request.app.state.templates
    user = current_user(request)
    base: dict[str, Any] = {
        "user": user,
        "csrf_token": ensure_csrf_token(request),
        "home_url": ROLE_HOME.get(user.role, "/login") if user else "/login",
        "demo_mode": request.app.state.settings.demo_mode,
        "path": request.url.path,
    }
    return templates.TemplateResponse(
        request, template, {**base, **(context or {})}, status_code=status_code, headers=headers
    )
