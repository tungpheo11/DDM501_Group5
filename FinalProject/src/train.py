"""
Module: train.py
Trains the Baseline Credit Risk Model (V1.0), evaluates performance,
and registers the model to the MLflow Model Registry.
"""

import os
import joblib
import mlflow
import mlflow.sklearn
from mlflow.models.signature import infer_signature
from sklearn.pipeline import Pipeline
from sklearn.ensemble import RandomForestClassifier

from src.config import (
    BASELINE_DATA_PATH,
    NORMAL_STREAM_PATH,
    MODELS_DIR,
    MODEL_NAME,
    MODEL_ALIAS,
    EXPERIMENT_NAME,
    MLFLOW_TRACKING_URI,
)
from src.data_loader import get_train_val_split, load_data
from src.preprocessing import create_preprocessor
from src.evaluate import evaluate_model


def train_baseline_model(
    n_estimators: int = 100,
    max_depth: int = 6,
    random_state: int = 42,
    register_model: bool = True,
):
    print("=" * 60)
    print("Starting Model V1.0 (Baseline) Training Pipeline")
    print(f"Data source: {BASELINE_DATA_PATH}")
    print(f"Hyperparameters: n_estimators={n_estimators}, max_depth={max_depth}")
    print("=" * 60)

    # 1. Load baseline training and validation data
    X_train, X_val, y_train, y_val = get_train_val_split(
        BASELINE_DATA_PATH, test_size=0.2, random_state=random_state
    )
    print(
        f"Training set: {X_train.shape[0]} samples, Validation set: {X_val.shape[0]} samples"
    )

    # 2. Build model pipeline
    preprocessor = create_preprocessor()
    classifier = RandomForestClassifier(
        n_estimators=n_estimators,
        max_depth=max_depth,
        random_state=random_state,
        class_weight="balanced",
    )
    pipeline = Pipeline(
        steps=[
            ("preprocessor", preprocessor),
            ("classifier", classifier),
        ]
    )

    # 3. Fit pipeline
    print("Fitting model pipeline...")
    pipeline.fit(X_train, y_train)
    print("Model fitted successfully.")

    # 4. Evaluate on validation set
    val_metrics = evaluate_model(pipeline, X_val, y_val)
    print("\n--- Validation Metrics (Model V1.0) ---")
    for k, v in val_metrics.items():
        print(f"  {k}: {v}")

    # 5. Evaluate on Normal Stream (Future month 1 - No Drift)
    if os.path.exists(NORMAL_STREAM_PATH):
        X_norm, y_norm = load_data(NORMAL_STREAM_PATH)
        norm_metrics = evaluate_model(pipeline, X_norm, y_norm)
        print("\n--- Performance on Normal Stream (No Drift) ---")
        roc = norm_metrics["roc_auc"]
        f1_val = norm_metrics["f1_score"]
        acc = norm_metrics["accuracy"]
        print(f"  ROC-AUC: {roc:.4f} | F1: {f1_val:.4f} | Accuracy: {acc:.4f}")

    # 6. Save model locally
    local_model_path = os.path.join(MODELS_DIR, "credit_model_v1.joblib")
    joblib.dump(pipeline, local_model_path)
    print(f"\nModel saved locally to: {local_model_path}")

    # 7. Log to MLflow if tracking server is reachable
    try:
        mlflow.set_tracking_uri(MLFLOW_TRACKING_URI)
        mlflow.set_experiment(EXPERIMENT_NAME)

        with mlflow.start_run(run_name="baseline-rf-v1.0") as run:
            run_id = run.info.run_id
            print(f"\nActive MLflow Run ID: {run_id}")

            # Log parameters
            mlflow.log_param("model_type", "RandomForestClassifier")
            mlflow.log_param("n_estimators", n_estimators)
            mlflow.log_param("max_depth", max_depth)
            mlflow.log_param("class_weight", "balanced")
            mlflow.log_param("train_samples", len(X_train))

            # Log metrics
            mlflow.log_metrics(val_metrics)

            # Infer model signature
            sample_input = X_val.iloc[:5]
            sample_output = pipeline.predict(sample_input)
            signature = infer_signature(sample_input, sample_output)

            # Log model
            model_info = mlflow.sklearn.log_model(
                sk_model=pipeline,
                artifact_path="model",
                signature=signature,
                registered_model_name=MODEL_NAME if register_model else None,
                serialization_format=mlflow.sklearn.SERIALIZATION_FORMAT_CLOUDPICKLE,
            )
            print(f"Model logged to MLflow artifacts: {model_info.model_uri}")

            # Assign champion alias
            if register_model:
                client = mlflow.tracking.MlflowClient()
                # Wait briefly or fetch latest version
                versions = client.get_latest_versions(MODEL_NAME)
                if versions:
                    latest_v = versions[0].version
                    client.set_registered_model_alias(
                        name=MODEL_NAME, alias=MODEL_ALIAS, version=latest_v
                    )
                    print(
                        f"Assigned alias '@{MODEL_ALIAS}' to Model '{MODEL_NAME}' version {latest_v}"
                    )

    except Exception as exc:
        print(f"\n[Notice] Could not log to MLflow Tracking Server ({exc}).")
        print("Model remains saved locally in models/ for standalone serving.")

    return pipeline, val_metrics


if __name__ == "__main__":
    train_baseline_model()
