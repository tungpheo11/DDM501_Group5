"""Drift monitoring: Evidently analysis of recent inference logs; retrain on drift.

Calls the drift monitor (``POST /analyze``), which compares the latest
``window_size`` inference logs with ``data/reference`` (key-feature PSI +
Evidently drift share) and publishes the result as Prometheus metrics.

* dataset drift -> notification + trigger ``model_retrain`` (unless a retrain
  ran within ``retrain_cooldown_minutes`` or is still running);
* prediction-distribution shift alone -> notification only (alert
  ``PredictionDistributionShift``), since a score shift without input drift
  points at the model or upstream data, not at stale training data;
* too few logged predictions / database unavailable -> skipped, not failed.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from airflow import DAG
from airflow.decorators import task
from airflow.exceptions import AirflowFailException
from airflow.models.param import Param
from airflow.operators.empty import EmptyOperator
from airflow.operators.trigger_dagrun import TriggerDagRunOperator
from utils.common import (
    DEFAULT_ARGS,
    DRIFT_MONITOR_PUBLIC_URL,
    DRIFT_MONITOR_URL,
    DRIFT_MONITORING_SCHEDULE,
    DRIFT_WINDOW_SIZE,
    RETRAIN_COOLDOWN_MINUTES,
    START_DATE,
    http_json,
)
from utils.notify import escape, notify, task_failure_callback

ANALYZE_TIMEOUT_SECONDS = 120

with DAG(
    dag_id="drift_monitoring",
    description="Evidently drift analysis of recent inference logs; trigger model_retrain on drift",
    schedule=DRIFT_MONITORING_SCHEDULE,
    start_date=START_DATE,
    catchup=False,
    max_active_runs=1,
    default_args={**DEFAULT_ARGS, "on_failure_callback": task_failure_callback},
    params={
        "window_size": Param(
            DRIFT_WINDOW_SIZE,
            type="integer",
            minimum=10,
            maximum=10000,
            description="Number of most recent inference logs to analyse",
        ),
        "retrain_cooldown_minutes": Param(
            RETRAIN_COOLDOWN_MINUTES,
            type="integer",
            minimum=0,
            description="Do not trigger model_retrain again within this window",
        ),
    },
    tags=["mlops", "drift", "evidently"],
    doc_md=__doc__,
) as dag:

    @task
    def run_drift_analysis(params: dict[str, Any] | None = None) -> dict[str, Any]:
        window = int((params or {}).get("window_size", DRIFT_WINDOW_SIZE))
        result = http_json(
            "POST",
            f"{DRIFT_MONITOR_URL}/analyze",
            json={"window_size": window, "save_report": True},
            timeout=ANALYZE_TIMEOUT_SECONDS,
        )
        status = result.get("status")
        if status == "error":
            raise AirflowFailException(f"Drift analysis failed: {result.get('detail')}")
        if status == "skipped":
            print(
                f"Drift analysis skipped: {result.get('reason')} "
                f"({result.get('current_samples')}/{result.get('min_samples')} samples)"
            )
        else:
            print(
                f"drifted={result.get('is_drifted')} share={result.get('drift_share'):.2f} "
                f"max_psi={result.get('max_psi', 0.0):.3f} "
                f"prediction_psi={result.get('prediction_psi')} reasons={result.get('reasons')}"
            )
        return result

    @task.branch
    def decide(result: dict[str, Any]) -> list[str] | str:
        if result.get("status") != "success":
            return "no_drift"
        if result.get("is_drifted"):
            return ["alert_drift", "check_retrain_cooldown"]
        if result.get("prediction_shift"):
            return "alert_drift"
        return "no_drift"

    @task
    def alert_drift(result: dict[str, Any]) -> None:
        psi = result.get("psi") or {}
        top = sorted(psi.items(), key=lambda item: item[1], reverse=True)[:5]
        action = "triggering <code>model_retrain</code>" if result.get("is_drifted") else "investigate the model"
        notify(
            "DataDriftDetected" if result.get("is_drifted") else "PredictionDistributionShift",
            "[DRIFT] Data drift detected" if result.get("is_drifted") else "[DRIFT] Prediction distribution shift",
            [
                f"Drift share: {result.get('drift_share', 0):.0%} "
                f"({len(result.get('drifted_columns') or [])} columns drifted)",
                "Top PSI: " + ", ".join(f"{escape(k)}={v:.2f}" for k, v in top),
                f"Prediction PSI: {result.get('prediction_psi')}",
                f"Samples: reference={result.get('reference_samples')}, current={result.get('current_samples')}",
                f"Report: {escape(DRIFT_MONITOR_PUBLIC_URL)}/reports/{escape(result.get('report', '-'))}",
                f"Action: {action}",
            ],
            severity="warning",
            labels={"dag_id": "drift_monitoring"},
        )

    @task.short_circuit(ignore_downstream_trigger_rules=False)
    def check_retrain_cooldown(params: dict[str, Any] | None = None) -> bool:
        from airflow.models import DagRun
        from airflow.utils.state import DagRunState

        cooldown = timedelta(minutes=int((params or {}).get("retrain_cooldown_minutes", RETRAIN_COOLDOWN_MINUTES)))
        since = datetime.now(UTC) - cooldown
        runs = DagRun.find(dag_id="model_retrain")
        active = [r.run_id for r in runs if r.state in (DagRunState.RUNNING, DagRunState.QUEUED)]
        recent = [r.run_id for r in runs if r.start_date and r.start_date >= since]
        if active or recent:
            print(f"Retrain not triggered: active={active} started within {cooldown}={recent}")
            return False
        return True

    trigger_retrain = TriggerDagRunOperator(
        task_id="trigger_model_retrain",
        trigger_dag_id="model_retrain",
        conf={"reason": "drift_monitoring {{ run_id }}"},
        wait_for_completion=False,
    )

    no_drift = EmptyOperator(task_id="no_drift")

    analysis = run_drift_analysis()
    branch = decide(analysis)
    branch >> [no_drift, alert_drift(analysis)]
    branch >> check_retrain_cooldown() >> trigger_retrain
