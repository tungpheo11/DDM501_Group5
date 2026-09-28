"""
Module: database.py
Database connection and schema for storing real-time inference logs.
"""

import json
from datetime import datetime
from typing import Dict, Any

from sqlalchemy import (
    create_engine,
    Column,
    Integer,
    String,
    Float,
    DateTime,
    Text,
)
from sqlalchemy.orm import declarative_base, sessionmaker

from src.config import DATABASE_URL

Base = declarative_base()


class InferenceLog(Base):
    """
    Table storing every prediction request, its input features, output score,
    and operational metadata for subsequent drift analysis by Evidently AI.
    """

    __tablename__ = "inference_logs"

    id = Column(Integer, primary_key=True, autoincrement=True)
    request_id = Column(String(64), index=True, nullable=False)
    timestamp = Column(DateTime, default=datetime.utcnow, index=True, nullable=False)
    features_json = Column(Text, nullable=False)
    prediction = Column(Integer, nullable=False)
    probability = Column(Float, nullable=False)
    risk_decision = Column(String(16), nullable=False)
    latency_ms = Column(Float, nullable=False)
    model_version = Column(String(128), default="v1.0")


# Engine and session creation
engine = None
SessionLocal = None


def init_db():
    global engine, SessionLocal
    try:
        engine = create_engine(
            DATABASE_URL,
            pool_pre_ping=True,
            pool_size=10,
            max_overflow=20,
        )
        Base.metadata.create_all(bind=engine)
        SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
        print("Database connection initialized and tables verified.")
        return True
    except Exception as exc:
        print(
            f"Warning: Could not connect to PostgreSQL ({exc}). Inference logs will fall back to in-memory/console."
        )
        engine = None
        SessionLocal = None
        return False


def save_inference_log(
    request_id: str,
    features: Dict[str, Any],
    prediction: int,
    probability: float,
    risk_decision: str,
    latency_ms: float,
    model_version: str = "v1.0",
) -> bool:
    """
    Saves an inference record into PostgreSQL.
    """
    if SessionLocal is None:
        return False

    session = SessionLocal()
    try:
        log_entry = InferenceLog(
            request_id=request_id,
            timestamp=datetime.utcnow(),
            features_json=json.dumps(features),
            prediction=prediction,
            probability=probability,
            risk_decision=risk_decision,
            latency_ms=latency_ms,
            model_version=model_version,
        )
        session.add(log_entry)
        session.commit()
        return True
    except Exception as exc:
        session.rollback()
        print(f"Failed to write inference log: {exc}")
        return False
    finally:
        session.close()
