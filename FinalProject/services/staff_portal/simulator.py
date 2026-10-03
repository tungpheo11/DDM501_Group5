"""Admin traffic simulation: a rate-limited background job replaying stream CSV rows to the real API.

Same data as ``make simulate SCENARIO=normal|drift`` (``simulations/run_scenario.py``):

* ``normal``: ``data/processed/stream_normal.csv`` - cardholders aged 30+, same
  population as the drift reference, so no drift is expected;
* ``genz``: ``data/processed/stream_drifted.csv`` - 5,000 cardholders under 30
  (Gen-Z limit-increase campaign); enough of them push the AGE PSI over the
  threshold, the drift monitor reports drift and Alertmanager notifies.

Each request is one ``POST /api/v1/predict`` (one ``inference_logs`` row). Only one
job runs at a time in the portal process.
"""

from __future__ import annotations

import random
import threading
import time
from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from credit_risk.config import get_logger
from staff_portal.catalog import load_feature_rows
from staff_portal.scoring_client import ScoringApiError, ScoringClient
from staff_portal.store import utcnow

logger = get_logger(__name__)

SOURCE_LABELS: dict[str, str] = {
    "normal": "Lưu lượng bình thường",
    "genz": "Chủ thẻ dưới 30 tuổi (chiến dịch Gen-Z)",
}


class SimulationBusyError(Exception):
    """A simulation job is already running."""


class SimulationRejectedError(ValueError):
    """Invalid simulation request (unknown source or count out of range)."""


@dataclass
class SimulationJob:
    """Progress of one simulation run."""

    job_id: int
    source: str
    requested: int
    started_by: str
    started_at: datetime
    status: str = "running"
    attempted: int = 0
    succeeded: int = 0
    errors: int = 0
    decisions: Counter[str] = field(default_factory=Counter)
    last_error: str | None = None
    finished_at: datetime | None = None
    stopped_by: str | None = None

    @property
    def source_label(self) -> str:
        """Human-readable source."""
        return SOURCE_LABELS.get(self.source, self.source)

    @property
    def running(self) -> bool:
        """Whether the job is still sending requests."""
        return self.status == "running"

    def snapshot(self) -> dict[str, Any]:
        """Copy safe to render while the worker keeps updating the job."""
        return {
            "job_id": self.job_id,
            "source": self.source,
            "source_label": self.source_label,
            "requested": self.requested,
            "started_by": self.started_by,
            "started_at": self.started_at,
            "status": self.status,
            "running": self.running,
            "attempted": self.attempted,
            "succeeded": self.succeeded,
            "errors": self.errors,
            "decisions": {key: self.decisions.get(key, 0) for key in ("APPROVE", "REVIEW", "DECLINE")},
            "last_error": self.last_error,
            "finished_at": self.finished_at,
            "stopped_by": self.stopped_by,
        }


class SimulationManager:
    """Starts, tracks and stops the single background simulation job."""

    def __init__(
        self,
        client: ScoringClient,
        sources: dict[str, Path],
        *,
        rate_per_second: float = 20.0,
        max_count: int = 2000,
        on_finish: Callable[[SimulationJob], None] | None = None,
        seed: int | None = None,
    ) -> None:
        self._client = client
        self._sources = sources
        self._interval = 1.0 / rate_per_second if rate_per_second > 0 else 0.0
        self._max_count = max_count
        self._on_finish = on_finish
        self._seed = seed
        self._rows: dict[str, list[dict[str, Any]]] = {}
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._job: SimulationJob | None = None
        self._next_id = 1

    @property
    def max_count(self) -> int:
        """Largest accepted request count."""
        return self._max_count

    def _payloads(self, source: str, count: int) -> list[dict[str, Any]]:
        if source not in self._rows:
            self._rows[source] = load_feature_rows(self._sources[source])
        rows = self._rows[source]
        rng = random.Random(self._seed)
        if count <= len(rows):
            return rng.sample(rows, count)
        return [rng.choice(rows) for _ in range(count)]

    def current(self) -> dict[str, Any] | None:
        """Snapshot of the running or last finished job."""
        with self._lock:
            return self._job.snapshot() if self._job else None

    def is_running(self) -> bool:
        """Whether a job is in progress."""
        with self._lock:
            return self._job is not None and self._job.running

    def start(self, source: str, count: int, actor: str) -> dict[str, Any]:
        """Start a job; raises :class:`SimulationBusyError` or :class:`SimulationRejectedError`."""
        if source not in self._sources:
            raise SimulationRejectedError(f"Nguồn dữ liệu không hợp lệ: {source}")
        if not 1 <= count <= self._max_count:
            raise SimulationRejectedError(f"Số request phải từ 1 đến {self._max_count}.")
        with self._lock:
            if self._job is not None and self._job.running:
                raise SimulationBusyError()
            payloads = self._payloads(source, count)
            job = SimulationJob(
                job_id=self._next_id, source=source, requested=count, started_by=actor, started_at=utcnow()
            )
            self._next_id += 1
            self._job = job
            self._stop.clear()
            self._thread = threading.Thread(
                target=self._run, args=(job, payloads), name=f"portal-simulation-{job.job_id}", daemon=True
            )
            self._thread.start()
        logger.info(
            "Simulation started",
            extra={"event": "simulation_started", "source": source, "count": count, "actor": actor},
        )
        return job.snapshot()

    def stop(self, actor: str) -> bool:
        """Ask the running job to stop after the in-flight request; False when nothing runs."""
        with self._lock:
            if self._job is None or not self._job.running:
                return False
            self._job.stopped_by = actor
        self._stop.set()
        return True

    def wait(self, timeout: float | None = None) -> bool:
        """Block until the current job thread ends (tests and shutdown); True when it finished."""
        thread = self._thread
        if thread is None:
            return True
        thread.join(timeout)
        return not thread.is_alive()

    def shutdown(self) -> None:
        """Stop any running job and wait briefly for it."""
        self._stop.set()
        self.wait(timeout=5)

    def _run(self, job: SimulationJob, payloads: list[dict[str, Any]]) -> None:
        next_at = time.monotonic()
        try:
            for payload in payloads:
                if self._stop.is_set():
                    break
                try:
                    body = self._client.predict(payload).body
                except ScoringApiError as exc:
                    with self._lock:
                        job.attempted += 1
                        job.errors += 1
                        job.last_error = f"{exc.status_code} {exc.code}"
                else:
                    with self._lock:
                        job.attempted += 1
                        job.succeeded += 1
                        job.decisions[str(body.get("risk_decision", "?"))] += 1
                if self._interval:
                    next_at += self._interval
                    delay = next_at - time.monotonic()
                    if delay > 0 and self._stop.wait(delay):
                        break
            final_status = "stopped" if self._stop.is_set() else "completed"
        except Exception as exc:  # The job must always reach a terminal state.
            logger.exception("Simulation job failed")
            final_status = "failed"
            with self._lock:
                job.last_error = type(exc).__name__
        with self._lock:
            job.status = final_status
            job.finished_at = utcnow()
        logger.info(
            "Simulation finished",
            extra={
                "event": "simulation_finished",
                "status": final_status,
                "attempted": job.attempted,
                "errors": job.errors,
            },
        )
        if self._on_finish:
            try:
                self._on_finish(job)
            except Exception:  # Auditing must not crash the worker thread.
                logger.exception("Simulation on_finish callback failed")
