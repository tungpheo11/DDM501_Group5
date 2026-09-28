"""Service health check: probe every service of the stack and report failures.

Runs every ``HEALTH_CHECK_SCHEDULE`` (default 5 minutes). Each target is probed
in its own mapped task so one slow service does not hide the others; the
summary fails the run (and notifies) when any critical service is unhealthy,
and warns when the API serves the local fallback model instead of the registry
champion.
"""

from __future__ import annotations

import time
from typing import Any

import requests
from airflow import DAG
from airflow.decorators import task
from airflow.exceptions import AirflowFailException
from utils.common import (
    ALERTMANAGER_URL,
    API_URL,
    DEFAULT_ARGS,
    DRIFT_MONITOR_URL,
    HEALTH_CHECK_SCHEDULE,
    HTTP_TIMEOUT_SECONDS,
    MLFLOW_URL,
    PROMETHEUS_URL,
    START_DATE,
    api_headers,
)
from utils.notify import escape, notify

TARGETS: list[dict[str, Any]] = [
    {"name": "api", "url": f"{API_URL}/health/ready", "critical": True},
    {"name": "api-model", "url": f"{API_URL}/api/v1/model/info", "critical": True, "auth": True},
    {"name": "mlflow", "url": f"{MLFLOW_URL}/health", "critical": True},
    {"name": "drift-monitor", "url": f"{DRIFT_MONITOR_URL}/health", "critical": False},
    {"name": "prometheus", "url": f"{PROMETHEUS_URL}/-/healthy", "critical": False},
    {"name": "alertmanager", "url": f"{ALERTMANAGER_URL}/-/healthy", "critical": False},
]

with DAG(
    dag_id="service_health_check",
    description="Probe API, model, MLflow, drift monitor, Prometheus and Alertmanager",
    schedule=HEALTH_CHECK_SCHEDULE,
    start_date=START_DATE,
    catchup=False,
    max_active_runs=1,
    default_args={**DEFAULT_ARGS, "retries": 0},
    tags=["mlops", "monitoring"],
    doc_md=__doc__,
) as dag:

    @task(map_index_template="{{ task.op_kwargs['target']['name'] }}")
    def probe(target: dict[str, Any]) -> dict[str, Any]:
        started = time.perf_counter()
        headers = api_headers() if target.get("auth") else {}
        result: dict[str, Any] = {"name": target["name"], "critical": target["critical"]}
        try:
            response = requests.get(target["url"], headers=headers, timeout=HTTP_TIMEOUT_SECONDS)
            result["status_code"] = response.status_code
            result["healthy"] = response.status_code == 200
            if target["name"] == "api-model" and result["healthy"]:
                info = response.json()
                result["model_version"] = info.get("model_version")
                result["source"] = info.get("source")
                result["degraded"] = bool(info.get("degraded"))
        except requests.RequestException as exc:
            result["healthy"] = False
            result["error"] = type(exc).__name__
        result["latency_ms"] = round((time.perf_counter() - started) * 1000, 1)
        print(result)
        return result

    @task
    def active_alerts() -> list[str]:
        try:
            response = requests.get(f"{PROMETHEUS_URL}/api/v1/alerts", timeout=HTTP_TIMEOUT_SECONDS)
            response.raise_for_status()
            alerts = response.json()["data"]["alerts"]
        except (requests.RequestException, KeyError, ValueError) as exc:
            print(f"Could not read Prometheus alerts: {exc}")
            return []
        return sorted({a["labels"]["alertname"] for a in alerts if a.get("state") == "firing"})

    @task
    def summarize(results: list[dict[str, Any]], firing: list[str]) -> dict[str, Any]:
        results = list(results)
        unhealthy = [r for r in results if not r["healthy"]]
        critical = [r["name"] for r in unhealthy if r["critical"]]
        degraded = [r for r in results if r.get("degraded")]
        for r in results:
            print(
                f"{r['name']:<14} {'OK' if r['healthy'] else 'FAIL':<4} {r.get('status_code', '-')} "
                f"{r['latency_ms']} ms {r.get('error', '')}"
            )
        print(f"Firing alerts: {firing or 'none'}")

        if unhealthy or degraded:
            notify(
                "ServiceHealthCheck",
                "[HEALTH] " + (f"critical services down: {', '.join(critical)}" if critical else "degraded services"),
                [f"{escape(r['name'])}: {escape(r.get('error') or r.get('status_code'))}" for r in unhealthy]
                + [f"api-model: serving {escape(r.get('source'))} (degraded)" for r in degraded]
                + [f"Firing alerts: {escape(', '.join(firing) or 'none')}"],
                severity="critical" if critical else "warning",
                labels={"dag_id": "service_health_check"},
            )
        if critical:
            raise AirflowFailException(f"Critical services unhealthy: {critical}")
        return {"healthy": len(results) - len(unhealthy), "total": len(results), "firing_alerts": firing}

    summarize(probe.expand(target=TARGETS), active_alerts())
