"""Model retrain: train challenger -> quality gate -> promote @champion -> reload API.

Triggered manually or by ``drift_monitoring``. ML steps run in the project
interpreter (``CREDIT_PYTHON``) and reuse ``credit_risk.training``:
``run_retraining_pipeline`` (challenger + champion/challenger gate),
``promote_model_version`` and ``rollback_champion``.

Outcomes:

* gate passes -> ``@champion`` moves, the API hot-reloads and is verified to
  serve the new version; the drift reference is re-scored with it;
* challenger not better than the champion -> champion kept, run succeeds;
* any failure (training, ROC-AUC floor, promotion, reload) -> run fails, the
  ``credit_retrain_last_run_failed`` gauge is set (alert ``RetrainFailed``) and
  ``@champion`` is left on, or rolled back to, the previous version.

Force a failure for a demo: trigger with ``{"min_roc_auc": 0.99}``.
"""

from __future__ import annotations

import time
from typing import Any

from airflow import DAG
from airflow.decorators import task
from airflow.exceptions import AirflowFailException
from airflow.models.param import Param
from airflow.utils.trigger_rule import TriggerRule
from utils.common import (
    API_URL,
    CREDIT_PYTHON,
    DEFAULT_ARGS,
    DRIFT_MONITOR_URL,
    MLFLOW_PUBLIC_URL,
    RETRAIN_MIN_ROC_AUC,
    START_DATE,
    api_headers,
    http_json,
)
from utils.notify import escape, notify, statsd_gauge, task_failure_callback

RELOAD_TIMEOUT_SECONDS = 120
FAILED_GAUGE = "credit.retrain.last_run_failed"


def _on_dag_success(context: dict[str, Any]) -> None:
    statsd_gauge(FAILED_GAUGE, 0)
    statsd_gauge("credit.retrain.last_run_timestamp", time.time())


def _on_dag_failure(context: dict[str, Any]) -> None:
    statsd_gauge(FAILED_GAUGE, 1)
    statsd_gauge("credit.retrain.last_run_timestamp", time.time())
    dag_run = context.get("dag_run")
    failed = [ti.task_id for ti in dag_run.get_task_instances(state="failed")] if dag_run else []
    notify(
        "RetrainFailed",
        "[RETRAIN] model_retrain failed - current champion kept",
        [
            f"Run: <code>{escape(getattr(dag_run, 'run_id', '-'))}</code>",
            f"Failed tasks: <code>{escape(', '.join(failed) or '-')}</code>",
            f"Reason: {escape(context.get('reason', '-'))}",
        ],
        severity="critical",
        labels={"dag_id": "model_retrain"},
    )


with DAG(
    dag_id="model_retrain",
    description="Train a challenger, gate it, promote @champion and hot-reload the API",
    schedule=None,
    start_date=START_DATE,
    catchup=False,
    max_active_runs=1,
    default_args={**DEFAULT_ARGS, "on_failure_callback": task_failure_callback},
    on_success_callback=_on_dag_success,
    on_failure_callback=_on_dag_failure,
    params={
        "min_roc_auc": Param(
            RETRAIN_MIN_ROC_AUC,
            type="number",
            minimum=0,
            maximum=1,
            description="Absolute ROC-AUC floor on the held-out drifted rows (0.99 forces a failure)",
        ),
        "reason": Param("manual", type="string", description="Why this retrain was requested"),
    },
    tags=["mlops", "training", "mlflow"],
    doc_md=__doc__,
) as dag:

    @task.external_python(task_id="train_challenger", python=CREDIT_PYTHON, expect_airflow=False, retries=0)
    def train_challenger(reason: str) -> dict:
        from credit_risk.config import get_settings
        from credit_risk.training.registry import get_alias_version, get_registry_client
        from credit_risk.training.retrain import run_retraining_pipeline

        settings = get_settings()
        client = get_registry_client(settings)
        if client is None:
            raise RuntimeError(f"MLflow registry unreachable at {settings.mlflow.tracking_uri}")
        name, alias = settings.mlflow.model_name, settings.mlflow.model_alias
        champion_before = get_alias_version(client, name, alias)

        result = run_retraining_pipeline(settings, reload_api=False, promote=False)
        keys = ("roc_auc", "f1_score", "precision", "recall", "financial_loss")
        summary = {
            "model_name": name,
            "reason": reason,
            "registered_version": result.registered_version,
            "duplicate_of": result.duplicate_of,
            "champion_version_before": result.champion_version or champion_before,
            "champion_source": result.champion_source,
            "eval_samples": result.eval_samples,
            "training_fingerprint": result.training_fingerprint[:12],
            "candidate": result.candidate,
            "challenger_metrics": {k: float(result.challenger_metrics.get(k, 0.0)) for k in keys},
            "champion_metrics": {k: float(result.champion_metrics.get(k, 0.0)) for k in keys},
            "gate_promote": bool(result.gate.promote) if result.gate else False,
            "gate_reasons": list(result.gate.reasons) if result.gate else [],
        }
        champion = summary["champion_version_before"]
        print(f"Challenger v{summary['registered_version']} vs champion v{champion}: {summary}")
        return summary

    @task
    def quality_gate(candidate: dict[str, Any], params: dict[str, Any] | None = None) -> dict[str, Any]:
        floor = float((params or {}).get("min_roc_auc", RETRAIN_MIN_ROC_AUC))
        roc_auc = candidate["challenger_metrics"]["roc_auc"]
        duplicate_of = candidate.get("duplicate_of")
        if not candidate.get("registered_version") and not duplicate_of:
            raise AirflowFailException("Challenger was not registered in MLflow; nothing to promote.")
        label = f"v{candidate['registered_version']}" if not duplicate_of else f"same as rejected v{duplicate_of}"
        if roc_auc < floor:
            # AirflowFailException skips retries: re-running does not change the metric.
            raise AirflowFailException(
                f"Quality gate failed: ROC-AUC {roc_auc:.4f} < floor {floor:.4f} "
                f"(challenger {label}, champion unchanged)"
            )
        print(f"Quality floor passed: ROC-AUC {roc_auc:.4f} >= {floor:.4f}; gate: {candidate['gate_reasons']}")
        return candidate

    @task.branch
    def decide_promotion(candidate: dict[str, Any]) -> str:
        promote = candidate["gate_promote"] and not candidate.get("duplicate_of")
        return "promote_champion" if promote else "keep_champion"

    @task.external_python(task_id="promote_champion", python=CREDIT_PYTHON, expect_airflow=False, retries=0)
    def promote_champion(candidate: dict) -> dict:
        from credit_risk.training.registry import promote_model_version

        change = promote_model_version(
            candidate["registered_version"], reason=f"airflow model_retrain: {candidate['reason']}"
        )
        return {
            "model_name": change.model_name,
            "champion_version": change.champion_version,
            "previous_champion_version": change.previous_champion_version,
        }

    @task(retries=2)
    def reload_api(promotion: dict[str, Any]) -> dict[str, Any]:
        body = http_json(
            "POST", f"{API_URL}/api/v1/model/reload", headers=api_headers(), timeout=RELOAD_TIMEOUT_SECONDS
        )
        model = body.get("model") or {}
        served = str(model.get("model_version"))
        if body.get("status") != "reloaded" or served != promotion["champion_version"] or model.get("degraded"):
            raise AirflowFailException(
                f"API did not switch to v{promotion['champion_version']}: status={body.get('status')} "
                f"served=v{served} source={model.get('source')} degraded={model.get('degraded')}"
            )
        print(f"API now serves {model.get('uri')} (previous v{body.get('previous_version')})")
        return {**promotion, "api_model_version": served, "api_previous_version": body.get("previous_version")}

    @task.external_python(
        task_id="rollback_champion",
        python=CREDIT_PYTHON,
        expect_airflow=False,
        retries=0,
        trigger_rule=TriggerRule.ONE_FAILED,
    )
    def rollback_on_failure(promotion: dict | None) -> dict:
        import os

        import requests

        if not promotion:
            print("Nothing was promoted in this run; champion unchanged.")
            return {"action": "none"}
        previous = promotion.get("previous_champion_version")
        if not previous:
            print("No previous champion to roll back to; leaving the alias in place.")
            return {"action": "none", "reason": "no previous champion"}

        from credit_risk.training.registry import rollback_champion

        change = rollback_champion(to_version=previous)
        api_url = os.environ.get("API_URL", "http://api:8000").rstrip("/")
        api_key = os.environ.get("API_KEY", "")
        try:
            response = requests.post(
                f"{api_url}/api/v1/model/reload", headers={"X-API-Key": api_key} if api_key else {}, timeout=120
            )
            reloaded = response.status_code == 200
        except requests.RequestException as exc:
            print(f"API reload after rollback failed: {exc}")
            reloaded = False
        print(f"Rolled back @champion v{change.previous_champion_version} -> v{change.champion_version}")
        return {"action": "rollback", "champion_version": change.champion_version, "api_reloaded": reloaded}

    @task
    def refresh_drift_reference(reloaded: dict[str, Any]) -> dict[str, Any]:
        try:
            body = http_json("POST", f"{DRIFT_MONITOR_URL}/reference/refresh", timeout=120)
            print(f"Drift reference re-scored with the new champion: {body}")
        except Exception as exc:  # The promotion already succeeded; a stale reference is only a warning.
            print(f"WARNING: drift reference refresh failed: {exc}")
        return reloaded

    @task
    def notify_promoted(candidate: dict[str, Any], reloaded: dict[str, Any]) -> None:
        statsd_gauge("credit.retrain.last_promoted_version", float(reloaded["champion_version"]))
        new, old = candidate["challenger_metrics"], candidate["champion_metrics"]
        notify(
            "RetrainPromoted",
            f"[RETRAIN] {candidate['model_name']} v{reloaded['champion_version']} promoted to @champion",
            [
                f"Previous champion: v{escape(reloaded.get('previous_champion_version') or '-')}",
                f"ROC-AUC {new['roc_auc']:.4f} (was {old['roc_auc']:.4f}) | F1 {new['f1_score']:.4f}",
                f"Financial loss {new['financial_loss']:,.0f} (was {old['financial_loss']:,.0f})",
                f"Reason: {escape(candidate['reason'])}",
                f"API serving v{escape(reloaded['api_model_version'])} | MLflow: {escape(MLFLOW_PUBLIC_URL)}",
            ],
            status="resolved",
            labels={"dag_id": "model_retrain"},
        )

    @task
    def keep_champion(candidate: dict[str, Any]) -> None:
        champion = candidate["champion_version_before"]
        duplicate_of = candidate.get("duplicate_of")
        lines = [escape(reason) for reason in candidate["gate_reasons"]]
        if duplicate_of:
            title = f"[RETRAIN] inputs unchanged - champion v{champion} kept (same result as rejected v{duplicate_of})"
            lines.append(
                f"Same data files, spec and champion as v{duplicate_of} (fingerprint "
                f"{escape(candidate.get('training_fingerprint', ''))}): the seeded refit reproduces the same "
                "challenger, so no new version was registered. Only new labelled feedback can change the decision."
            )
        else:
            title = f"[RETRAIN] challenger v{candidate['registered_version']} rejected - champion v{champion} kept"
        lines += [
            f"Compared on {candidate.get('eval_samples', 0)} held-out drifted rows against "
            f"{escape(candidate.get('champion_source', '-'))}",
            f"Reason: {escape(candidate['reason'])}",
        ]
        notify("RetrainChampionKept", title, lines, status="resolved", labels={"dag_id": "model_retrain"})

    candidate = train_challenger(reason="{{ dag_run.conf.get('reason') or params.reason }}")
    gated = quality_gate(candidate)
    branch = decide_promotion(gated)
    promotion = promote_champion(gated)
    reloaded = reload_api(promotion)
    refreshed = refresh_drift_reference(reloaded)
    notify_promoted(gated, refreshed)
    branch >> [promotion, keep_champion(gated)]
    reloaded >> rollback_on_failure(promotion)
