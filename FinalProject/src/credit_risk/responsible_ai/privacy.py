"""Privacy controls: PII inventory, pseudonymization, generalization and log retention.

The UCI dataset carries no direct identifiers (no name, national ID or account number),
but every row is still personal data: demographics are *protected attributes* and the
repayment/bill history is *financial* personal data. Controls:

* application logs never contain raw cardholder fields (``credit_risk.config.logging``
  redacts them; :func:`assert_no_raw_pii` is used by tests);
* identifiers that leave the serving boundary are pseudonymized with a keyed HMAC;
* analytics exports generalize quasi-identifiers (age band, limit band) and drop
  protected attributes that are not needed;
* inference logs (which must keep raw features for drift detection and retraining) are
  purged after ``retention_days`` (:func:`purge_inference_logs`).
"""

from __future__ import annotations

import hashlib
import hmac
import os
from collections.abc import Mapping
from datetime import UTC, datetime, timedelta
from typing import Any

from credit_risk.data.schema import ALL_FEATURES

PSEUDONYMIZATION_KEY_ENV = "PSEUDONYMIZATION_KEY"
DEFAULT_RETENTION_DAYS = 90

PII_INVENTORY: dict[str, dict[str, str]] = {
    "LIMIT_BAL": {"category": "financial", "sensitivity": "high", "treatment": "generalize to band in exports"},
    "SEX": {"category": "protected_attribute", "sensitivity": "special", "treatment": "fairness audit only; drop"},
    "EDUCATION": {"category": "protected_attribute", "sensitivity": "high", "treatment": "fairness audit only; drop"},
    "MARRIAGE": {"category": "protected_attribute", "sensitivity": "special", "treatment": "fairness audit only; drop"},
    "AGE": {"category": "protected_attribute", "sensitivity": "high", "treatment": "generalize to age band"},
    **{
        f"PAY_{i}": {"category": "financial_behaviour", "sensitivity": "high", "treatment": "keep (model input)"}
        for i in (0, 2, 3, 4, 5, 6)
    },
    **{
        f"BILL_AMT{i}": {"category": "financial", "sensitivity": "high", "treatment": "keep (model input)"}
        for i in range(1, 7)
    },
    **{
        f"PAY_AMT{i}": {"category": "financial", "sensitivity": "high", "treatment": "keep (model input)"}
        for i in range(1, 7)
    },
    "request_id": {"category": "pseudonymous_identifier", "sensitivity": "medium", "treatment": "HMAC pseudonym"},
}
DROPPED_IN_EXPORTS: frozenset[str] = frozenset({"SEX", "EDUCATION", "MARRIAGE"})

LIMIT_BANDS: tuple[tuple[float, str], ...] = (
    (50_000, "<50k"),
    (100_000, "50k-100k"),
    (200_000, "100k-200k"),
    (500_000, "200k-500k"),
)


def pseudonymize(value: str, key: str | None = None, length: int = 16) -> str:
    """Keyed, deterministic pseudonym (HMAC-SHA256, hex-truncated) of an identifier.

    The same identifier maps to the same pseudonym (joins still work) but cannot be
    reversed or brute-forced without the key.

    Raises:
        ValueError: if no key is given and ``PSEUDONYMIZATION_KEY`` is unset.
    """
    secret = key if key is not None else os.getenv(PSEUDONYMIZATION_KEY_ENV, "")
    if not secret:
        raise ValueError(f"Pseudonymization key missing: set {PSEUDONYMIZATION_KEY_ENV}")
    digest = hmac.new(secret.encode("utf-8"), str(value).encode("utf-8"), hashlib.sha256).hexdigest()
    return digest[:length]


def age_band(age: float) -> str:
    """Generalize an exact age to a 10-year band (``"30-39"``); ``"60+"`` above 59."""
    years = int(age)
    if years < 20:
        return "<20"
    if years >= 60:
        return "60+"
    lower = years // 10 * 10
    return f"{lower}-{lower + 9}"


def limit_band(limit_bal: float) -> str:
    """Generalize the credit limit to a coarse band."""
    for upper, label in LIMIT_BANDS:
        if limit_bal < upper:
            return label
    return "500k+"


def generalize_record(features: Mapping[str, Any]) -> dict[str, Any]:
    """Export-safe copy of one cardholder: bands for AGE/LIMIT_BAL, protected attributes dropped."""
    record = {key: value for key, value in features.items() if key not in DROPPED_IN_EXPORTS}
    if "AGE" in record:
        record["AGE"] = age_band(float(record["AGE"]))
    if "LIMIT_BAL" in record:
        record["LIMIT_BAL"] = limit_band(float(record["LIMIT_BAL"]))
    return record


def assert_no_raw_pii(entry: Mapping[str, Any], raw: Mapping[str, Any]) -> None:
    """Raise ``AssertionError`` when a structured log ``entry`` exposes a raw cardholder field.

    Checks every schema feature key at any nesting level of ``entry`` whose value equals
    the raw value in ``raw``.
    """

    def _walk(node: Any) -> None:
        if isinstance(node, Mapping):
            for key, value in node.items():
                if key in ALL_FEATURES and key in raw and value == raw[key]:
                    raise AssertionError(f"raw cardholder field {key!r} leaked into a log entry")
                _walk(value)
        elif isinstance(node, list | tuple):
            for item in node:
                _walk(item)

    _walk(entry)


def retention_cutoff(retention_days: int = DEFAULT_RETENTION_DAYS, now: datetime | None = None) -> datetime:
    """Naive-UTC timestamp before which inference logs must be deleted."""
    if retention_days < 1:
        raise ValueError("retention_days must be >= 1")
    current = now or datetime.now(UTC)
    return (current - timedelta(days=retention_days)).replace(tzinfo=None)


def purge_inference_logs(retention_days: int = DEFAULT_RETENTION_DAYS, *, dry_run: bool = False) -> int:
    """Delete inference logs older than ``retention_days``; return the number of rows affected.

    Requires :func:`credit_risk.serving.database.init_db` to have been called. With
    ``dry_run`` the rows are only counted.
    """
    from credit_risk.serving import database

    factory = database._session_factory
    if factory is None:
        return 0
    cutoff = retention_cutoff(retention_days)
    session = factory()
    try:
        query = session.query(database.InferenceLog).filter(database.InferenceLog.timestamp < cutoff)
        if dry_run:
            return int(query.count())
        deleted = int(query.delete(synchronize_session=False))
        session.commit()
        return deleted
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
