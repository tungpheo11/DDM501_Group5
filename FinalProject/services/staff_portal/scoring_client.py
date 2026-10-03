"""HTTP client of the scoring API, used server-side like any other backend client.

Every call goes through the real ``/api/v1`` endpoints, so portal traffic shows up
in Prometheus metrics, Grafana, ``inference_logs`` and the drift monitor. The API
key is attached here and never reaches the browser.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any

import httpx

from credit_risk.config import get_logger

logger = get_logger(__name__)


class ScoringApiError(Exception):
    """Non-2xx answer from the scoring API, or the API is unreachable."""

    def __init__(self, status_code: int, code: str, message: str) -> None:
        super().__init__(f"{status_code} {code}: {message}")
        self.status_code = status_code
        self.code = code
        self.message = message


@dataclass(frozen=True)
class ApiResult:
    """Decoded JSON body plus the round-trip time measured by the portal."""

    body: dict[str, Any]
    roundtrip_ms: float


class ScoringClient:
    """Thin wrapper over ``httpx.Client`` with the API key header preset."""

    def __init__(
        self,
        base_url: str,
        api_key: str,
        *,
        timeout_seconds: float = 10.0,
        client: httpx.Client | None = None,
    ) -> None:
        self._owns_client = client is None
        self._client = client or httpx.Client(base_url=base_url, timeout=timeout_seconds)
        self._auth = {"X-API-Key": api_key} if api_key else {}

    def close(self) -> None:
        """Release the connection pool (only when this object created it)."""
        if self._owns_client:
            self._client.close()

    def _request(self, method: str, path: str, *, json: Any = None, auth: bool = True) -> ApiResult:
        start = time.perf_counter()
        try:
            response = self._client.request(method, path, json=json, headers=self._auth if auth else None)
        except httpx.HTTPError as exc:
            logger.warning("Scoring API unreachable: %s %s (%s)", method, path, type(exc).__name__)
            raise ScoringApiError(503, "API_UNREACHABLE", "Không kết nối được API chấm điểm.") from exc
        roundtrip_ms = round((time.perf_counter() - start) * 1000, 1)
        try:
            body = response.json()
        except ValueError:
            body = {}
        if response.status_code >= 400:
            code = str(body.get("code", "HTTP_ERROR")) if isinstance(body, dict) else "HTTP_ERROR"
            message = str(body.get("message", response.reason_phrase)) if isinstance(body, dict) else ""
            raise ScoringApiError(response.status_code, code, message)
        return ApiResult(body=body if isinstance(body, dict) else {"items": body}, roundtrip_ms=roundtrip_ms)

    def predict(self, features: dict[str, Any]) -> ApiResult:
        """``POST /api/v1/predict`` for one cardholder."""
        return self._request("POST", "/api/v1/predict", json=features)

    def predict_batch(self, cardholders: list[dict[str, Any]]) -> ApiResult:
        """``POST /api/v1/predict/batch`` (field ``cardholders``)."""
        return self._request("POST", "/api/v1/predict/batch", json={"cardholders": cardholders})

    def explain(self, features: dict[str, Any]) -> ApiResult:
        """``POST /api/v1/explain`` (SHAP attributions)."""
        return self._request("POST", "/api/v1/explain", json=features)

    def model_info(self) -> ApiResult:
        """``GET /api/v1/model/info``."""
        return self._request("GET", "/api/v1/model/info")

    def readiness(self) -> dict[str, Any]:
        """``GET /health/ready`` (unauthenticated); 503 bodies are returned, not raised."""
        try:
            return self._request("GET", "/health/ready", auth=False).body
        except ScoringApiError as exc:
            return {"status": "not_ready" if exc.status_code == 503 else "unreachable", "reasons": [exc.message]}
