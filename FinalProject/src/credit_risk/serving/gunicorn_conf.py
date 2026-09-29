"""gunicorn settings for the API container (ADR-0007).

    gunicorn --config python:credit_risk.serving.gunicorn_conf credit_risk.serving.app:app

``API_WORKERS`` (default 2) worker processes run the ASGI app; keep it equal to the
container CPU limit. ``API_WORKERS=1`` is the rollback path to single-worker serving.

The master prepares the directories shared by its workers before forking them:
Prometheus multiprocess files (``PROMETHEUS_MULTIPROC_DIR``, emptied on start) and
the model generation marker (``MODEL_SYNC_DIR``). Nothing here may import
``prometheus_client`` at module level: it picks its value backend at import time, and
workers inherit the master's modules.
"""

from __future__ import annotations

import os
import tempfile
from pathlib import Path
from typing import Any

_RUNTIME_DIR = Path(tempfile.gettempdir()) / "credit-risk-api"


def _int_env(name: str, default: int) -> int:
    value = os.environ.get(name, "").strip()
    return int(value) if value else default


bind = os.environ.get("API_BIND", "0.0.0.0:8000")
workers = max(1, _int_env("API_WORKERS", 2))
worker_class = "uvicorn_worker.UvicornWorker"
graceful_timeout = 20
# Covers the worker's startup (MLflow model download + SHAP warm-up) before its first heartbeat.
timeout = 120
keepalive = 5
accesslog = None
errorlog = "-"
loglevel = os.environ.get("LOG_LEVEL", "info").lower()
# Heartbeat files on tmpfs: fchmod on an overlay filesystem can stall workers.
worker_tmp_dir = "/dev/shm" if os.path.isdir("/dev/shm") else None


def on_starting(server: Any) -> None:
    """Master, before any worker exists: export shared paths and empty the metric files."""
    # Literal names: importing credit_risk.monitoring.multiprocess first would load prometheus_client.
    metrics_dir = Path(os.environ.setdefault("PROMETHEUS_MULTIPROC_DIR", str(_RUNTIME_DIR / "metrics")))
    sync_dir = Path(os.environ.setdefault("MODEL_SYNC_DIR", str(_RUNTIME_DIR / "model-sync")))
    os.environ["API_MASTER_PID"] = str(os.getpid())

    from credit_risk.monitoring.multiprocess import reset_multiprocess_dir

    reset_multiprocess_dir(metrics_dir)
    sync_dir.mkdir(parents=True, exist_ok=True)
    server.log.info("API workers=%s, metrics dir=%s, model sync dir=%s", workers, metrics_dir, sync_dir)


def child_exit(server: Any, worker: Any) -> None:
    """Master, after reaping a worker: stop exposing its live gauges."""
    from credit_risk.monitoring.multiprocess import mark_worker_dead

    mark_worker_dead(worker.pid)
