"""Per-request context shared by the serving middleware and the log formatter."""

from __future__ import annotations

from contextvars import ContextVar

request_id_var: ContextVar[str | None] = ContextVar("request_id", default=None)


def get_request_id() -> str | None:
    """Request id of the request being handled in the current context, if any."""
    return request_id_var.get()
