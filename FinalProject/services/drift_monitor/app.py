"""HTTP layer of the drift monitor: health, Prometheus metrics, on-demand analysis, reports.

Internal service (Compose network / localhost only): it has no authentication and
must not be published behind the public reverse proxy.

    uvicorn drift_monitor.app:app --host 0.0.0.0 --port 8085
"""

from __future__ import annotations

import threading
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, JSONResponse, Response
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest
from pydantic import BaseModel, Field

from credit_risk.config import Settings, get_logger, get_settings, setup_logging
from drift_monitor import __version__
from drift_monitor.monitor import DriftMonitor

logger = get_logger("drift_monitor")


class AnalyzeRequest(BaseModel):
    """Body of ``POST /analyze``."""

    window_size: int | None = Field(default=None, ge=10, le=10000, description="Latest inference logs to analyse")
    save_report: bool = Field(default=True, description="Persist the Evidently HTML report")


class _Scheduler:
    """Background thread running one analysis every ``interval`` seconds."""

    def __init__(self, monitor: DriftMonitor, interval: float) -> None:
        self._monitor = monitor
        self._interval = interval
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, name="drift-scheduler", daemon=True)

    def start(self) -> None:
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        self._thread.join(timeout=5)

    def _run(self) -> None:
        while not self._stop.wait(self._interval):
            try:
                self._monitor.analyze()
            except Exception:  # The loop must survive any single failed cycle.
                logger.exception("Scheduled drift analysis failed")


def create_app(
    settings: Settings | None = None, *, monitor: DriftMonitor | None = None, run_scheduler: bool = True
) -> FastAPI:
    """Build the drift-monitor app (``run_scheduler=False`` in tests)."""
    cfg = settings or get_settings()
    drift_monitor = monitor or DriftMonitor(cfg)

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        try:
            drift_monitor.load_reference()
        except Exception:  # /health reports the missing reference; the process stays up.
            logger.exception("Could not load the drift reference at startup")
        scheduler = _Scheduler(drift_monitor, cfg.drift.analysis_interval_seconds) if run_scheduler else None
        if scheduler:
            scheduler.start()
        yield
        if scheduler:
            scheduler.stop()

    app = FastAPI(
        title="Credit Risk Drift Monitor",
        version=__version__,
        description="Evidently + PSI drift analysis of the scoring API's inference logs against data/reference.",
        lifespan=lifespan,
    )
    app.state.monitor = drift_monitor

    @app.get("/", summary="Service index")
    def index() -> dict[str, Any]:
        return {
            "service": "drift-monitor",
            "version": __version__,
            "endpoints": ["/health", "/metrics", "/analyze", "/drift/latest", "/reference", "/reports"],
        }

    @app.get("/health", summary="Health: reference loaded")
    def health() -> JSONResponse:
        reference = drift_monitor.reference
        latest = drift_monitor.latest or {}
        body = {
            "status": "healthy" if reference is not None else "unhealthy",
            "reference_loaded": reference is not None,
            "reference_samples": len(reference.features) if reference else 0,
            "reference_model_version": reference.model_version if reference else None,
            "last_analysis_at": latest.get("analyzed_at"),
            "last_is_drifted": latest.get("is_drifted"),
        }
        return JSONResponse(status_code=200 if reference is not None else 503, content=body)

    @app.get("/metrics", summary="Prometheus metrics", include_in_schema=False)
    def metrics() -> Response:
        return Response(content=generate_latest(), media_type=CONTENT_TYPE_LATEST)

    @app.post("/analyze", summary="Run one drift analysis now")
    def analyze(request: AnalyzeRequest | None = None) -> dict[str, Any]:
        body = request or AnalyzeRequest()
        return drift_monitor.analyze(window_size=body.window_size, save_report=body.save_report)

    @app.get("/drift/latest", summary="Latest successful analysis")
    def latest() -> dict[str, Any]:
        if drift_monitor.latest is None:
            raise HTTPException(status_code=404, detail="No analysis has completed yet.")
        return drift_monitor.latest

    @app.get("/reference", summary="Reference window description")
    def reference_info() -> dict[str, Any]:
        reference = drift_monitor.reference
        if reference is None:
            raise HTTPException(status_code=503, detail="Reference not loaded.")
        return {
            "samples": len(reference.features),
            "features": list(reference.features.columns),
            "model_version": reference.model_version,
            "model_source": reference.model_source,
            "loaded_at": reference.loaded_at.isoformat(),
            "baseline_path": str(cfg.paths.baseline_data),
        }

    @app.post("/reference/refresh", summary="Re-score the reference with the current champion")
    def refresh_reference() -> dict[str, Any]:
        state = drift_monitor.load_reference()
        return {"status": "refreshed", "model_version": state.model_version, "model_source": state.model_source}

    @app.get("/reports", summary="Saved Evidently HTML reports")
    def reports() -> dict[str, Any]:
        items = drift_monitor.list_reports()
        return {"count": len(items), "reports": items}

    @app.get("/reports/{name}", summary="One saved Evidently HTML report", response_class=FileResponse)
    def report(name: str) -> FileResponse:
        path = drift_monitor.report_path(name)
        if path is None:
            raise HTTPException(status_code=404, detail="Report not found.")
        return FileResponse(path, media_type="text/html")

    return app


def _build_default_app() -> FastAPI:
    setup_logging()
    return create_app()


app = _build_default_app()
