"""Login, logout and the role-based landing redirect."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Form, Query, Request, Response
from fastapi.responses import RedirectResponse

from credit_risk.config import get_logger
from staff_portal.auth import authenticate, current_user, start_session, verify_csrf
from staff_portal.config import ROLE_HOME
from staff_portal.context import PortalContext, get_portal
from staff_portal.views import render

router = APIRouter(tags=["auth"])
logger = get_logger(__name__)


def _safe_next(target: str | None, role: str) -> str:
    """Only same-site paths inside the role's own area are honoured after login."""
    home = ROLE_HOME[role]
    if target and target.startswith(home) and not target.startswith("//") and "\\" not in target:
        return target
    return home


@router.get("/")
def index(request: Request) -> Response:
    user = current_user(request)
    return RedirectResponse(ROLE_HOME[user.role] if user else "/login", status_code=303)


def _accounts(portal: PortalContext) -> list[tuple[str, str]]:
    return [(user.username, user.role) for user in portal.settings.users]


@router.get("/login")
def login_form(
    request: Request,
    portal: Annotated[PortalContext, Depends(get_portal)],
    next_url: Annotated[str, Query(alias="next", max_length=512)] = "",
) -> Response:
    user = current_user(request)
    if user:
        return RedirectResponse(ROLE_HOME[user.role], status_code=303)
    context = {"next": next_url, "error": None, "username": "", "accounts": _accounts(portal)}
    return render(request, "login.html", context)


@router.post("/login", dependencies=[Depends(verify_csrf)])
def login(
    request: Request,
    portal: Annotated[PortalContext, Depends(get_portal)],
    username: Annotated[str, Form(max_length=64)] = "",
    password: Annotated[str, Form(max_length=256)] = "",
    next_url: Annotated[str, Form(alias="next", max_length=512)] = "",
) -> Response:
    username = username.strip()
    context = {"next": next_url, "username": username, "accounts": _accounts(portal)}
    if portal.throttle.is_locked(username):
        logger.warning("Portal login locked out", extra={"event": "login_locked", "username": username})
        error = "Tài khoản tạm khoá do đăng nhập sai nhiều lần. Thử lại sau ít phút."
        return render(request, "login.html", {**context, "error": error}, 429)
    user = authenticate(portal.settings, username, password)
    if user is None:
        portal.throttle.record_failure(username)
        logger.info("Portal login failed", extra={"event": "login_failed", "username": username})
        return render(request, "login.html", {**context, "error": "Sai tên đăng nhập hoặc mật khẩu."}, 401)
    portal.throttle.reset(username)
    start_session(request, user)
    logger.info("Portal login", extra={"event": "login", "username": user.username, "role": user.role})
    return RedirectResponse(_safe_next(next_url, user.role), status_code=303)


@router.post("/logout", dependencies=[Depends(verify_csrf)])
def logout(request: Request) -> Response:
    request.session.clear()
    return RedirectResponse("/login", status_code=303)
