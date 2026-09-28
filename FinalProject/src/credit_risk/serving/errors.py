"""Uniform error contract: every non-2xx response is an :class:`ErrorResponse` body."""

from __future__ import annotations

from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from credit_risk.utils.request_context import get_request_id

_HTTP_STATUS_CODES = {
    400: "BAD_REQUEST",
    401: "UNAUTHORIZED",
    403: "FORBIDDEN",
    404: "NOT_FOUND",
    405: "METHOD_NOT_ALLOWED",
    413: "PAYLOAD_TOO_LARGE",
    415: "UNSUPPORTED_MEDIA_TYPE",
    422: "VALIDATION_ERROR",
    429: "TOO_MANY_REQUESTS",
    500: "INTERNAL_ERROR",
    503: "SERVICE_UNAVAILABLE",
}


class ApiError(Exception):
    """Domain error rendered as ``{code, message, details, request_id}``."""

    def __init__(
        self,
        status_code: int,
        code: str,
        message: str,
        details: Any = None,
        headers: dict[str, str] | None = None,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.code = code
        self.message = message
        self.details = details
        self.headers = headers


def error_body(code: str, message: str, details: Any = None) -> dict[str, Any]:
    """Build the error payload for the current request."""
    return {"code": code, "message": message, "details": details, "request_id": get_request_id()}


def error_response(
    status_code: int, code: str, message: str, details: Any = None, headers: dict[str, str] | None = None
) -> JSONResponse:
    """JSON response carrying the error contract."""
    return JSONResponse(status_code=status_code, content=error_body(code, message, details), headers=headers)


def _validation_details(exc: RequestValidationError) -> list[dict[str, Any]]:
    # The rejected ``input`` is dropped on purpose: it would echo applicant data
    # back into responses and into any log line built from them.
    details = []
    for err in exc.errors():
        item: dict[str, Any] = {
            "field": ".".join(str(part) for part in err.get("loc", ()) if part != "body"),
            "message": err.get("msg", ""),
            "type": err.get("type", ""),
        }
        if err.get("ctx"):
            item["constraint"] = {key: str(value) for key, value in err["ctx"].items()}
        details.append(item)
    return details


async def _api_error_handler(_: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, ApiError)
    return error_response(exc.status_code, exc.code, exc.message, exc.details, exc.headers)


async def _validation_error_handler(_: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, RequestValidationError)
    return error_response(422, "VALIDATION_ERROR", "Request validation failed.", _validation_details(exc))


async def _http_error_handler(_: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, StarletteHTTPException)
    code = _HTTP_STATUS_CODES.get(exc.status_code, f"HTTP_{exc.status_code}")
    message = exc.detail if isinstance(exc.detail, str) else code.replace("_", " ").capitalize()
    return error_response(exc.status_code, code, message, headers=getattr(exc, "headers", None))


def register_error_handlers(app: FastAPI) -> None:
    """Install the handlers that map every framework/domain error onto the contract."""
    app.add_exception_handler(ApiError, _api_error_handler)
    app.add_exception_handler(RequestValidationError, _validation_error_handler)
    app.add_exception_handler(StarletteHTTPException, _http_error_handler)
