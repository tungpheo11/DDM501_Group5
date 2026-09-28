import json
import logging
from datetime import UTC, datetime, timedelta

import pytest

from credit_risk.config.logging import PII_FIELDS, JsonFormatter
from credit_risk.data.schema import ALL_FEATURES
from credit_risk.responsible_ai import privacy
from credit_risk.serving import database


def test_inventory_covers_every_model_feature():
    assert set(ALL_FEATURES) <= set(privacy.PII_INVENTORY)
    protected = {k for k, v in privacy.PII_INVENTORY.items() if v["category"] == "protected_attribute"}
    assert protected == {"SEX", "AGE", "EDUCATION", "MARRIAGE"}


def test_log_redaction_covers_every_model_feature():
    assert set(ALL_FEATURES) <= PII_FIELDS


def test_pseudonymize_is_keyed_and_deterministic(monkeypatch):
    first = privacy.pseudonymize("req_000001", key="k1")
    assert first == privacy.pseudonymize("req_000001", key="k1")
    assert first != privacy.pseudonymize("req_000001", key="k2")
    assert first != privacy.pseudonymize("req_000002", key="k1")
    assert len(first) == 16 and "req" not in first
    monkeypatch.setenv(privacy.PSEUDONYMIZATION_KEY_ENV, "k1")
    assert privacy.pseudonymize("req_000001") == first


def test_pseudonymize_requires_a_key(monkeypatch):
    monkeypatch.delenv(privacy.PSEUDONYMIZATION_KEY_ENV, raising=False)
    with pytest.raises(ValueError, match="PSEUDONYMIZATION_KEY"):
        privacy.pseudonymize("req_000001")


@pytest.mark.parametrize(("age", "band"), [(18, "<20"), (25, "20-29"), (39, "30-39"), (59, "50-59"), (75, "60+")])
def test_age_band(age, band):
    assert privacy.age_band(age) == band


@pytest.mark.parametrize(
    ("limit", "band"), [(10_000, "<50k"), (50_000, "50k-100k"), (150_000, "100k-200k"), (1e6, "500k+")]
)
def test_limit_band(limit, band):
    assert privacy.limit_band(limit) == band


def test_generalize_record_drops_protected_and_bands_quasi_identifiers():
    record = privacy.generalize_record(
        {"SEX": 1, "EDUCATION": 2, "MARRIAGE": 1, "AGE": 34, "LIMIT_BAL": 80000, "PAY_0": 2}
    )
    assert record == {"AGE": "30-39", "LIMIT_BAL": "50k-100k", "PAY_0": 2}


def test_structured_logs_never_contain_raw_applicant_fields(valid_payload):
    record = logging.LogRecord("t", logging.INFO, __file__, 1, "scored", None, None)
    record.features = valid_payload
    record.context = {"AGE": valid_payload["AGE"], "nested": [{"LIMIT_BAL": valid_payload["LIMIT_BAL"]}]}
    entry = json.loads(JsonFormatter().format(record))
    privacy.assert_no_raw_pii(entry, valid_payload)


def test_assert_no_raw_pii_detects_leak(valid_payload):
    with pytest.raises(AssertionError, match="AGE"):
        privacy.assert_no_raw_pii({"extra": {"AGE": valid_payload["AGE"]}}, valid_payload)


def test_retention_cutoff():
    now = datetime(2026, 9, 28, 12, tzinfo=UTC)
    assert privacy.retention_cutoff(90, now) == datetime(2026, 6, 30, 12)
    with pytest.raises(ValueError):
        privacy.retention_cutoff(0)


def test_purge_inference_logs_deletes_only_expired_rows(valid_payload):
    assert database.init_db("sqlite:///:memory:")
    database.save_inference_logs(
        [
            {
                "request_id": f"r{i}",
                "features": valid_payload,
                "prediction": 0,
                "probability": 0.1,
                "risk_decision": "APPROVE",
                "latency_ms": 1.0,
            }
            for i in range(3)
        ]
    )
    session = database._session_factory()
    old = session.query(database.InferenceLog).filter(database.InferenceLog.request_id == "r0").one()
    old.timestamp = datetime.now(UTC).replace(tzinfo=None) - timedelta(days=120)
    session.commit()
    session.close()

    assert privacy.purge_inference_logs(90, dry_run=True) == 1
    assert database.count_inference_logs() == 3
    assert privacy.purge_inference_logs(90) == 1
    assert database.count_inference_logs() == 2
