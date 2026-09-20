"""
Airflow DAG: scheduled retraining for the credit default model.

    ingest -> validate -> train -> evaluate -> decide -> [promote | skip] -> cleanup

"""

from __future__ import annotations

import json
import os
import shutil
import sys
from datetime import datetime, timedelta
from pathlib import Path

# The image installs the project at /opt/airflow/project; this makes the local
# checkout work too, so the DAG can be parsed outside the container.
sys.path.insert(0, os.getenv("PROJECT_ROOT", str(Path(__file__).resolve().parents[1])))

from airflow import DAG
from airflow.operators.empty import EmptyOperator
from airflow.operators.python import BranchPythonOperator, PythonOperator

RUN_DIR = Path(os.getenv("PIPELINE_RUN_DIR", "/opt/airflow/artifacts"))

default_args = {
    "owner": "mlops-team",
    "depends_on_past": False,
    "email_on_failure": False,
    "retries": 1,
    "retry_delay": timedelta(minutes=2),
}


# =============================================================================
# Tasks
# =============================================================================
def ingest(**context):
    """Load the raw dataset and stash the split on the shared volume."""
    import joblib

    from pipeline.data_ingestion import dataset_stats, load_raw, split_data

    run_dir = RUN_DIR / context["run_id"].replace(":", "_").replace("+", "_")
    run_dir.mkdir(parents=True, exist_ok=True)

    df = load_raw()
    stats = dataset_stats(df)
    X_train, X_test, y_train, y_test = split_data(df)

    joblib.dump({"X_train": X_train, "X_test": X_test, "y_train": y_train, "y_test": y_test},
                run_dir / "split.joblib")
    df.to_parquet(run_dir / "raw.parquet", index=False)

    ti = context["ti"]
    ti.xcom_push(key="run_dir", value=str(run_dir))
    ti.xcom_push(key="data_stats", value=stats)
    return f"{stats['n_rows']} rows, positive rate {stats['positive_rate']}"


# =============================================================================
# TODO 1: Implement validate
# =============================================================================
def validate(**context):
    """Quality gate on the data. Raising here stops the DAG before training."""
    import pandas as pd
    from pipeline.validation import validate_dataset

    ti = context["ti"]
    run_dir = Path(ti.xcom_pull(key="run_dir"))
    df = pd.read_parquet(run_dir / "raw.parquet")

    # raise_on_error=True: a failure marks this task FAILED and blocks training
    report = validate_dataset(df, raise_on_error=True)

    report_path = run_dir / "validation_report.json"
    report_path.write_text(json.dumps(report))
    ti.xcom_push(key="validation_report", value=report)
    return f"passed={report['passed']} n_errors={report['n_errors']}"


# =============================================================================
# TODO 2: Implement train
# =============================================================================
def train(**context):
    """Fit the pipeline inside an MLflow run."""
    import joblib
    from pipeline.training import setup_mlflow, train_model

    ti = context["ti"]
    run_dir = Path(ti.xcom_pull(key="run_dir"))
    data_stats = ti.xcom_pull(key="data_stats")
    validation_report = ti.xcom_pull(key="validation_report")

    split = joblib.load(run_dir / "split.joblib")
    X_train, y_train = split["X_train"], split["y_train"]

    setup_mlflow()
    model, run_id = train_model(
        X_train,
        y_train,
        model_type=os.getenv("MODEL_TYPE", "hgb"),
        run_name=f"airflow-{context['ds']}",
        data_stats=data_stats,
        validation_report=validation_report,
    )

    joblib.dump(model, run_dir / "model.joblib")
    ti.xcom_push(key="mlflow_run_id", value=run_id)
    return f"trained model run_id={run_id}"


# =============================================================================
# TODO 3: Implement evaluate
# =============================================================================
def evaluate(**context):
    """Score the held-out set and log every metric to the run."""
    import joblib
    from pipeline.evaluation import evaluate_model

    ti = context["ti"]
    run_dir = Path(ti.xcom_pull(key="run_dir"))
    run_id = ti.xcom_pull(key="mlflow_run_id")

    split = joblib.load(run_dir / "split.joblib")
    model = joblib.load(run_dir / "model.joblib")
    X_test, y_test = split["X_test"], split["y_test"]

    result = evaluate_model(model, X_test, y_test, run_id=run_id)

    # Push ONLY scalar metrics to XCom — no nested dicts, no DataFrames
    scalar_metrics = {k: v for k, v in result.items() if isinstance(v, (int, float))}
    ti.xcom_push(key="metrics", value=scalar_metrics)

    # Write full result (including group metrics) to the shared volume
    (run_dir / "evaluation.json").write_text(json.dumps(result))
    return f"roc_auc={scalar_metrics.get('roc_auc', 0):.4f} fairness_gap={scalar_metrics.get('fairness_gap', 0):.4f}"


# =============================================================================
# TODO 4: Implement decide
# =============================================================================
def decide(**context):
    """Branch: does this model clear the promotion gate?"""
    from pipeline.registry import passes_quality_gate

    ti = context["ti"]
    metrics = ti.xcom_pull(key="metrics")
    gate = passes_quality_gate(metrics)
    ti.xcom_push(key="quality_gate", value=gate)

    if gate["passed"]:
        return "promote_model"
    return "skip_promotion"


# =============================================================================
# TODO 5: Implement promote
# =============================================================================
def promote(**context):
    """Register the run and give it the alias it earned."""
    from pipeline.registry import promote_model
    from pipeline.training import setup_mlflow

    ti = context["ti"]
    run_id = ti.xcom_pull(key="mlflow_run_id")
    metrics = ti.xcom_pull(key="metrics")

    setup_mlflow()
    result = promote_model(run_id, metrics)
    ti.xcom_push(key="promotion", value=result)
    return f"outcome={result['outcome']} version={result['version']}"


def cleanup(**context):
    """Remove the run directory. Runs whether or not the model was promoted."""
    run_dir = context["ti"].xcom_pull(key="run_dir")
    if run_dir and Path(run_dir).exists():
        shutil.rmtree(run_dir, ignore_errors=True)
        return f"removed {run_dir}"
    return "nothing to clean"


# =============================================================================
# DAG
# =============================================================================
with DAG(
    dag_id="credit_default_training",
    default_args=default_args,
    description="Scheduled retraining and gated promotion for the credit default model",
    schedule=os.getenv("AIRFLOW_SCHEDULE", "@weekly"),
    start_date=datetime(2026, 1, 1),
    catchup=False,
    max_active_runs=1,
    tags=["ml", "training", "credit-risk"],
) as dag:

    t_ingest = PythonOperator(task_id="ingest", python_callable=ingest)
    t_validate = PythonOperator(task_id="validate", python_callable=validate)
    t_train = PythonOperator(task_id="train", python_callable=train)
    t_evaluate = PythonOperator(task_id="evaluate", python_callable=evaluate)
    t_decide = BranchPythonOperator(task_id="decide", python_callable=decide)
    t_promote = PythonOperator(task_id="promote_model", python_callable=promote)
    t_skip = EmptyOperator(task_id="skip_promotion")

    # none_failed_min_one_success: cleanup must run down whichever branch was
    # taken, but must not run if an upstream task actually failed.
    t_cleanup = PythonOperator(
        task_id="cleanup",
        python_callable=cleanup,
        trigger_rule="none_failed_min_one_success",
    )

    # =========================================================================
    # TODO 6: Wire up the dependency graph
    # =========================================================================
    t_ingest >> t_validate >> t_train >> t_evaluate >> t_decide
    t_decide >> [t_promote, t_skip] >> t_cleanup
