"""API-key authentication for the versioned API (header ``X-API-Key``)."""

from __future__ import annotations

import hmac

from fastapi import Request, Security
from fastapi.security import APIKeyHeader

from credit_risk.config import Settings, get_logger
from credit_risk.monitoring.metrics import AUTH_FAILURES
from credit_risk.serving.errors import ApiError

API_KEY_HEADER = "X-API-Key"

api_key_scheme = APIKeyHeader(
    name=API_KEY_HEADER,
    auto_error=False,
    scheme_name="ApiKeyAuth",
    description="Static API key issued to each client. Configure server keys with the `API_KEYS` env var.",
)

logger = get_logger(__name__)


def is_valid_api_key(candidate: str, keys: tuple[str, ...]) -> bool:
    """Constant-time comparison against every configured key."""
    encoded = candidate.encode("utf-8")
    matched = False
    for key in keys:
        matched |= hmac.compare_digest(encoded, key.encode("utf-8"))
    return matched


async def require_api_key(request: Request, api_key: str | None = Security(api_key_scheme)) -> None:
    """Reject the request unless it carries a configured API key (no-op when auth is disabled)."""
    settings: Settings = request.app.state.settings
    if not settings.serving.auth_enabled:
        return
    if not api_key:
        AUTH_FAILURES.labels(reason="missing").inc()
        raise ApiError(
            401,
            "MISSING_API_KEY",
            f"Missing {API_KEY_HEADER} header.",
            headers={"WWW-Authenticate": "ApiKey"},
        )
    if not is_valid_api_key(api_key, settings.serving.api_keys):
        AUTH_FAILURES.labels(reason="invalid").inc()
        logger.warning("Rejected invalid API key", extra={"event": "auth_rejected"})
        raise ApiError(403, "INVALID_API_KEY", "The provided API key is not valid.")
