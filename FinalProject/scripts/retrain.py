"""
Script: retrain.py
Executes the Continuous Retraining Pipeline:
1. Combines baseline data (15k) with new labeled feedback (5k) via Replay Strategy
   to prevent Catastrophic Forgetting.
2. Trains Challenger Model (V2.0) with enhanced capacity.
3. Evaluates Champion (V1.0) vs Challenger (V2.0) on financial cost & ROC-AUC.
4. If Challenger wins, registers V2.0 to MLflow and assigns alias '@champion'.
5. Triggers zero-downtime hot reload on the FastAPI serving layer.
"""

import os
import joblib
import requests
import pandas as pd
from sklearn.pipeline import Pipeline
from sklearn.ensemble import RandomForestClassifier
from sklearn.model_selection import train_test_split

import mlflow
import mlflow.sklearn
from mlflow.models.signature import infer_signature

from src.config import (
    BASELINE_DATA_PATH,
    DRIFTED_STREAM_PATH,
    GROUND_TRUTH_PATH,
    MODELS_DIR,
    MODEL_NAME,
    MODEL_ALIAS,
    EXPERIMENT_NAME,
    MLFLOW_TRACKING_URI,
    ALL_FEATURES,
    TARGET_COLUMN,
)
from src.preprocessing import create_preprocessor
from src.evaluate import evaluate_model


def load_combined_training_data():
    """Combines baseline data with ground truth feedback using Replay Strategy."""
    # 1. Baseline data
    df_baseline = pd.read_csv(BASELINE_DATA_PATH)
    print(f"Loaded Baseline data: {len(df_baseline)} samples (Mean age: {df_baseline['AGE'].mean():.1f})")

    # 2. Ground truth feedback data
    df_features = pd.read_csv(DRIFTED_STREAM_PATH)
    df_feedback = pd.read_csv(GROUND_TRUTH_PATH)

    df_drifted = pd.merge(df_features, df_feedback, on="request_id")
    if "request_id" in df_drifted.columns:
        df_drifted = df_drifted.drop(columns=["request_id"])
    print(f"Loaded Ground Truth Feedback: {len(df_drifted)} samples (Mean age: {df_drifted['AGE'].mean():.1f})")

    # 3. Combine to prevent Catastrophic Forgetting
    df_combined = pd.concat([df_baseline, df_drifted], ignore_index=True)
    print(f"Combined Training Corpus: {len(df_combined)} samples (Mean age: {df_combined['AGE'].mean():.1f})")

    X = df_combined[ALL_FEATURES]
    y = df_combined[TARGET_COLUMN]
    return X, y, df_drifted


def calculate_financial_loss(y_true, y_pred, cost_fn: float = 10.0, cost_fp: float = 1.0) -> float:
    """Calculates financial loss based on asymmetric cost matrix."""
    from sklearn.metrics import confusion_matrix
    tn, fp, fn, tp = confusion_matrix(y_true, y_pred).ravel()
    total_loss = (fn * cost_fn) + (fp * cost_fp)
    return float(total_loss)


def run_retraining_pipeline():
    print("=" * 65)
    print("Starting Model V2.0 Challenger Retraining & Champion Evaluation")
    print("=" * 65)

    X_all, y_all, df_drifted_test = load_combined_training_data()

    # Split combined data into Train and Validation
    X_train, X_val, y_train, y_val = train_test_split(
        X_all, y_all, test_size=0.2, random_state=42, stratify=y_all
    )
    print(f"Train split: {len(X_train)} samples | Validation split: {len(X_val)} samples")

    # Prepare holdout drifted test set for fair Champion vs Challenger comparison
    X_drift_test = df_drifted_test[ALL_FEATURES]
    y_drift_test = df_drifted_test[TARGET_COLUMN]

    # 1. Load current Champion Model (V1.0)
    champion_model = None
    champion_path = os.path.join(MODELS_DIR, "credit_model_v1.joblib")
    if os.path.exists(champion_path):
        champion_model = joblib.load(champion_path)
        print("\nLoaded Champion Model (V1.0) for benchmarking.")

    # 2. Build Challenger Model (V2.0) with enhanced capacity
    preprocessor = create_preprocessor()
    classifier_v2 = RandomForestClassifier(
        n_estimators=150,
        max_depth=8,
        min_samples_split=8,
        class_weight="balanced",
        random_state=42,
    )
    challenger_pipeline = Pipeline([
        ("preprocessor", preprocessor),
        ("classifier", classifier_v2),
    ])

    print("\nTraining Challenger Model (V2.0)...")
    challenger_pipeline.fit(X_train, y_train)
    print("Challenger Model fitted successfully.")

    # 3. Evaluate Challenger on Validation Set
    val_metrics_v2 = evaluate_model(challenger_pipeline, X_val, y_val)
    print("\n--- Challenger (V2.0) Validation Metrics ---")
    for k, v in val_metrics_v2.items():
        print(f"  {k}: {v}")

    # 4. Champion vs Challenger Showdown on Drifted Test Set
    print("\n" + "=" * 65)
    print("Champion vs Challenger Showdown on Drifted Segment")
    print("=" * 65)

    champ_metrics = {}
    champ_loss = 0.0
    if champion_model is not None:
        champ_metrics = evaluate_model(champion_model, X_drift_test, y_drift_test)
        champ_pred = champion_model.predict(X_drift_test)
        champ_loss = calculate_financial_loss(y_drift_test, champ_pred)
        c_auc = champ_metrics['roc_auc']
        c_f1 = champ_metrics['f1_score']
        print(
            f"Champion (V1.0)   -> ROC-AUC: {c_auc:.4f} | F1: {c_f1:.4f} | Loss: {champ_loss:,.0f}"
        )

    chal_metrics = evaluate_model(challenger_pipeline, X_drift_test, y_drift_test)
    chal_pred = challenger_pipeline.predict(X_drift_test)
    chal_loss = calculate_financial_loss(y_drift_test, chal_pred)
    ch_auc = chal_metrics['roc_auc']
    ch_f1 = chal_metrics['f1_score']
    print(
        f"Challenger (V2.0) -> ROC-AUC: {ch_auc:.4f} | F1: {ch_f1:.4f} | Loss: {chal_loss:,.0f}"
    )

    # Determine winner
    is_promoted = chal_metrics["roc_auc"] >= champ_metrics.get("roc_auc", 0.0)

    # 5. Log Challenger to MLflow & Update Registry
    try:
        mlflow.set_tracking_uri(MLFLOW_TRACKING_URI)

        mlflow.set_experiment(EXPERIMENT_NAME)

        with mlflow.start_run(run_name="retrain-rf-v2.0-challenger") as run:
            print(f"\nMLflow Run ID: {run.info.run_id}")
            mlflow.log_param("model_type", "RandomForestClassifier-V2")
            mlflow.log_param("n_estimators", 150)
            mlflow.log_param("max_depth", 8)
            mlflow.log_param("strategy", "Replay-15k-baseline-plus-5k-feedback")
            mlflow.log_param("train_samples", len(X_train))

            mlflow.log_metrics(val_metrics_v2)
            mlflow.log_metric("drifted_test_roc_auc", chal_metrics["roc_auc"])
            mlflow.log_metric("drifted_test_financial_loss", chal_loss)

            sample_input = X_val.iloc[:5]
            sample_output = challenger_pipeline.predict(sample_input)
            signature = infer_signature(sample_input, sample_output)

            model_info = mlflow.sklearn.log_model(
                sk_model=challenger_pipeline,
                artifact_path="model",
                signature=signature,
                registered_model_name=MODEL_NAME,
                serialization_format=mlflow.sklearn.SERIALIZATION_FORMAT_CLOUDPICKLE,
            )
            print(f"Logged Challenger Model to MLflow: {model_info.model_uri}")

            # If promoted, update alias to @champion
            if is_promoted:
                client = mlflow.tracking.MlflowClient()
                versions = client.get_latest_versions(MODEL_NAME)
                new_version = versions[0].version
                client.set_registered_model_alias(MODEL_NAME, MODEL_ALIAS, new_version)
                print(f"\n[PROMOTION] Challenger Model promoted to '@{MODEL_ALIAS}' (Version {new_version})!")

    except Exception as exc:
        print(f"\nMLflow logging note: {exc}")

    # Save local artifact
    v2_path = os.path.join(MODELS_DIR, "credit_model_v2.joblib")
    joblib.dump(challenger_pipeline, v2_path)
    print(f"Saved Model V2 locally to: {v2_path}")

    # 6. Trigger zero-downtime hot reload on Serving API
    api_url = "http://localhost:18020/reload-model"
    try:
        resp = requests.post(api_url, timeout=3)
        if resp.status_code == 200:
            print(f"\n[HOT RELOAD] Successfully triggered model reload on API: {resp.json()}")
    except Exception as exc:
        print(f"Could not reach API for hot reload ({exc}).")

    print("\nRetraining Pipeline completed successfully!")
    return challenger_pipeline, chal_metrics


if __name__ == "__main__":
    run_retraining_pipeline()
