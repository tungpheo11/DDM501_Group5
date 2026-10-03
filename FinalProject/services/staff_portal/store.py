"""Portal persistence: its own tables plus read/delete access to the API's ``inference_logs``.

Portal tables (``portal_limit_requests``, ``analyst_decisions``,
``portal_batch_reviews``, ``portal_audit_log``) live in the same database as the
inference log but in a separate SQLAlchemy metadata, so the portal never creates,
alters or drops ``inference_logs``. Analyst decisions are stored here and never
modify the API's log rows.
"""

from __future__ import annotations

import json
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import DateTime, Float, ForeignKey, Integer, String, Text, create_engine, func, select, text
from sqlalchemy.engine import Engine
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column, sessionmaker
from sqlalchemy.pool import StaticPool
from sqlalchemy.sql.elements import ColumnElement

from credit_risk.config import get_logger
from credit_risk.serving.database import InferenceLog

logger = get_logger(__name__)

DECISIONS: tuple[str, ...] = ("APPROVE", "REVIEW", "DECLINE")
ANALYST_ACTIONS: dict[str, str] = {
    "KEEP": "Giữ nguyên hạn mức",
    "REDUCE": "Hạ hạn mức",
    "SUSPEND": "Tạm khoá hạn mức",
}


def utcnow() -> datetime:
    """Naive UTC timestamp (same convention as ``inference_logs.timestamp``)."""
    return datetime.now(UTC).replace(tzinfo=None)


class PortalBase(DeclarativeBase):
    """Metadata of the portal-owned tables only."""


class LimitRequest(PortalBase):
    """A cardholder request created by customer service, with the API decision."""

    __tablename__ = "portal_limit_requests"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, index=True)
    created_by: Mapped[str] = mapped_column(String(64))
    customer_id: Mapped[str] = mapped_column(String(16), index=True)
    request_type: Mapped[str] = mapped_column(String(32))
    requested_amount: Mapped[float | None] = mapped_column(Float, nullable=True)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    api_request_id: Mapped[str] = mapped_column(String(64))
    risk_decision: Mapped[str] = mapped_column(String(16), index=True)
    default_probability: Mapped[float] = mapped_column(Float)
    credit_score: Mapped[int] = mapped_column(Integer)
    credit_tier: Mapped[str] = mapped_column(String(16))
    recommended_limit_ntd: Mapped[float] = mapped_column(Float)
    top_risk_factors_json: Mapped[str] = mapped_column(Text, default="[]")
    policy_guardrails_json: Mapped[str] = mapped_column(Text, default="{}")
    model_version: Mapped[str] = mapped_column(String(128))
    api_latency_ms: Mapped[float] = mapped_column(Float)
    roundtrip_ms: Mapped[float] = mapped_column(Float)

    @property
    def top_risk_factors(self) -> list[str]:
        """Decoded reason list returned by the API."""
        return list(json.loads(self.top_risk_factors_json or "[]"))

    @property
    def policy_guardrails(self) -> dict[str, str]:
        """Decoded guardrail checks returned by the API."""
        return dict(json.loads(self.policy_guardrails_json or "{}"))


class AnalystDecision(PortalBase):
    """Final human decision on a REVIEW case (human-in-the-loop)."""

    __tablename__ = "analyst_decisions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    limit_request_id: Mapped[int] = mapped_column(ForeignKey("portal_limit_requests.id"), unique=True)
    decided_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    analyst: Mapped[str] = mapped_column(String(64))
    action: Mapped[str] = mapped_column(String(16))
    new_limit_ntd: Mapped[float | None] = mapped_column(Float, nullable=True)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)


class BatchReview(PortalBase):
    """One post-statement limit review run through ``/predict/batch``."""

    __tablename__ = "portal_batch_reviews"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    created_by: Mapped[str] = mapped_column(String(64))
    cohort: Mapped[str] = mapped_column(String(64))
    count: Mapped[int] = mapped_column(Integer)
    api_request_id: Mapped[str] = mapped_column(String(64))
    model_version: Mapped[str] = mapped_column(String(128))
    latency_ms: Mapped[float] = mapped_column(Float)
    decision_summary_json: Mapped[str] = mapped_column(Text)
    results_json: Mapped[str] = mapped_column(Text)

    @property
    def decision_summary(self) -> dict[str, int]:
        """Number of cardholders per decision."""
        return dict(json.loads(self.decision_summary_json))

    @property
    def results(self) -> list[dict[str, Any]]:
        """Per-cardholder rows (identity + API outcome) in request order."""
        return list(json.loads(self.results_json))


class AuditEntry(PortalBase):
    """Who did what on administrative actions."""

    __tablename__ = "portal_audit_log"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, index=True)
    actor: Mapped[str] = mapped_column(String(64))
    action: Mapped[str] = mapped_column(String(64))
    rows_affected: Mapped[int | None] = mapped_column(Integer, nullable=True)
    detail: Mapped[str | None] = mapped_column(Text, nullable=True)


class StoreUnavailableError(Exception):
    """The database cannot be reached or a required table is missing."""


class AlreadyDecidedError(Exception):
    """The REVIEW case already has an analyst decision."""


@dataclass(frozen=True)
class LogFilters:
    """Filters of the admin inference-log table (``start``/``end`` are naive UTC)."""

    risk_decision: str | None = None
    model_version: str | None = None
    start: datetime | None = None
    end: datetime | None = None

    def clauses(self) -> list[ColumnElement[bool]]:
        """SQL predicates for these filters."""
        clauses: list[ColumnElement[bool]] = []
        if self.risk_decision:
            clauses.append(InferenceLog.risk_decision == self.risk_decision)
        if self.model_version:
            clauses.append(InferenceLog.model_version == self.model_version)
        if self.start:
            clauses.append(InferenceLog.timestamp >= self.start)
        if self.end:
            clauses.append(InferenceLog.timestamp <= self.end)
        return clauses


@dataclass(frozen=True)
class LogPage:
    """One page of the inference-log table."""

    rows: list[InferenceLog]
    total: int
    page: int
    page_size: int

    @property
    def pages(self) -> int:
        """Number of pages (at least 1)."""
        return max(1, -(-self.total // self.page_size))


class PortalStore:
    """Database access for the portal (thread-safe: one short session per call)."""

    def __init__(self, database_url: str) -> None:
        kwargs: dict[str, Any] = {"pool_pre_ping": True}
        if database_url.startswith("sqlite"):
            kwargs = {"connect_args": {"check_same_thread": False}}
            if database_url in ("sqlite://", "sqlite:///:memory:"):
                kwargs["poolclass"] = StaticPool
        self.engine: Engine = create_engine(database_url, **kwargs)
        self._sessions = sessionmaker(bind=self.engine, autoflush=False, expire_on_commit=False)
        self._schema_ready = False
        self._schema_lock = threading.Lock()

    def ensure_schema(self) -> bool:
        """Create the portal tables once; return False while the database is unreachable."""
        if self._schema_ready:
            return True
        with self._schema_lock:
            if self._schema_ready:
                return True
            try:
                PortalBase.metadata.create_all(bind=self.engine)
            except SQLAlchemyError as exc:
                logger.warning("Portal database not ready: %s", type(exc).__name__)
                return False
            self._schema_ready = True
            return True

    @contextmanager
    def session(self) -> Iterator[Session]:
        """Transactional session; database errors surface as :class:`StoreUnavailableError`."""
        if not self.ensure_schema():
            raise StoreUnavailableError("Không kết nối được cơ sở dữ liệu.")
        session = self._sessions()
        try:
            yield session
            session.commit()
        except SQLAlchemyError as exc:
            session.rollback()
            logger.error("Portal database error: %s", exc)
            raise StoreUnavailableError("Lỗi truy vấn cơ sở dữ liệu.") from exc
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    def ping(self) -> bool:
        """``SELECT 1`` against the database."""
        try:
            with self.engine.connect() as connection:
                connection.execute(text("SELECT 1"))
            return True
        except SQLAlchemyError:
            return False

    # --- customer service requests ------------------------------------------------

    def add_limit_request(self, **values: Any) -> LimitRequest:
        """Persist one request and its API decision."""
        values["top_risk_factors_json"] = json.dumps(values.pop("top_risk_factors", []), ensure_ascii=False)
        values["policy_guardrails_json"] = json.dumps(values.pop("policy_guardrails", {}), ensure_ascii=False)
        record = LimitRequest(created_at=utcnow(), **values)
        with self.session() as session:
            session.add(record)
            session.flush()
        return record

    def get_limit_request(self, request_id: int) -> LimitRequest | None:
        """Request by id."""
        with self.session() as session:
            return session.get(LimitRequest, request_id)

    def recent_requests(self, created_by: str | None = None, limit: int = 10) -> list[LimitRequest]:
        """Latest requests, optionally of one staff member."""
        query = select(LimitRequest).order_by(LimitRequest.id.desc()).limit(limit)
        if created_by:
            query = query.where(LimitRequest.created_by == created_by)
        with self.session() as session:
            return list(session.scalars(query))

    # --- analyst review queue -----------------------------------------------------

    def review_queue(self) -> list[LimitRequest]:
        """REVIEW requests without an analyst decision, oldest first."""
        decided = select(AnalystDecision.limit_request_id)
        query = (
            select(LimitRequest)
            .where(LimitRequest.risk_decision == "REVIEW", LimitRequest.id.not_in(decided))
            .order_by(LimitRequest.id)
        )
        with self.session() as session:
            return list(session.scalars(query))

    def decision_for(self, limit_request_id: int) -> AnalystDecision | None:
        """Analyst decision of a case, if any."""
        query = select(AnalystDecision).where(AnalystDecision.limit_request_id == limit_request_id)
        with self.session() as session:
            return session.scalars(query).first()

    def recent_decisions(self, limit: int = 10) -> list[tuple[AnalystDecision, LimitRequest]]:
        """Latest analyst decisions with their request."""
        query = (
            select(AnalystDecision, LimitRequest)
            .join(LimitRequest, AnalystDecision.limit_request_id == LimitRequest.id)
            .order_by(AnalystDecision.id.desc())
            .limit(limit)
        )
        with self.session() as session:
            return [(decision, request) for decision, request in session.execute(query).all()]

    def record_decision(
        self, limit_request_id: int, analyst: str, action: str, new_limit_ntd: float | None, note: str | None
    ) -> AnalystDecision:
        """Store the final decision of a case (one per case)."""
        if self.decision_for(limit_request_id) is not None:
            raise AlreadyDecidedError(limit_request_id)
        decision = AnalystDecision(
            limit_request_id=limit_request_id,
            decided_at=utcnow(),
            analyst=analyst,
            action=action,
            new_limit_ntd=new_limit_ntd,
            note=note,
        )
        with self.session() as session:
            session.add(decision)
            session.flush()
        return decision

    # --- batch reviews ------------------------------------------------------------

    def save_batch_review(
        self,
        *,
        created_by: str,
        cohort: str,
        api_request_id: str,
        model_version: str,
        latency_ms: float,
        decision_summary: dict[str, int],
        results: list[dict[str, Any]],
    ) -> BatchReview:
        """Persist a batch run so its CSV can be downloaded later."""
        review = BatchReview(
            created_at=utcnow(),
            created_by=created_by,
            cohort=cohort,
            count=len(results),
            api_request_id=api_request_id,
            model_version=model_version,
            latency_ms=latency_ms,
            decision_summary_json=json.dumps(decision_summary),
            results_json=json.dumps(results, ensure_ascii=False),
        )
        with self.session() as session:
            session.add(review)
            session.flush()
        return review

    def get_batch_review(self, review_id: int) -> BatchReview | None:
        """Batch run by id."""
        with self.session() as session:
            return session.get(BatchReview, review_id)

    def latest_batch_review(self) -> BatchReview | None:
        """Most recent batch run."""
        with self.session() as session:
            return session.scalars(select(BatchReview).order_by(BatchReview.id.desc()).limit(1)).first()

    def recent_batch_reviews(self, limit: int = 5) -> list[BatchReview]:
        """Latest batch runs."""
        with self.session() as session:
            return list(session.scalars(select(BatchReview).order_by(BatchReview.id.desc()).limit(limit)))

    # --- inference_logs (owned by the API) ----------------------------------------

    def query_logs(self, filters: LogFilters, page: int, page_size: int) -> LogPage:
        """Newest-first page of ``inference_logs`` matching ``filters``."""
        clauses = filters.clauses()
        with self.session() as session:
            total = int(session.scalar(select(func.count(InferenceLog.id)).where(*clauses)) or 0)
            pages = max(1, -(-total // page_size))
            page = min(max(page, 1), pages)
            rows = list(
                session.scalars(
                    select(InferenceLog)
                    .where(*clauses)
                    .order_by(InferenceLog.id.desc())
                    .offset((page - 1) * page_size)
                    .limit(page_size)
                )
            )
        return LogPage(rows=rows, total=total, page=page, page_size=page_size)

    def log_stats(self, filters: LogFilters) -> dict[str, Any]:
        """Counts per decision, mean probability/latency and time range for ``filters``."""
        clauses = filters.clauses()
        with self.session() as session:
            grouped = session.execute(
                select(InferenceLog.risk_decision, func.count(InferenceLog.id))
                .where(*clauses)
                .group_by(InferenceLog.risk_decision)
            ).all()
            by_decision: dict[str, int] = {str(decision): int(count) for decision, count in grouped}
            total, avg_probability, avg_latency, max_latency, first, last = session.execute(
                select(
                    func.count(InferenceLog.id),
                    func.avg(InferenceLog.probability),
                    func.avg(InferenceLog.latency_ms),
                    func.max(InferenceLog.latency_ms),
                    func.min(InferenceLog.timestamp),
                    func.max(InferenceLog.timestamp),
                ).where(*clauses)
            ).one()
        return {
            "total": int(total or 0),
            "by_decision": {decision: int(by_decision.get(decision, 0)) for decision in DECISIONS},
            "avg_probability": float(avg_probability) if avg_probability is not None else None,
            "avg_latency_ms": float(avg_latency) if avg_latency is not None else None,
            "max_latency_ms": float(max_latency) if max_latency is not None else None,
            "first": first,
            "last": last,
        }

    def model_versions(self) -> list[str]:
        """Distinct model versions present in the log."""
        with self.session() as session:
            query = select(InferenceLog.model_version).distinct().order_by(InferenceLog.model_version)
            return [str(version) for version in session.scalars(query) if version is not None]

    def get_log(self, log_id: int) -> InferenceLog | None:
        """One inference-log row."""
        with self.session() as session:
            return session.get(InferenceLog, log_id)

    def count_logs(self) -> int:
        """Total rows in ``inference_logs``."""
        with self.session() as session:
            return int(session.scalar(select(func.count(InferenceLog.id))) or 0)

    def delete_all_logs(self, actor: str) -> int:
        """Delete every ``inference_logs`` row (the table stays) and audit it in the same transaction."""
        with self.session() as session:
            deleted = session.query(InferenceLog).delete(synchronize_session=False)
            session.add(
                AuditEntry(
                    at=utcnow(),
                    actor=actor,
                    action="delete_inference_logs",
                    rows_affected=int(deleted),
                    detail="Xoá toàn bộ dòng trong inference_logs (chế độ demo)",
                )
            )
        logger.warning("inference_logs cleared", extra={"event": "inference_logs_cleared", "rows": int(deleted)})
        return int(deleted)

    # --- audit --------------------------------------------------------------------

    def audit(self, actor: str, action: str, detail: str | None = None, rows_affected: int | None = None) -> None:
        """Append one audit entry."""
        with self.session() as session:
            session.add(AuditEntry(at=utcnow(), actor=actor, action=action, detail=detail, rows_affected=rows_affected))

    def audit_entries(self, limit: int = 20) -> list[AuditEntry]:
        """Latest audit entries."""
        with self.session() as session:
            return list(session.scalars(select(AuditEntry).order_by(AuditEntry.id.desc()).limit(limit)))
