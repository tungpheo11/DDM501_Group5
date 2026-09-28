"""DAG integrity tests. Run inside the Airflow image (``make dags-test``); skipped elsewhere."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

pytest.importorskip("airflow")

from airflow.configuration import conf  # noqa: E402
from airflow.models import DagBag  # noqa: E402
from airflow.utils.trigger_rule import TriggerRule  # noqa: E402

REPO_AIRFLOW_HOME = Path(__file__).resolve().parents[2] / "orchestration" / "airflow"
EXPECTED_DAGS = {"service_health_check", "drift_monitoring", "model_retrain"}


def _dags_folder() -> Path:
    """The repo checkout when present, otherwise the image's configured DAG folder."""
    if (REPO_AIRFLOW_HOME / "dags").is_dir():
        return REPO_AIRFLOW_HOME / "dags"
    return Path(conf.get("core", "dags_folder"))


@pytest.fixture(scope="module")
def dagbag() -> DagBag:
    folder = _dags_folder()
    sys.path.insert(0, str(folder.parent))
    return DagBag(dag_folder=str(folder), include_examples=False, read_dags_from_db=False)


def test_no_import_errors(dagbag: DagBag) -> None:
    assert dagbag.size() > 0
    assert dagbag.import_errors == {}


def test_expected_dags_present(dagbag: DagBag) -> None:
    assert set(dagbag.dag_ids) >= EXPECTED_DAGS


def test_model_retrain_pipeline_order(dagbag: DagBag) -> None:
    dag = dagbag.get_dag("model_retrain")
    assert dag.schedule_interval is None
    assert dag.max_active_runs == 1
    chain = ["train_challenger", "quality_gate", "decide_promotion", "promote_champion", "reload_api"]
    for upstream, downstream in zip(chain, chain[1:], strict=False):
        assert downstream in dag.get_task(upstream).downstream_task_ids
    rollback = dag.get_task("rollback_champion")
    assert rollback.trigger_rule == TriggerRule.ONE_FAILED
    assert "reload_api" in rollback.upstream_task_ids
    assert dag.on_failure_callback is not None and dag.on_success_callback is not None


def test_drift_monitoring_triggers_retrain(dagbag: DagBag) -> None:
    dag = dagbag.get_dag("drift_monitoring")
    trigger = dag.get_task("trigger_model_retrain")
    assert trigger.trigger_dag_id == "model_retrain"
    assert "check_retrain_cooldown" in trigger.upstream_task_ids


def test_health_check_probes_are_mapped(dagbag: DagBag) -> None:
    dag = dagbag.get_dag("service_health_check")
    assert {"probe", "active_alerts", "summarize"} <= set(dag.task_ids)
