"""
Module: config.py
Central configuration and feature definitions for the Credit Risk MLOps project.
"""

import os
from pathlib import Path

# Paths
BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"
MODELS_DIR = BASE_DIR / "models"
MODELS_DIR.mkdir(parents=True, exist_ok=True)

# Dataset file paths
BASELINE_DATA_PATH = os.getenv(
    "BASELINE_DATA_PATH", str(DATA_DIR / "train_baseline.csv")
)
NORMAL_STREAM_PATH = os.getenv(
    "NORMAL_STREAM_PATH", str(DATA_DIR / "stream_normal.csv")
)
DRIFTED_STREAM_PATH = os.getenv(
    "DRIFTED_STREAM_PATH", str(DATA_DIR / "stream_drifted.csv")
)
GROUND_TRUTH_PATH = os.getenv(
    "GROUND_TRUTH_PATH", str(DATA_DIR / "ground_truth_feedback.csv")
)

# Feature schema
NUMERICAL_FEATURES = [
    "LIMIT_BAL",
    "AGE",
    "BILL_AMT1",
    "BILL_AMT2",
    "BILL_AMT3",
    "BILL_AMT4",
    "BILL_AMT5",
    "BILL_AMT6",
    "PAY_AMT1",
    "PAY_AMT2",
    "PAY_AMT3",
    "PAY_AMT4",
    "PAY_AMT5",
    "PAY_AMT6",
]

CATEGORICAL_FEATURES = [
    "SEX",
    "EDUCATION",
    "MARRIAGE",
]

ORDINAL_FEATURES = [
    "PAY_0",
    "PAY_2",
    "PAY_3",
    "PAY_4",
    "PAY_5",
    "PAY_6",
]

ALL_FEATURES = NUMERICAL_FEATURES + CATEGORICAL_FEATURES + ORDINAL_FEATURES
TARGET_COLUMN = "default_payment_next_month"

# Model and MLflow configurations
MODEL_NAME = os.getenv("MODEL_NAME", "credit-risk-model")
MODEL_ALIAS = os.getenv("MODEL_ALIAS", "champion")
EXPERIMENT_NAME = os.getenv("EXPERIMENT_NAME", "credit-default-risk-scoring")
MLFLOW_TRACKING_URI = os.getenv("MLFLOW_TRACKING_URI", "http://localhost:15040")

# Decision thresholds for Credit Risk Scoring
REVIEW_THRESHOLD = float(os.getenv("REVIEW_THRESHOLD", "0.30"))
DECLINE_THRESHOLD = float(os.getenv("DECLINE_THRESHOLD", "0.60"))

# Database configurations for Inference Logging
POSTGRES_USER = os.getenv("POSTGRES_USER", "mlops")
POSTGRES_PASSWORD = os.getenv("POSTGRES_PASSWORD", "mlopspass")
POSTGRES_DB = os.getenv("POSTGRES_DB", "credit_mlops_db")
POSTGRES_HOST = os.getenv("POSTGRES_HOST", "localhost")
POSTGRES_PORT = os.getenv("POSTGRES_PORT", "15434")

DATABASE_URL = os.getenv(
    "DATABASE_URL",
    f"postgresql://{POSTGRES_USER}:{POSTGRES_PASSWORD}@{POSTGRES_HOST}:{POSTGRES_PORT}/{POSTGRES_DB}",
)
