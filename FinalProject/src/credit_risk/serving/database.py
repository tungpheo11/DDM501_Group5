"""Inference-log persistence (PostgreSQL in production, SQLite in tests).

Every prediction is stored with its input features so the drift monitor can
compare production traffic with the training reference.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import Column, DateTime, Float, Integer, String, Text, create_engine, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import declarative_base, sessionmaker
from sqlalchemy.pool import StaticPool

from credit_risk.config import get_logger

logger = get_logger(__name__)

Base: Any = declarative_base()


def _utcnow() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


class InferenceLog(Base):
    """One scored request: features, output and operational metadata."""

    __tablename__ = "inference_logs"

    id = Column(Integer, primary_key=True, autoincrement=True)
    request_id = Column(String(64), index=True, nullable=False)
    timestamp = Column(DateTime, default=_utcnow, index=True, nullable=False)
    features_json = Column(Text, nullable=False)
    prediction = Column(Integer, nullable=False)
    probability = Column(Float, nullable=False)
    risk_decision = Column(String(16), nullable=False)
    latency_ms = Column(Float, nullable=False)
    model_version = Column(String(128), default="v1.0")


_engine: Engine | None = None
_session_factory: sessionmaker[Any] | None = None


def _engine_kwargs(url: str, pool_size: int, max_overflow: int) -> dict[str, Any]:
    if url.startswith("sqlite"):
        return {"connect_args": {"check_same_thread": False}, "poolclass": StaticPool}
    return {"pool_pre_ping": True, "pool_size": pool_size, "max_overflow": max_overflow}


def init_db(database_url: str, *, pool_size: int = 5, max_overflow: int = 5) -> bool:
    """Create the engine and tables; return False (and disable logging) when unreachable.

    The pool belongs to one process: with N API workers the database sees up to
    ``N * (pool_size + max_overflow)`` connections.
    """
    global _engine, _session_factory
    try:
        engine = create_engine(database_url, **_engine_kwargs(database_url, pool_size, max_overflow))
        Base.metadata.create_all(bind=engine)
    except Exception as exc:  # Driver-specific connection errors; the API must still start.
        logger.warning("Could not connect to inference-log database (%s). Inference logging disabled.", exc)
        _engine = None
        _session_factory = None
        return False
    _engine = engine
    _session_factory = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    logger.info("Inference-log database initialized and tables verified.")
    return True


def is_connected() -> bool:
    """Whether :func:`init_db` succeeded."""
    return _engine is not None


def save_inference_log(
    request_id: str,
    features: dict[str, Any],
    prediction: int,
    probability: float,
    risk_decision: str,
    latency_ms: float,
    model_version: str = "v1.0",
) -> bool:
    """Persist one inference record; return False when logging is disabled or fails."""
    if _session_factory is None:
        return False

    session = _session_factory()
    try:
        session.add(
            InferenceLog(
                request_id=request_id,
                timestamp=_utcnow(),
                features_json=json.dumps(features),
                prediction=prediction,
                probability=probability,
                risk_decision=risk_decision,
                latency_ms=latency_ms,
                model_version=model_version,
            )
        )
        session.commit()
        return True
    except Exception as exc:  # Never fail a prediction because the audit log write failed.
        session.rollback()
        logger.error("Failed to write inference log: %s", exc)
        return False
    finally:
        session.close()


def save_inference_logs(records: list[dict[str, Any]], model_version: str = "v1.0") -> int:
    """Persist several inference records in one transaction; return how many were written.

    Each record carries the keyword arguments of :func:`save_inference_log`
    (except ``model_version``).
    """
    if _session_factory is None or not records:
        return 0

    session = _session_factory()
    now = _utcnow()
    try:
        session.add_all(
            [
                InferenceLog(
                    request_id=record["request_id"],
                    timestamp=now,
                    features_json=json.dumps(record["features"]),
                    prediction=record["prediction"],
                    probability=record["probability"],
                    risk_decision=record["risk_decision"],
                    latency_ms=record["latency_ms"],
                    model_version=model_version,
                )
                for record in records
            ]
        )
        session.commit()
        return len(records)
    except Exception as exc:  # Never fail a prediction because the audit log write failed.
        session.rollback()
        logger.error("Failed to write %d inference logs: %s", len(records), exc)
        return 0
    finally:
        session.close()


def ping() -> bool:
    """Run ``SELECT 1`` against the inference-log database."""
    if _engine is None:
        return False
    try:
        with _engine.connect() as connection:
            connection.execute(text("SELECT 1"))
        return True
    except Exception as exc:  # Any driver error means the dependency is down.
        logger.warning("Inference-log database ping failed: %s", exc)
        return False


def count_inference_logs() -> int:
    """Number of stored inference records (0 when logging is disabled)."""
    if _session_factory is None:
        return 0
    session = _session_factory()
    try:
        return int(session.query(InferenceLog).count())
    finally:
        session.close()
