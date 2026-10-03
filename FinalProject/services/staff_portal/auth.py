"""Login, session identity, CSRF protection and per-route role checks.

The session is a signed cookie (Starlette ``SessionMiddleware``: ``HttpOnly``,
``SameSite=Lax``). It carries only the username, role, display name and the CSRF
token; the scoring API key never leaves the server.
"""

from __future__ import annotations

import secrets
import threading
import time
from collections import deque
from collections.abc import Awaitable, Callable
from dataclasses import dataclass

import bcrypt
from fastapi import HTTPException, Request

from staff_portal.config import PortalSettings, PortalUser

CSRF_SESSION_KEY = "csrf_token"
CSRF_FORM_FIELD = "csrf_token"
CSRF_HEADER = "X-CSRF-Token"
USER_SESSION_KEY = "user"

# Verified against when the username is unknown, so both paths cost one bcrypt check.
_DUMMY_HASH = bcrypt.hashpw(b"staff-portal-unknown-user", bcrypt.gensalt(rounds=4))


@dataclass(frozen=True)
class SessionUser:
    """Identity stored in the session cookie."""

    username: str
    role: str
    display_name: str


class LoginRequiredError(Exception):
    """Raised by role checks when the request has no authenticated session."""


class LoginThrottle:
    """In-memory lockout after repeated failed logins for one username (single portal process)."""

    def __init__(self, max_failures: int, lockout_seconds: int, clock: Callable[[], float] = time.monotonic) -> None:
        self._max_failures = max_failures
        self._lockout_seconds = lockout_seconds
        self._clock = clock
        self._failures: dict[str, deque[float]] = {}
        self._lock = threading.Lock()

    def _recent(self, username: str) -> deque[float]:
        window_start = self._clock() - self._lockout_seconds
        failures = self._failures.setdefault(username, deque())
        while failures and failures[0] < window_start:
            failures.popleft()
        return failures

    def is_locked(self, username: str) -> bool:
        """Whether ``username`` reached ``max_failures`` within the lockout window."""
        with self._lock:
            return len(self._recent(username)) >= self._max_failures

    def record_failure(self, username: str) -> None:
        """Count one failed attempt."""
        with self._lock:
            self._recent(username).append(self._clock())

    def reset(self, username: str) -> None:
        """Forget failures after a successful login."""
        with self._lock:
            self._failures.pop(username, None)


def authenticate(settings: PortalSettings, username: str, password: str) -> PortalUser | None:
    """Return the account when ``password`` matches its bcrypt hash."""
    user = settings.user(username)
    candidate = password.encode("utf-8")[:72]
    if user is None:
        bcrypt.checkpw(candidate, _DUMMY_HASH)
        return None
    try:
        return user if bcrypt.checkpw(candidate, user.password_hash) else None
    except ValueError:  # malformed hash in PORTAL_*_PASSWORD_HASH
        return None


def ensure_csrf_token(request: Request) -> str:
    """CSRF token of the current session, created on first use."""
    token = request.session.get(CSRF_SESSION_KEY)
    if not token:
        token = secrets.token_urlsafe(32)
        request.session[CSRF_SESSION_KEY] = token
    return str(token)


def start_session(request: Request, user: PortalUser) -> None:
    """Replace the session content with a fresh identity and CSRF token."""
    request.session.clear()
    request.session[USER_SESSION_KEY] = {
        "username": user.username,
        "role": user.role,
        "display_name": user.display_name,
    }
    request.session[CSRF_SESSION_KEY] = secrets.token_urlsafe(32)


def current_user(request: Request) -> SessionUser | None:
    """Authenticated user of this request, if any (re-checked against the configured accounts)."""
    raw = request.session.get(USER_SESSION_KEY)
    if not isinstance(raw, dict):
        return None
    settings: PortalSettings = request.app.state.settings
    account = settings.user(str(raw.get("username", "")))
    if account is None or account.role != raw.get("role"):
        return None
    return SessionUser(username=account.username, role=account.role, display_name=account.display_name)


async def verify_csrf(request: Request) -> None:
    """Reject state-changing requests whose CSRF token (form field or header) does not match the session."""
    expected = request.session.get(CSRF_SESSION_KEY)
    provided = request.headers.get(CSRF_HEADER)
    if not provided:
        form = await request.form()
        value = form.get(CSRF_FORM_FIELD)
        provided = value if isinstance(value, str) else None
    if not expected or not provided or not secrets.compare_digest(str(expected).encode(), provided.encode()):
        raise HTTPException(status_code=403, detail="Phiên làm việc không hợp lệ (CSRF). Hãy tải lại trang.")


def require_role(*roles: str) -> Callable[[Request], Awaitable[SessionUser]]:
    """Dependency: the session user must have one of ``roles`` (401/redirect if anonymous, 403 otherwise)."""

    async def dependency(request: Request) -> SessionUser:
        user = current_user(request)
        if user is None:
            raise LoginRequiredError()
        if user.role not in roles:
            raise HTTPException(status_code=403, detail="Tài khoản của bạn không có quyền truy cập màn hình này.")
        return user

    return dependency
