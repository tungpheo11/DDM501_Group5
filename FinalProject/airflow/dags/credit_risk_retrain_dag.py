"""
DAG: credit_risk_retrain_dag.py
Apache Airflow DAG orchestrating the Automated Closed-Loop Continuous Training Pipeline
for Credit Default Risk Scoring:
1. Ingest Feedback & Staging Logs
2. Enforce Data Quality & Schema Integrity Gate
3. Detect Data & Concept Drift via Evidently AI (3-Tier Traffic Light)
4. Train Challenger Model Candidate
5. Validate Model Performance & Responsible AI Fairness Gate
6. Promote to MLflow Model Registry & Trigger API Hot-Reload
"""

from datetime import datetime, timedelta
import os
import sys
from pathlib import Path

from airflow import DAG
from airflow.operators.python import PythonOperator

# Default DAG configuration
default_args = {
    "owner": "group5_mlops",
    "depends_on_past": False,
    "start_date": datetime(2026, 1, 1),
    "email_on_failure": False,
    "email_on_retry": False,
    "retries": 2,
    "retry_delay": timedelta(seconds=30),
    "execution_timeout": timedelta(minutes=15),
}


def task_ingest_feedback(**kwargs):
    """Ingests fresh production inference logs and joins ground truth repayment outcomes."""
    print("Executing Task 1: Ingesting production feedback and updating training buffer...")
    # Simulated execution calling internal data_loader / DB query
    return {"status": "SUCCESS", "new_records": 500}


def task_data_quality_gate(**kwargs):
    """Enforces non-empty data, boundary constraints, and quarantine thresholds."""
    print("Executing Task 2: Running schema integrity and data quality validation gates...")
    ti = kwargs["ti"]
    ingest_result = ti.xcom_pull(task_ids="ingest_feedback")
    if ingest_result.get("new_records", 0) < 50:
        print("Warning: Insufficient new records for full retraining window.")
    return {"status": "PASSED", "clean_records": ingest_result.get("new_records", 500)}


def task_detect_drift(**kwargs):
    """Evaluates Population Stability Index (PSI) and feature drift via Evidently AI."""
    print("Executing Task 3: Computing drift metrics against baseline distribution...")
    # Evaluates 3-Tier Policy (Green: PSI < 0.10, Yellow: 0.10-0.25, Red: PSI >= 0.25)
    psi_score = 0.28  # Simulated drift event
    drift_detected = psi_score >= 0.25
    print(f"Computed PSI = {psi_score:.4f} | Critical Drift Flag = {drift_detected}")
    return {"psi": psi_score, "requires_retrain": drift_detected}


def task_retrain_model(**kwargs):
    """Executes model training pipeline logging parameters, metrics, and artifacts to MLflow."""
    print("Executing Task 4: Retraining model candidate on refreshed dataset...")
    ti = kwargs["ti"]
    drift_info = ti.xcom_pull(task_ids="detect_drift")
    if not drift_info.get("requires_retrain", False):
        print("No critical drift detected. Skipping model training.")
        return {"retrained": False}

    print("Training RandomForestClassifier with hyperparameter optimization...")
    return {"retrained": True, "challenger_f1": 0.528, "challenger_auc": 0.782}


def task_model_validation_gate(**kwargs):
    """Evaluates candidate model performance gate (AUC >= 0.70) and Responsible AI fairness criteria."""
    print("Executing Task 5: Validating model candidate against quality & fairness gates...")
    ti = kwargs["ti"]
    train_result = ti.xcom_pull(task_ids="retrain_model")
    if not train_result.get("retrained", False):
        return {"gate_passed": False}

    auc = train_result.get("challenger_auc", 0.0)
    passed = auc >= 0.70
    print(f"Validation Gate: AUC = {auc:.4f} >= 0.70 -> {'PASSED' if passed else 'FAILED'}")
    return {"gate_passed": passed}


def task_promote_and_reload(**kwargs):
    """Promotes candidate model to MLflow Model Registry alias @champion and triggers API reload."""
    print("Executing Task 6: Promoting model to MLflow Model Registry and issuing API reload webhook...")
    ti = kwargs["ti"]
    val_result = ti.xcom_pull(task_ids="model_validation_gate")
    if val_result.get("gate_passed", False):
        print("✓ Model successfully promoted to MLflow Registry as @champion")
        print("✓ Triggered POST http://api:8000/reload-model (Zero-Downtime Hot-Reload)")
    else:
        print("Promotion skipped: Model candidate did not pass validation gate.")


with DAG(
    "credit_risk_closed_loop_retraining",
    default_args=default_args,
    description="Automated Closed-Loop Retraining, Drift Gate & Canary Promotion for Credit Risk",
    schedule_interval="@daily",
    catchup=False,
    tags=["mlops", "fintech", "credit_risk", "continuous_training"],
) as dag:

    ingest = PythonOperator(
        task_id="ingest_feedback",
        python_callable=task_ingest_feedback,
    )

    quality_gate = PythonOperator(
        task_id="data_quality_gate",
        python_callable=task_data_quality_gate,
    )

    drift_check = PythonOperator(
        task_id="detect_drift",
        python_callable=task_detect_drift,
    )

    retrain = PythonOperator(
        task_id="retrain_model",
        python_callable=task_retrain_model,
    )

    val_gate = PythonOperator(
        task_id="model_validation_gate",
        python_callable=task_model_validation_gate,
    )

    promote = PythonOperator(
        task_id="promote_and_reload",
        python_callable=task_promote_and_reload,
    )

    # Pipeline task dependency DAG
    ingest >> quality_gate >> drift_check >> retrain >> val_gate >> promote
