"""Pure-ASGI request middleware: request id, access log, HTTP metrics, last-resort 500s."""

from __future__ import annotations

import re
import time
import uuid

from starlette.datastructures import MutableHeaders
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from credit_risk.config import get_logger
from credit_risk.monitoring.metrics import HTTP_LATENCY, HTTP_REQUESTS
from credit_risk.serving.errors import error_response
from credit_risk.utils.request_context import request_id_var

REQUEST_ID_HEADER = "X-Request-ID"
_VALID_REQUEST_ID = re.compile(r"^[A-Za-z0-9._\-]{1,64}$")

logger = get_logger("credit_risk.serving.access")


def new_request_id() -> str:
    """Generate an opaque request id."""
    return f"req_{uuid.uuid4().hex}"


def _resolve_request_id(scope: Scope) -> str:
    for name, value in scope.get("headers", []):
        if name == b"x-request-id":
            candidate = value.decode("latin-1").strip()
            if _VALID_REQUEST_ID.match(candidate):
                return candidate
            break
    return new_request_id()


def _endpoint_label(scope: Scope) -> str:
    # Route templates keep label cardinality bounded (never the raw path).
    route = scope.get("route")
    path = getattr(route, "path", None)
    return path if isinstance(path, str) else "unmatched"


class RequestContextMiddleware:
    """Assign/propagate ``X-Request-ID`` and record metrics + one access log line per request."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        """Handle one ASGI connection."""
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        request_id = _resolve_request_id(scope)
        token = request_id_var.set(request_id)
        scope.setdefault("state", {})["request_id"] = request_id
        status_code = 500
        response_started = False
        start = time.perf_counter()

        async def send_wrapper(message: Message) -> None:
            nonlocal status_code, response_started
            if message["type"] == "http.response.start":
                response_started = True
                status_code = int(message["status"])
                MutableHeaders(scope=message)[REQUEST_ID_HEADER] = request_id
            await send(message)

        try:
            await self.app(scope, receive, send_wrapper)
        except Exception:
            logger.exception("Unhandled error while serving request", extra={"event": "unhandled_error"})
            if response_started:
                raise
            status_code = 500
            response = error_response(500, "INTERNAL_ERROR", "Internal server error.")
            response.headers[REQUEST_ID_HEADER] = request_id
            await response(scope, receive, send)
        finally:
            elapsed = time.perf_counter() - start
            method = scope.get("method", "")
            endpoint = _endpoint_label(scope)
            HTTP_REQUESTS.labels(method=method, endpoint=endpoint, status=str(status_code)).inc()
            HTTP_LATENCY.labels(method=method, endpoint=endpoint).observe(elapsed)
            logger.info(
                "%s %s -> %s",
                method,
                endpoint,
                status_code,
                extra={
                    "event": "http_request",
                    "method": method,
                    "endpoint": endpoint,
                    "status": status_code,
                    "duration_ms": round(elapsed * 1000, 2),
                },
            )
            request_id_var.reset(token)
