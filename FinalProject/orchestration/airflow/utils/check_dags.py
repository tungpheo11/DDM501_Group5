"""Parse the DAG folder and fail on import errors (``python -m utils.check_dags``).

Runs inside the Airflow image without a metadata database, so CI and
``make dags-check`` can validate DAGs before the stack is up.
"""

from __future__ import annotations

import os
import sys

EXPECTED_DAGS = {"service_health_check", "drift_monitoring", "model_retrain"}


def main() -> int:
    """Return 0 when every expected DAG parses without import errors."""
    from airflow.models import DagBag

    folder = os.environ.get("AIRFLOW__CORE__DAGS_FOLDER", "/opt/airflow/orchestration/dags")
    dagbag = DagBag(dag_folder=folder, include_examples=False)
    for path, error in dagbag.import_errors.items():
        print(f"IMPORT ERROR {path}:\n{error}")
    missing = EXPECTED_DAGS - set(dagbag.dag_ids)
    for dag_id in sorted(dagbag.dag_ids):
        dag = dagbag.get_dag(dag_id)
        print(f"{dag_id:<22} tasks={len(dag.tasks):<3} schedule={dag.timetable.summary}")
    if missing:
        print(f"MISSING DAGS: {sorted(missing)}")
    if dagbag.import_errors or missing:
        return 1
    print(f"OK: {len(dagbag.dag_ids)} DAGs, 0 import errors")
    return 0


if __name__ == "__main__":
    sys.exit(main())
