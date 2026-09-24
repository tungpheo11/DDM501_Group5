"""
Module: main.py
FastAPI Serving Service for Credit Default Risk Scoring.
Fetches the champion model from MLflow Registry or fallback local artifact,
serves predictions, exports Prometheus telemetry, and logs requests to PostgreSQL.
"""

import os
import time
import uuid
import socket
from urllib.parse import urlparse
from contextlib import asynccontextmanager
from typing import Optional, Any

import joblib
import pandas as pd
from fastapi import FastAPI, HTTPException, Response
from prometheus_client import (
    Counter,
    Histogram,
    Gauge,
    generate_latest,
    CONTENT_TYPE_LATEST,
)

import mlflow
import mlflow.sklearn

from src.config import (
    MODEL_NAME,
    MODEL_ALIAS,
    MODELS_DIR,
    MLFLOW_TRACKING_URI,
    REVIEW_THRESHOLD,
    DECLINE_THRESHOLD,
)
from app.schemas import CreditPredictRequest, CreditPredictResponse, HealthResponse
from app.database import init_db, save_inference_log

# Global state
model: Optional[Any] = None
model_source: str = "none"

# Prometheus metrics
PREDICTION_REQUESTS = Counter(
    "credit_prediction_requests_total",
    "Total credit prediction requests received",
    ["decision", "status"],
)
PREDICTION_LATENCY = Histogram(
    "credit_prediction_duration_seconds",
    "Prediction execution latency in seconds",
    buckets=[0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0],
)
DEFAULT_RISK_RATIO = Gauge(
    "credit_default_prediction_ratio",
    "Rolling ratio of requests predicted as default risk (1)",
)
recent_predictions = []


def is_service_reachable(url: str, timeout: float = 0.5) -> bool:
    try:
        parsed = urlparse(url)
        host = parsed.hostname or "localhost"
        port = parsed.port or (443 if parsed.scheme == "https" else 80)
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except Exception:
        return False


def load_champion_model():
    """
    Attempts to load the model from MLflow Model Registry via alias.
    Falls back to local joblib artifact if MLflow is unreachable.
    """
    global model, model_source
    mlflow_uri = f"models:/{MODEL_NAME}@{MODEL_ALIAS}"
    tracking_uri = os.getenv("MLFLOW_TRACKING_URI", MLFLOW_TRACKING_URI)

    if is_service_reachable(tracking_uri):
        try:
            print(f"Connecting to MLflow Tracking Server at: {tracking_uri}")
            mlflow.set_tracking_uri(tracking_uri)
            print(f"Loading registered model from: {mlflow_uri}...")
            model = mlflow.sklearn.load_model(mlflow_uri)
            model_source = f"mlflow_registry:{mlflow_uri}"
            print(f"Successfully loaded champion model from MLflow: {mlflow_uri}")
            return
        except Exception as exc:
            print(
                f"Could not load from MLflow ({exc}). Attempting fallback to local artifact..."
            )
    else:
        print(
            f"MLflow server at {tracking_uri} is offline. Using local artifact fallback."
        )

    local_path = os.path.join(MODELS_DIR, "credit_model_v1.joblib")
    if os.path.exists(local_path):
        try:
            model = joblib.load(local_path)
            model_source = f"local_artifact:{local_path}"
            print(f"Loaded fallback model from local file: {local_path}")
            return
        except Exception as exc:
            print(f"Failed to load local model: {exc}")

    model = None
    model_source = "unavailable"
    print("Warning: No model could be loaded at startup.")


@asynccontextmanager
async def lifespan(_: FastAPI):
    # 1. Initialize database
    init_db()
    # 2. Load model
    load_champion_model()
    yield


app = FastAPI(
    title="Credit Default Risk Scoring API",
    description="Production-grade MLOps Serving Microservice with Telemetry & Inference Logging.",
    version="1.0.0",
    lifespan=lifespan,
)


@app.get("/health", response_model=HealthResponse)
def health_check():
    from app.database import engine

    db_ok = engine is not None
    return HealthResponse(
        status="ok" if model is not None else "degraded",
        model_loaded=model is not None,
        model_name=MODEL_NAME,
        model_source=model_source,
        database_connected=db_ok,
    )


@app.post("/reload-model")
def reload_model_endpoint():
    """
    Manually triggers reloading the champion model from MLflow Registry or local artifact.
    Enables zero-downtime canary/champion hot-reloading.
    """
    load_champion_model()
    return {
        "status": "ok",
        "model_loaded": model is not None,
        "model_name": MODEL_NAME,
        "model_source": model_source,
    }


@app.get("/metrics")
def metrics():
    """
    Prometheus telemetry endpoint for scraping latency, throughput, and risk ratios.
    """
    return Response(content=generate_latest(), media_type=CONTENT_TYPE_LATEST)


@app.post("/predict", response_model=CreditPredictResponse)
def predict_credit_risk(payload: CreditPredictRequest):
    if model is None:
        # Try reloading on the fly in case model just finished training
        load_champion_model()
        if model is None:
            PREDICTION_REQUESTS.labels(decision="NONE", status="503").inc()
            raise HTTPException(
                status_code=503,
                detail="Model is not yet loaded or currently initializing. Please check /health.",
            )

    start_time = time.time()
    req_id = f"req_{uuid.uuid4().hex[:12]}"
    features_dict = payload.model_dump()
    df_input = pd.DataFrame([features_dict])

    try:
        # 1. Inference
        with PREDICTION_LATENCY.time():
            prediction = int(model.predict(df_input)[0])
            if hasattr(model, "predict_proba"):
                probability = float(model.predict_proba(df_input)[0][1])
            else:
                probability = float(prediction)

        # 2. Business Decision Rule
        if probability >= DECLINE_THRESHOLD:
            decision = "DECLINE"
        elif probability >= REVIEW_THRESHOLD:
            decision = "REVIEW"
        else:
            decision = "APPROVE"

        duration_ms = (time.time() - start_time) * 1000

        # 3. Update telemetry metrics
        PREDICTION_REQUESTS.labels(decision=decision, status="200").inc()
        recent_predictions.append(prediction)
        if len(recent_predictions) > 200:
            recent_predictions.pop(0)
        DEFAULT_RISK_RATIO.set(sum(recent_predictions) / len(recent_predictions))

        # 4. Asynchronously/directly save inference log for Evidently drift detection
        save_inference_log(
            request_id=req_id,
            features=features_dict,
            prediction=prediction,
            probability=probability,
            risk_decision=decision,
            latency_ms=duration_ms,
            model_version=model_source.split(":")[-1],
        )

        return CreditPredictResponse(
            request_id=req_id,
            default_prediction=prediction,
            default_probability=probability,
            risk_decision=decision,
            served_by=model_source,
            latency_ms=round(duration_ms, 2),
        )

    except Exception as exc:
        PREDICTION_REQUESTS.labels(decision="ERROR", status="500").inc()
        raise HTTPException(status_code=500, detail=f"Prediction error: {str(exc)}")
