"""Converge the served model across gunicorn workers after a hot reload.

``POST /api/v1/model/reload`` reaches a single worker. When that reload succeeds
the worker publishes a new *generation* marker in a directory shared by all
workers of the container; every other worker polls the marker and reloads the
champion in the background when it sees a generation it has not applied yet.
A failed reload publishes nothing, so each worker keeps its own safe-reload
semantics (previous model kept, registry model never downgraded to the fallback).
"""

from __future__ import annotations

import json
import os
import tempfile
import threading
import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Protocol

from credit_risk.config import get_logger

logger = get_logger(__name__)

MARKER_FILE = "model_generation.json"


@dataclass(frozen=True)
class Generation:
    """One published reload."""

    token: str
    model_version: str
    pid: int
    written_at: str


class _Reloader(Protocol):
    def load_champion(self, *, broadcast: bool = False) -> object: ...


class ModelGenerationSync:
    """Reads and atomically writes the shared generation marker; tracks what this worker applied."""

    def __init__(self, directory: Path, *, retry_seconds: float = 10.0) -> None:
        self.directory = directory
        self.path = directory / MARKER_FILE
        self._retry_seconds = retry_seconds
        self._lock = threading.Lock()
        self._applied: str | None = None
        self._retry_token: str | None = None
        self._retry_after = 0.0

    def read(self) -> Generation | None:
        """Current marker, or None when absent or unreadable."""
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
            return Generation(
                token=str(raw["token"]),
                model_version=str(raw["model_version"]),
                pid=int(raw["pid"]),
                written_at=str(raw["written_at"]),
            )
        except (OSError, ValueError, KeyError, TypeError):
            return None

    def publish(self, model_version: str) -> Generation:
        """Write a new generation (write to a temp file, then rename) and mark it applied here."""
        generation = Generation(
            token=uuid.uuid4().hex,
            model_version=model_version,
            pid=os.getpid(),
            written_at=datetime.now(UTC).isoformat(),
        )
        with self._lock:
            # Recorded before the rename so this worker's own poller never reloads it again.
            self._applied = generation.token
            self.directory.mkdir(parents=True, exist_ok=True)
            fd, tmp_name = tempfile.mkstemp(dir=self.directory, prefix=".generation-", suffix=".tmp")
            try:
                with os.fdopen(fd, "w", encoding="utf-8") as handle:
                    json.dump(generation.__dict__, handle)
                os.replace(tmp_name, self.path)
            except BaseException:
                Path(tmp_name).unlink(missing_ok=True)
                raise
        logger.info(
            "Published model generation",
            extra={"event": "model_generation_published", "model_version": model_version},
        )
        return generation

    def mark_current_applied(self) -> None:
        """Adopt the existing marker as applied (a freshly started worker already loaded the champion)."""
        current = self.read()
        with self._lock:
            self._applied = current.token if current else None

    def pending(self) -> Generation | None:
        """A generation this worker has not applied yet, unless it is backing off after a failure."""
        current = self.read()
        with self._lock:
            if current is None or current.token == self._applied:
                return None
            if current.token == self._retry_token and time.monotonic() < self._retry_after:
                return None
            return current

    def acknowledge(self, generation: Generation, *, success: bool) -> None:
        """Record the outcome of applying ``generation``."""
        with self._lock:
            if success:
                self._applied = generation.token
                self._retry_token = None
            else:
                self._retry_token = generation.token
                self._retry_after = time.monotonic() + self._retry_seconds


class ModelSyncWatcher:
    """Daemon thread polling the marker and reloading the champion when it changes."""

    def __init__(
        self,
        sync: ModelGenerationSync,
        manager: _Reloader,
        *,
        interval_seconds: float = 1.0,
        on_reload: Callable[[], None] | None = None,
    ) -> None:
        self._sync = sync
        self._manager = manager
        self._interval = interval_seconds
        self._on_reload = on_reload
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        """Start polling; call :meth:`ModelGenerationSync.mark_current_applied` before the initial load."""
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, name="model-sync", daemon=True)
        self._thread.start()

    def stop(self, timeout: float = 5.0) -> None:
        """Stop polling and wait for an in-progress reload to finish."""
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout)
            self._thread = None

    def check_once(self) -> bool:
        """Apply a pending generation, if any; return whether a reload was attempted."""
        generation = self._sync.pending()
        if generation is None:
            return False
        logger.info(
            "Model generation changed; reloading champion",
            extra={"event": "model_generation_seen", "model_version": generation.model_version},
        )
        outcome = self._manager.load_champion()
        success = bool(getattr(outcome, "success", False))
        self._sync.acknowledge(generation, success=success)
        if self._on_reload is not None:
            self._on_reload()
        return True

    def _run(self) -> None:
        while not self._stop.wait(self._interval):
            try:
                self.check_once()
            except Exception:  # The poller must survive any reload error.
                logger.exception("Model generation check failed", extra={"event": "model_sync_error"})
