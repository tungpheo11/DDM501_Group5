"""Load test: run the Locust scenario headless against the live API and check the latency SLO.

Locust is started in a subprocess because it monkey-patches the standard library with gevent on import.
Tunables (environment): ``LOAD_USERS`` (10), ``LOAD_SPAWN_RATE`` (10), ``LOAD_DURATION`` (60s),
``LOAD_P95_MS`` (100, the p95 SLO of ``/api/v1/predict``), ``E2E_API_URL``, ``LOAD_REPORT_NAME`` (locust).
Reports: ``reports/load/<name>_report.html``, ``<name>_stats.csv`` and ``<name>_summary.json``
(``make test-load-stress`` writes ``locust_stress_*`` so the 10-user baseline is kept).
"""

from __future__ import annotations

import csv
import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest
import requests

pytestmark = pytest.mark.load

PROJECT_ROOT = Path(__file__).resolve().parents[2]
LOCUSTFILE = Path(__file__).with_name("locustfile.py")
REPORT_DIR = PROJECT_ROOT / "reports" / "load"
PREDICT = "POST /api/v1/predict"


def _api_url() -> str:
    if os.environ.get("E2E_API_URL"):
        return os.environ["E2E_API_URL"]
    port = "18020"
    env_file = PROJECT_ROOT / ".env"
    if env_file.is_file():
        for line in env_file.read_text(encoding="utf-8").splitlines():
            if line.startswith("API_PORT="):
                port = line.partition("=")[2].strip() or port
    return f"http://localhost:{port}"


@pytest.fixture(scope="module")
def locust_stats() -> dict[str, dict[str, str]]:
    if importlib.util.find_spec("locust") is None:
        pytest.skip("locust is not installed (uv sync --dev)")
    api_url = _api_url()
    try:
        requests.get(f"{api_url}/health/ready", timeout=3).raise_for_status()
    except requests.RequestException as exc:
        pytest.skip(f"API not ready at {api_url} ({exc.__class__.__name__}); run `make up`")

    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    name = os.environ.get("LOAD_REPORT_NAME", "locust")
    prefix = REPORT_DIR / name
    cmd = [
        sys.executable,
        "-m",
        "locust",
        "-f",
        str(LOCUSTFILE),
        "--headless",
        "--only-summary",
        "--host",
        api_url,
        "-u",
        os.environ.get("LOAD_USERS", "10"),
        "-r",
        os.environ.get("LOAD_SPAWN_RATE", "10"),
        "-t",
        os.environ.get("LOAD_DURATION", "60s"),
        "--csv",
        str(prefix),
        "--html",
        str(REPORT_DIR / f"{name}_report.html"),
        "--exit-code-on-error",
        "0",
    ]
    completed = subprocess.run(cmd, cwd=PROJECT_ROOT, capture_output=True, text=True, timeout=900, check=False)
    (REPORT_DIR / f"{name}_output.txt").write_text(completed.stdout + completed.stderr, encoding="utf-8")
    assert completed.returncode == 0, completed.stderr[-2000:]

    with (REPORT_DIR / f"{name}_stats.csv").open(encoding="utf-8") as handle:
        rows = {row["Name"]: row for row in csv.DictReader(handle)}

    summary = {
        name: {
            "requests": int(row["Request Count"]),
            "failures": int(row["Failure Count"]),
            "rps": round(float(row["Requests/s"]), 2),
            "p50_ms": float(row["50%"]),
            "p95_ms": float(row["95%"]),
            "p99_ms": float(row["99%"]),
            "max_ms": round(float(row["Max Response Time"]), 1),
        }
        for name, row in rows.items()
    }
    summary["config"] = {
        "users": int(os.environ.get("LOAD_USERS", "10")),
        "spawn_rate": int(os.environ.get("LOAD_SPAWN_RATE", "10")),
        "duration": os.environ.get("LOAD_DURATION", "60s"),
        "api_url": api_url,
    }
    (REPORT_DIR / f"{name}_summary.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    return rows


def test_load_has_no_failed_requests(locust_stats: dict[str, dict[str, str]]) -> None:
    aggregated = locust_stats["Aggregated"]
    assert int(aggregated["Request Count"]) > 0
    assert int(aggregated["Failure Count"]) == 0


def test_predict_p95_meets_slo(locust_stats: dict[str, dict[str, str]]) -> None:
    slo_ms = float(os.environ.get("LOAD_P95_MS", "100"))
    assert float(locust_stats[PREDICT]["95%"]) <= slo_ms


def test_throughput_is_sustained(locust_stats: dict[str, dict[str, str]]) -> None:
    users = int(os.environ.get("LOAD_USERS", "10"))
    # Each user waits 0.1-0.5 s between calls, so a healthy API sustains well over one request/s per user.
    assert float(locust_stats["Aggregated"]["Requests/s"]) >= users
