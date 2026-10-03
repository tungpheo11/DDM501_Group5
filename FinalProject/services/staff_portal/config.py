"""Portal settings: demo accounts, session, scoring API client, data sources and external links.

Shared values (database URL, scoring API URL/key, stream CSV paths, batch size cap)
come from the layered :mod:`credit_risk.config` settings; everything specific to
the portal is read from ``PORTAL_*`` environment variables.
"""

from __future__ import annotations

import os
import secrets
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import timedelta, timezone
from pathlib import Path
from typing import Literal

import bcrypt

from credit_risk.config import Settings, get_logger, get_settings

logger = get_logger(__name__)

Role = Literal["cskh", "analyst", "admin"]

ROLE_LABELS: dict[str, str] = {
    "cskh": "Nhân viên tiếp nhận yêu cầu (CSKH)",
    "analyst": "Chuyên viên rủi ro tín dụng",
    "admin": "Quản trị hệ thống",
}
ROLE_HOME: dict[str, str] = {"cskh": "/cskh", "analyst": "/analyst", "admin": "/admin"}

_ACCOUNT_DEFAULTS: tuple[tuple[Role, str, str, str], ...] = (
    ("cskh", "CSKH", "cskh", "Nguyễn Thu Trang"),
    ("analyst", "ANALYST", "chuyenvien", "Trần Minh Khoa"),
    ("admin", "ADMIN", "admin", "Lê Quốc Việt"),
)


@dataclass(frozen=True)
class PortalUser:
    """One demo account; only the bcrypt hash of its password is kept in memory."""

    username: str
    role: Role
    display_name: str
    password_hash: bytes = field(repr=False)


@dataclass(frozen=True)
class ExternalLinks:
    """Operator-facing URLs shown on the admin page (opened by the browser, not by the portal)."""

    grafana: str
    mlflow: str
    airflow: str
    alertmanager: str
    drift_monitor: str


@dataclass(frozen=True)
class PortalSettings:
    """Runtime configuration of the staff portal."""

    users: tuple[PortalUser, ...]
    session_secret: str = field(repr=False)
    api_url: str
    api_key: str = field(repr=False)
    database_url: str = field(repr=False)
    normal_stream: Path
    drifted_stream: Path
    links: ExternalLinks
    demo_mode: bool = False
    cookie_secure: bool = False
    session_max_age_seconds: int = 8 * 3600
    api_timeout_seconds: float = 10.0
    drift_monitor_url: str = ""
    catalog_size: int = 200
    catalog_drifted_share: float = 0.3
    catalog_seed: int = 2026
    batch_max_size: int = 500
    simulate_default_count: int = 200
    simulate_max_count: int = 2000
    simulate_rate_per_second: float = 20.0
    page_size: int = 25
    utc_offset_hours: int = 7
    login_max_failures: int = 5
    login_lockout_seconds: int = 300

    @property
    def tz(self) -> timezone:
        """Display time zone of the bank staff (timestamps are stored as naive UTC)."""
        return timezone(timedelta(hours=self.utc_offset_hours))

    def user(self, username: str) -> PortalUser | None:
        """Account with this username, if configured."""
        return next((user for user in self.users if user.username == username), None)


def hash_password(password: str, rounds: int = 12) -> bytes:
    """Bcrypt hash of ``password`` (bcrypt only uses the first 72 bytes)."""
    return bcrypt.hashpw(password.encode("utf-8")[:72], bcrypt.gensalt(rounds=rounds))


def _as_bool(raw: str | None, default: bool) -> bool:
    if raw is None or raw.strip() == "":
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _get(env: Mapping[str, str], name: str, default: str) -> str:
    value = env.get(name)
    return value if value not in (None, "") else default


def load_users(env: Mapping[str, str], rounds: int = 12) -> tuple[PortalUser, ...]:
    """Build the three role accounts from ``PORTAL_<ROLE>_{USERNAME,PASSWORD,PASSWORD_HASH,NAME}``.

    A ready-made bcrypt hash (``*_PASSWORD_HASH``) wins over a plain password, which is
    hashed once at startup and then discarded. An account without either is disabled.
    """
    users: list[PortalUser] = []
    for role, prefix, default_username, default_name in _ACCOUNT_DEFAULTS:
        username = _get(env, f"PORTAL_{prefix}_USERNAME", default_username)
        configured_hash = env.get(f"PORTAL_{prefix}_PASSWORD_HASH", "").strip()
        password = env.get(f"PORTAL_{prefix}_PASSWORD", "")
        if configured_hash:
            password_hash = configured_hash.encode("utf-8")
        elif password:
            password_hash = hash_password(password, rounds)
        else:
            logger.warning("Portal account for role %s is disabled: no password configured", role)
            continue
        display_name = _get(env, f"PORTAL_{prefix}_NAME", default_name)
        users.append(PortalUser(username=username, role=role, display_name=display_name, password_hash=password_hash))
    return tuple(users)


def load_portal_settings(base: Settings | None = None, env: Mapping[str, str] | None = None) -> PortalSettings:
    """Read the portal configuration from ``env`` (default: the process environment)."""
    cfg = base or get_settings()
    source: Mapping[str, str] = os.environ if env is None else env

    session_secret = source.get("PORTAL_SESSION_SECRET", "")
    if not session_secret:
        session_secret = secrets.token_urlsafe(32)
        logger.warning("PORTAL_SESSION_SECRET is not set; using a random secret (sessions end on restart)")

    links = ExternalLinks(
        grafana=_get(source, "PORTAL_GRAFANA_URL", "http://localhost:13000"),
        mlflow=_get(source, "PORTAL_MLFLOW_URL", "http://localhost:15040"),
        airflow=_get(source, "PORTAL_AIRFLOW_URL", "http://localhost:18080"),
        alertmanager=_get(source, "PORTAL_ALERTMANAGER_URL", "http://localhost:19093"),
        drift_monitor=_get(source, "PORTAL_DRIFT_MONITOR_PUBLIC_URL", "http://localhost:18085"),
    )
    return PortalSettings(
        users=load_users(source, rounds=int(_get(source, "PORTAL_BCRYPT_ROUNDS", "12"))),
        session_secret=session_secret,
        api_url=_get(source, "PORTAL_API_URL", cfg.serving.api_url).rstrip("/"),
        api_key=_get(source, "PORTAL_API_KEY", cfg.serving.client_api_key),
        database_url=_get(source, "PORTAL_DATABASE_URL", cfg.database.url),
        normal_stream=cfg.paths.normal_stream,
        drifted_stream=cfg.paths.drifted_stream,
        links=links,
        demo_mode=_as_bool(source.get("PORTAL_DEMO_MODE"), False),
        cookie_secure=_as_bool(source.get("PORTAL_COOKIE_SECURE"), False),
        session_max_age_seconds=int(_get(source, "PORTAL_SESSION_MAX_AGE_SECONDS", str(8 * 3600))),
        api_timeout_seconds=float(_get(source, "PORTAL_API_TIMEOUT_SECONDS", "10")),
        drift_monitor_url=_get(source, "DRIFT_MONITOR_URL", "").rstrip("/"),
        batch_max_size=cfg.serving.batch_max_size,
        simulate_rate_per_second=float(_get(source, "PORTAL_SIMULATE_RATE_PER_SECOND", "20")),
        utc_offset_hours=int(_get(source, "PORTAL_UTC_OFFSET_HOURS", "7")),
    )
