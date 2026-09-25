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
CREDIT_APPROVED_VOLUME = Counter(
    "credit_approved_volume_ntd_total",
    "Cumulative credit amount approved in NTD",
)
CREDIT_DECLINED_VOLUME = Counter(
    "credit_declined_volume_ntd_total",
    "Cumulative credit exposure blocked in NTD",
)
AVG_AGE_GAUGE = Gauge(
    "credit_customer_age_rolling_mean",
    "Rolling mean age of incoming applicants",
)
AVG_LIMIT_GAUGE = Gauge(
    "credit_customer_limit_bal_rolling_mean",
    "Rolling mean credit limit of applicants in NTD",
)
AVG_UTILIZATION_GAUGE = Gauge(
    "credit_customer_utilization_ratio_mean",
    "Rolling credit card utilization ratio (BILL_AMT1 / LIMIT_BAL)",
)
PAY_0_DELAY_RATIO = Gauge(
    "credit_customer_pay_0_delayed_ratio",
    "Ratio of applicants with recent payment delay (PAY_0 > 0)",
)
CREDIT_SCORE_HISTOGRAM = Histogram(
    "credit_applicant_score_distribution",
    "Credit score distribution on 300-850 scale",
    buckets=[350, 450, 550, 650, 700, 750, 800, 850],
)

recent_predictions = []
recent_ages = []
recent_limits = []
recent_utilizations = []
recent_delays = []


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
        # 1. Model Inference
        with PREDICTION_LATENCY.time():
            prediction = int(model.predict(df_input)[0])
            if hasattr(model, "predict_proba"):
                probability = float(model.predict_proba(df_input)[0][1])
            else:
                probability = float(prediction)

        # 2. Multi-threshold Business Decision
        if probability >= DECLINE_THRESHOLD:
            decision = "DECLINE"
        elif probability >= REVIEW_THRESHOLD:
            decision = "REVIEW"
        else:
            decision = "APPROVE"

        # 3. Credit Scoring & Explainability (XAI)
        limit_bal = float(payload.LIMIT_BAL)
        bill1 = float(payload.BILL_AMT1)
        age = int(payload.AGE)
        pay0 = int(payload.PAY_0)
        utilization = (bill1 / limit_bal) if limit_bal > 0 else 0.0

        # Calibrated FICO-equivalent Score (300 to 850 scale)
        credit_score = int(round(850.0 - (probability * 550.0)))
        credit_score = max(300, min(850, credit_score))

        if credit_score >= 740:
            credit_tier = "PRIME"
        elif credit_score >= 670:
            credit_tier = "NEAR_PRIME"
        elif credit_score >= 580:
            credit_tier = "SUBPRIME"
        else:
            credit_tier = "HIGH_RISK"

        # Dynamic Credit Limit Recommendation
        if decision == "APPROVE":
            recommended_limit = round(min(limit_bal * 1.25, 500000.0), -2)
        elif decision == "REVIEW":
            recommended_limit = round(min(limit_bal * 0.50, 100000.0), -2)
        else:
            recommended_limit = 0.0

        # Explainability: Top 3 Risk Factors
        top_risk_factors = []
        if pay0 >= 2:
            top_risk_factors.append(
                f"Severe Delinquency: PAY_0={pay0} indicates {pay0}+ months payment default"
            )
        elif pay0 == 1:
            top_risk_factors.append(
                "Payment Lag: 1-month delayed payment recorded on recent billing cycle"
            )
        else:
            top_risk_factors.append(
                "Repayment Discipline: Timely and structured monthly repayments"
            )

        if utilization >= 0.90:
            top_risk_factors.append(
                f"Excessive Credit Line Utilization: {utilization * 100:.1f}% of limit consumed"
            )
        elif utilization <= 0.35:
            top_risk_factors.append(
                f"Conservative Debt Ratio: Low credit utilization of {utilization * 100:.1f}%"
            )
        else:
            top_risk_factors.append(
                f"Moderate Debt Utilization: {utilization * 100:.1f}% credit utilization"
            )

        if age < 25:
            top_risk_factors.append(
                f"Demographic Cohort: Young applicant profile ({age}yo) with nascent credit history"
            )
        elif age >= 45:
            top_risk_factors.append(
                f"Demographic Cohort: Mature applicant profile ({age}yo) with established credit history"
            )

        if limit_bal <= 30000.0:
            top_risk_factors.append("Sub-prime Credit Ceiling: Low initial assigned limit")

        policy_guardrails = {
            "age_verification": "PASS" if age >= 18 else "FAIL",
            "utilization_ceiling_check": (
                "ACCEPTABLE" if utilization < 0.95 else "OVER_UTILIZED_WARNING"
            ),
            "delinquency_guardrail": (
                "CLEAR" if pay0 <= 1 else "ELEVATED_DEFAULT_RISK"
            ),
        }

        duration_ms = (time.time() - start_time) * 1000

        # 4. Telemetry Updates
        PREDICTION_REQUESTS.labels(decision=decision, status="200").inc()
        CREDIT_SCORE_HISTOGRAM.observe(credit_score)
        if decision == "APPROVE":
            CREDIT_APPROVED_VOLUME.inc(recommended_limit)
        elif decision == "DECLINE":
            CREDIT_DECLINED_VOLUME.inc(limit_bal)

        recent_predictions.append(prediction)
        recent_ages.append(age)
        recent_limits.append(limit_bal)
        recent_utilizations.append(utilization)
        recent_delays.append(1 if pay0 > 0 else 0)

        if len(recent_predictions) > 200:
            recent_predictions.pop(0)
            recent_ages.pop(0)
            recent_limits.pop(0)
            recent_utilizations.pop(0)
            recent_delays.pop(0)

        DEFAULT_RISK_RATIO.set(sum(recent_predictions) / len(recent_predictions))
        AVG_AGE_GAUGE.set(sum(recent_ages) / len(recent_ages))
        AVG_LIMIT_GAUGE.set(sum(recent_limits) / len(recent_limits))
        AVG_UTILIZATION_GAUGE.set(sum(recent_utilizations) / len(recent_utilizations))
        PAY_0_DELAY_RATIO.set(sum(recent_delays) / len(recent_delays))

        # 5. Persist to PostgreSQL inference_logs
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
            credit_score=credit_score,
            credit_tier=credit_tier,
            risk_decision=decision,
            recommended_limit_ntd=recommended_limit,
            top_risk_factors=top_risk_factors[:3],
            policy_guardrails=policy_guardrails,
            served_by=model_source,
            latency_ms=round(duration_ms, 2),
        )

    except Exception as exc:
        PREDICTION_REQUESTS.labels(decision="ERROR", status="500").inc()
        raise HTTPException(status_code=500, detail=f"Prediction error: {str(exc)}")
