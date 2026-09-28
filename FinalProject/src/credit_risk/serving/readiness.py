"""Readiness evaluation: served model + MLflow registry + inference-log database.

``ready``      model from the MLflow registry and every dependency reachable.
``degraded``   can serve, but on the local fallback model or with a dependency down.
``not_ready``  no model loaded (HTTP 503).

Dependency probes are cached so frequent health checks never hammer MLflow/Postgres.
"""

from __future__ import annotations

import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Literal

from credit_risk.config import Settings
from credit_risk.serving import database
from credit_risk.serving.model_loader import ModelManager
from credit_risk.utils.network import is_service_reachable

CheckStatus = Literal["ok", "degraded", "down"]
ReadinessStatus = Literal["ready", "degraded", "not_ready"]


@dataclass(frozen=True)
class CheckResult:
    """State of one dependency."""

    status: CheckStatus
    detail: str | None = None


@dataclass(frozen=True)
class ReadinessReport:
    """Aggregated readiness."""

    status: ReadinessStatus
    reasons: list[str]
    checks: dict[str, CheckResult]

    @property
    def http_status(self) -> int:
        """200 when the instance can serve traffic, else 503."""
        return 503 if self.status == "not_ready" else 200


class _CachedCheck:
    def __init__(self, check: Callable[[], bool], ttl_seconds: float) -> None:
        self._check = check
        self._ttl = ttl_seconds
        self._value: bool | None = None
        self._expires_at = 0.0
        self._lock = threading.Lock()

    def __call__(self) -> bool:
        with self._lock:
            now = time.monotonic()
            if self._value is None or now >= self._expires_at:
                self._value = self._check()
                self._expires_at = now + self._ttl
            return self._value

    def invalidate(self) -> None:
        with self._lock:
            self._value = None


class ReadinessProbe:
    """Computes :class:`ReadinessReport` for the app."""

    def __init__(self, settings: Settings, model_manager: ModelManager) -> None:
        ttl = settings.serving.readiness_cache_seconds
        timeout = settings.serving.mlflow_probe_timeout_seconds
        tracking_uri = settings.mlflow.tracking_uri
        self._model_manager = model_manager
        self._mlflow = _CachedCheck(lambda: is_service_reachable(tracking_uri, timeout=timeout), ttl)
        self._database = _CachedCheck(database.ping, ttl)

    def invalidate(self) -> None:
        """Force fresh dependency probes on the next evaluation (e.g. after a reload)."""
        self._mlflow.invalidate()
        self._database.invalidate()

    def evaluate(self) -> ReadinessReport:
        """Evaluate model state and (cached) dependency reachability."""
        reasons: list[str] = []
        loaded = self._model_manager.current

        if loaded is None:
            model_check = CheckResult("down", self._model_manager.last_error or "No model loaded")
            reasons.append("model_not_loaded")
        elif loaded.degraded:
            model_check = CheckResult("degraded", f"{loaded.source} version {loaded.version}")
            reasons.append("model_served_from_local_fallback")
        else:
            model_check = CheckResult("ok", f"{loaded.source} version {loaded.version}")

        if self._mlflow():
            mlflow_check = CheckResult("ok")
        else:
            mlflow_check = CheckResult("down", "tracking server unreachable")
            reasons.append("mlflow_unreachable")

        if self._database():
            database_check = CheckResult("ok")
        else:
            database_check = CheckResult("down", "inference-log database unreachable; predictions are not logged")
            reasons.append("database_unavailable")

        status: ReadinessStatus
        if loaded is None:
            status = "not_ready"
        elif reasons:
            status = "degraded"
        else:
            status = "ready"
        return ReadinessReport(
            status=status,
            reasons=reasons,
            checks={"model": model_check, "mlflow": mlflow_check, "database": database_check},
        )
