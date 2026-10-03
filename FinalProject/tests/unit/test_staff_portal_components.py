"""Staff portal building blocks: settings, login throttle, catalog, scoring client, simulator, store, formatters."""

from __future__ import annotations

import json
import threading
from collections.abc import Callable
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import httpx
import pytest

from credit_risk.config import Settings
from credit_risk.serving.database import Base as ApiBase
from credit_risk.serving.database import InferenceLog
from staff_portal.auth import LoginThrottle, authenticate
from staff_portal.catalog import FEATURES, build_catalog, fold_text, load_feature_rows
from staff_portal.config import hash_password, load_portal_settings, load_users
from staff_portal.scoring_client import ApiResult, ScoringApiError, ScoringClient
from staff_portal.simulator import SimulationBusyError, SimulationManager, SimulationRejectedError
from staff_portal.store import AlreadyDecidedError, LogFilters, PortalStore, StoreUnavailableError, utcnow
from staff_portal.views import (
    format_money,
    format_number,
    format_percent,
    guardrails,
    reason_codes,
    static_fingerprint,
)

# --- settings ------------------------------------------------------------------------


def test_load_users_hashes_plain_passwords_and_skips_unconfigured_roles() -> None:
    preset = hash_password("analyst-secret", rounds=4).decode()
    users = load_users(
        {
            "PORTAL_CSKH_PASSWORD": "cskh-secret",
            "PORTAL_CSKH_NAME": "Phạm Thị Lan",
            "PORTAL_ANALYST_USERNAME": "rui-ro",
            "PORTAL_ANALYST_PASSWORD_HASH": preset,
            "PORTAL_ANALYST_PASSWORD": "ignored-when-hash-is-set",
        },
        rounds=4,
    )
    assert [(user.username, user.role) for user in users] == [("cskh", "cskh"), ("rui-ro", "analyst")]
    assert users[0].display_name == "Phạm Thị Lan"
    assert b"cskh-secret" not in users[0].password_hash
    assert "cskh-secret" not in repr(users[0])


def test_load_portal_settings_from_env(settings: Settings) -> None:
    cfg = load_portal_settings(
        settings,
        {
            "PORTAL_SESSION_SECRET": "s3cret",
            "PORTAL_ADMIN_PASSWORD": "admin-secret",
            "PORTAL_BCRYPT_ROUNDS": "4",
            "PORTAL_DEMO_MODE": "true",
            "PORTAL_API_URL": "http://api:8000/",
            "PORTAL_API_KEY": "portal-key",
            "DRIFT_MONITOR_URL": "http://drift-monitor:8085/",
            "PORTAL_GRAFANA_URL": "https://grafana.example",
            "PORTAL_SIMULATE_RATE_PER_SECOND": "5",
        },
    )
    assert cfg.demo_mode is True
    assert cfg.api_url == "http://api:8000"
    assert cfg.api_key == "portal-key"
    assert cfg.drift_monitor_url == "http://drift-monitor:8085"
    assert cfg.links.grafana == "https://grafana.example"
    assert cfg.links.mlflow == "http://localhost:15040"
    assert cfg.simulate_rate_per_second == 5
    assert cfg.database_url == settings.database.url
    assert cfg.batch_max_size == settings.serving.batch_max_size
    assert [user.role for user in cfg.users] == ["admin"]
    assert cfg.user("admin") is not None
    assert cfg.user("nobody") is None
    assert "s3cret" not in repr(cfg)
    assert "portal-key" not in repr(cfg)


def test_load_portal_settings_defaults_are_safe(settings: Settings) -> None:
    cfg = load_portal_settings(settings, {})
    assert cfg.demo_mode is False
    assert cfg.cookie_secure is False
    assert cfg.users == ()
    assert len(cfg.session_secret) >= 32
    assert cfg.api_key == settings.serving.client_api_key
    assert cfg.tz.utcoffset(None) == timedelta(hours=7)


# --- authentication ------------------------------------------------------------------


def test_authenticate(settings: Settings) -> None:
    cfg = load_portal_settings(settings, {"PORTAL_CSKH_PASSWORD": "right", "PORTAL_BCRYPT_ROUNDS": "4"})
    assert authenticate(cfg, "cskh", "right") is not None
    assert authenticate(cfg, "cskh", "wrong") is None
    assert authenticate(cfg, "ghost", "right") is None


def test_authenticate_rejects_malformed_hash(settings: Settings) -> None:
    cfg = load_portal_settings(settings, {"PORTAL_ADMIN_PASSWORD_HASH": "not-a-bcrypt-hash"})
    assert authenticate(cfg, "admin", "anything") is None


def test_login_throttle_locks_and_expires() -> None:
    now = [1000.0]
    throttle = LoginThrottle(max_failures=3, lockout_seconds=60, clock=lambda: now[0])
    for _ in range(3):
        assert not throttle.is_locked("admin")
        throttle.record_failure("admin")
    assert throttle.is_locked("admin")
    assert not throttle.is_locked("cskh")
    now[0] += 61
    assert not throttle.is_locked("admin")
    throttle.record_failure("admin")
    throttle.reset("admin")
    assert not throttle.is_locked("admin")


# --- catalog -------------------------------------------------------------------------


def test_catalog_is_deterministic_and_mixes_sources(settings: Settings) -> None:
    paths = (settings.paths.normal_stream, settings.paths.drifted_stream)
    first = build_catalog(*paths, size=50, drifted_share=0.3, seed=11)
    second = build_catalog(*paths, size=50, drifted_share=0.3, seed=11)
    other = build_catalog(*paths, size=50, drifted_share=0.3, seed=12)
    assert [c.customer_id for c in first.all()] == [c.customer_id for c in second.all()]
    assert [c.customer_id for c in first.all()] != [c.customer_id for c in other.all()]
    assert len(first) == 50
    genz = [c for c in first.all() if c.source == "genz"]
    assert len(genz) == 15
    assert all(c.age < 30 for c in genz)
    assert len({c.customer_id for c in first.all()}) == 50
    member = first.all()[0]
    assert member.card_masked == f"**** {member.card_last4}"
    assert set(member.payload()) == set(FEATURES)
    assert member.customer_id not in json.dumps(member.payload())
    assert member.statement_day in (5, 15, 25)
    assert member.gender_label in ("Nam", "Nữ")
    assert member.utilization >= 0


def test_catalog_search(settings: Settings) -> None:
    catalog = build_catalog(settings.paths.normal_stream, settings.paths.drifted_stream, size=40, seed=3)
    member = catalog.all()[5]
    assert member in catalog.search(fold_text(member.full_name))
    assert member in catalog.search(member.full_name.upper())
    assert catalog.search(member.customer_id.lower()) == [member]
    assert member in catalog.search(f"**** {member.card_last4}")
    assert catalog.search("zzzz") == []
    assert len(catalog.search("", limit=7)) == 7
    assert catalog.get("KH000000") is None
    by_day = catalog.by_statement_day(member.statement_day)
    assert member in by_day
    assert len(catalog.by_statement_day(None)) == 40


def test_fold_text_removes_vietnamese_accents() -> None:
    assert fold_text("Nguyễn Đức Thắng") == "nguyen duc thang"


def test_load_feature_rows_casts_types(settings: Settings) -> None:
    row = load_feature_rows(settings.paths.normal_stream)[0]
    assert list(row) == list(FEATURES)
    assert isinstance(row["LIMIT_BAL"], float)
    assert isinstance(row["AGE"], int)
    assert isinstance(row["PAY_0"], int)


# --- scoring client ------------------------------------------------------------------


def _client(handler: Callable[[httpx.Request], httpx.Response]) -> ScoringClient:
    return ScoringClient(
        "http://api", "secret-key", client=httpx.Client(base_url="http://api", transport=httpx.MockTransport(handler))
    )


def test_scoring_client_sends_key_and_batch_field() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json={"ok": True})

    client = _client(handler)
    assert client.predict({"AGE": 30}).body == {"ok": True}
    client.predict_batch([{"AGE": 30}])
    client.explain({"AGE": 30})
    client.model_info()
    assert client.readiness() == {"ok": True}
    assert [r.url.path for r in seen] == [
        "/api/v1/predict",
        "/api/v1/predict/batch",
        "/api/v1/explain",
        "/api/v1/model/info",
        "/health/ready",
    ]
    assert all(r.headers["X-API-Key"] == "secret-key" for r in seen[:4])
    assert "X-API-Key" not in seen[4].headers
    assert json.loads(seen[1].content) == {"cardholders": [{"AGE": 30}]}
    client.close()


def test_scoring_client_maps_errors() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/v1/predict":
            return httpx.Response(422, json={"code": "VALIDATION_ERROR", "message": "AGE out of range"})
        if request.url.path == "/health/ready":
            return httpx.Response(503, json={"code": "NOT_READY", "message": "model missing"})
        return httpx.Response(500, text="boom")

    client = _client(handler)
    with pytest.raises(ScoringApiError) as excinfo:
        client.predict({})
    assert (excinfo.value.status_code, excinfo.value.code) == (422, "VALIDATION_ERROR")
    with pytest.raises(ScoringApiError) as excinfo:
        client.model_info()
    assert (excinfo.value.status_code, excinfo.value.code) == (500, "HTTP_ERROR")
    assert client.readiness() == {"status": "not_ready", "reasons": ["model missing"]}


def test_scoring_client_unreachable() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectTimeout("timeout", request=request)

    client = _client(handler)
    with pytest.raises(ScoringApiError) as excinfo:
        client.predict({})
    assert (excinfo.value.status_code, excinfo.value.code) == (503, "API_UNREACHABLE")
    assert client.readiness()["status"] == "not_ready"


def test_static_fingerprint_tracks_asset_content(tmp_path: Path) -> None:
    (tmp_path / "css").mkdir()
    asset = tmp_path / "css" / "portal.css"
    asset.write_text(".page { margin: 0; }")
    first = static_fingerprint(tmp_path)
    assert first == static_fingerprint(tmp_path)
    assert len(first) == 12
    asset.write_text(".page { margin: 1px; }")
    assert static_fingerprint(tmp_path) != first


def test_scoring_client_readiness_uses_probe_timeout() -> None:
    timeouts: list[dict[str, Any]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        timeouts.append(request.extensions["timeout"])
        return httpx.Response(200, json={"status": "ready"})

    client = _client(handler)
    assert client.readiness(timeout_seconds=2.0) == {"status": "ready"}
    client.readiness()
    assert timeouts[0]["read"] == 2.0
    assert timeouts[1]["read"] != 2.0


def test_scoring_client_owns_default_client() -> None:
    client = ScoringClient("http://127.0.0.1:9", "k", timeout_seconds=0.2)
    client.close()


# --- simulator -----------------------------------------------------------------------


class _FakeScoring:
    def __init__(self, fail_every: int = 0, gate: threading.Event | None = None) -> None:
        self.calls: list[dict[str, Any]] = []
        self.fail_every = fail_every
        self.gate = gate

    def predict(self, payload: dict[str, Any]) -> ApiResult:
        if self.gate is not None:
            self.gate.wait(5)
        self.calls.append(payload)
        if self.fail_every and len(self.calls) % self.fail_every == 0:
            raise ScoringApiError(503, "MODEL_UNAVAILABLE", "down")
        return ApiResult(body={"risk_decision": "REVIEW" if payload["AGE"] < 30 else "APPROVE"}, roundtrip_ms=1.0)


def _manager(settings: Settings, scoring: Any, **kwargs: Any) -> SimulationManager:
    sources = {"normal": settings.paths.normal_stream, "genz": settings.paths.drifted_stream}
    return SimulationManager(scoring, sources, rate_per_second=0, max_count=50, seed=1, **kwargs)


def test_simulator_completes_and_counts(settings: Settings) -> None:
    finished: list[str] = []
    scoring = _FakeScoring(fail_every=4)
    manager = _manager(settings, scoring, on_finish=lambda job: finished.append(job.status))
    snapshot = manager.start("genz", 12, "admin")
    assert snapshot["requested"] == 12
    assert manager.wait(10)
    job = manager.current()
    assert job is not None
    assert job["status"] == "completed"
    assert (job["attempted"], job["succeeded"], job["errors"]) == (12, 9, 3)
    assert job["decisions"]["REVIEW"] == 9
    assert job["last_error"] == "503 MODEL_UNAVAILABLE"
    assert all(call["AGE"] < 30 for call in scoring.calls)
    assert len({json.dumps(call, sort_keys=True) for call in scoring.calls}) == 12
    assert finished == ["completed"]
    assert not manager.is_running()


def test_simulator_rejects_bad_requests_and_concurrent_jobs(settings: Settings) -> None:
    gate = threading.Event()
    manager = _manager(settings, _FakeScoring(gate=gate))
    with pytest.raises(SimulationRejectedError):
        manager.start("chaos", 5, "admin")
    with pytest.raises(SimulationRejectedError):
        manager.start("normal", 51, "admin")
    assert manager.stop("admin") is False
    manager.start("normal", 5, "admin")
    assert manager.is_running()
    with pytest.raises(SimulationBusyError):
        manager.start("normal", 5, "admin")
    assert manager.stop("admin") is True
    gate.set()
    assert manager.wait(10)
    job = manager.current()
    assert job is not None
    assert job["status"] == "stopped"
    assert job["stopped_by"] == "admin"
    assert job["attempted"] <= 1


def test_simulator_rate_limit_and_shutdown(settings: Settings) -> None:
    sources = {"normal": settings.paths.normal_stream}
    manager = SimulationManager(_FakeScoring(), sources, rate_per_second=2, max_count=10, seed=1)
    manager.start("normal", 10, "admin")
    manager.shutdown()
    job = manager.current()
    assert job is not None
    assert job["status"] == "stopped"
    assert job["attempted"] < 10


def test_simulator_survives_crashing_client_and_callback(settings: Settings) -> None:
    class Broken:
        def predict(self, payload: dict[str, Any]) -> ApiResult:
            raise RuntimeError("unexpected")

    def explode(job: Any) -> None:
        raise RuntimeError("audit down")

    manager = _manager(settings, Broken(), on_finish=explode)
    manager.start("normal", 3, "admin")
    assert manager.wait(10)
    job = manager.current()
    assert job is not None
    assert job["status"] == "failed"
    assert job["last_error"] == "RuntimeError"


def test_simulator_samples_with_replacement_beyond_source_size(settings: Settings, tmp_path: Path) -> None:
    source = tmp_path / "tiny.csv"
    lines = settings.paths.normal_stream.read_text(encoding="utf-8").splitlines()[:4]
    source.write_text("\n".join(lines) + "\n", encoding="utf-8")
    scoring = _FakeScoring()
    manager = SimulationManager(scoring, {"normal": source}, rate_per_second=0, max_count=20, seed=1)
    manager.start("normal", 9, "admin")
    assert manager.wait(10)
    assert len(scoring.calls) == 9


# --- store ---------------------------------------------------------------------------


@pytest.fixture
def store(tmp_path: Path) -> PortalStore:
    portal_store = PortalStore(f"sqlite:///{tmp_path / 'portal.db'}")
    ApiBase.metadata.create_all(bind=portal_store.engine)
    return portal_store


def _seed_logs(store: PortalStore) -> None:
    base = datetime(2026, 10, 1, 8, 0, 0)
    with store.session() as session:
        for index, (decision, version) in enumerate(
            [("APPROVE", "v1"), ("APPROVE", "v1"), ("REVIEW", "v1"), ("DECLINE", "v2"), ("APPROVE", "v2")]
        ):
            session.add(
                InferenceLog(
                    request_id=f"req-{index}",
                    timestamp=base + timedelta(hours=index),
                    features_json=json.dumps({"AGE": 30 + index}),
                    prediction=int(decision == "DECLINE"),
                    probability=0.1 * (index + 1),
                    risk_decision=decision,
                    latency_ms=10.0 + index,
                    model_version=version,
                )
            )


def test_store_log_queries(store: PortalStore) -> None:
    _seed_logs(store)
    assert store.count_logs() == 5
    page = store.query_logs(LogFilters(), page=1, page_size=2)
    assert (page.total, page.pages, [row.request_id for row in page.rows]) == (5, 3, ["req-4", "req-3"])
    assert store.query_logs(LogFilters(), page=99, page_size=2).page == 3
    assert store.query_logs(LogFilters(risk_decision="APPROVE"), 1, 10).total == 3
    assert store.query_logs(LogFilters(model_version="v2"), 1, 10).total == 2
    window = LogFilters(start=datetime(2026, 10, 1, 9, 0), end=datetime(2026, 10, 1, 11, 0))
    assert [row.request_id for row in store.query_logs(window, 1, 10).rows] == ["req-3", "req-2", "req-1"]
    stats = store.log_stats(LogFilters())
    assert stats["by_decision"] == {"APPROVE": 3, "REVIEW": 1, "DECLINE": 1}
    assert stats["avg_probability"] == pytest.approx(0.3)
    assert stats["max_latency_ms"] == 14.0
    assert stats["first"] == datetime(2026, 10, 1, 8, 0)
    empty = store.log_stats(LogFilters(risk_decision="REVIEW", model_version="v2"))
    assert empty["total"] == 0
    assert empty["avg_probability"] is None
    assert store.model_versions() == ["v1", "v2"]
    first_id = page.rows[0].id
    assert store.get_log(first_id).request_id == "req-4"


def test_store_delete_all_logs_keeps_table_and_audits(store: PortalStore) -> None:
    _seed_logs(store)
    assert store.delete_all_logs("admin") == 5
    assert store.count_logs() == 0
    entry = store.audit_entries()[0]
    assert (entry.actor, entry.action, entry.rows_affected) == ("admin", "delete_inference_logs", 5)
    _seed_logs(store)
    assert store.count_logs() == 5


def _request_values(**overrides: Any) -> dict[str, Any]:
    values: dict[str, Any] = {
        "created_by": "cskh",
        "customer_id": "KH123456",
        "request_type": "LIMIT_INCREASE",
        "requested_amount": None,
        "note": None,
        "api_request_id": "req-1",
        "risk_decision": "REVIEW",
        "default_probability": 0.45,
        "credit_score": 600,
        "credit_tier": "SUBPRIME",
        "recommended_limit_ntd": 50000.0,
        "top_risk_factors": ["Payment Lag: 1 month"],
        "policy_guardrails": {"age_verification": "PASS"},
        "model_version": "v1",
        "api_latency_ms": 12.0,
        "roundtrip_ms": 20.0,
    }
    return values | overrides


def test_store_review_queue_and_decisions(store: PortalStore) -> None:
    review = store.add_limit_request(**_request_values())
    store.add_limit_request(**_request_values(risk_decision="APPROVE", created_by="other"))
    assert [item.id for item in store.review_queue()] == [review.id]
    assert store.get_limit_request(review.id).top_risk_factors == ["Payment Lag: 1 month"]
    assert store.get_limit_request(review.id).policy_guardrails == {"age_verification": "PASS"}
    assert len(store.recent_requests("cskh")) == 1
    assert len(store.recent_requests()) == 2

    store.record_decision(review.id, "chuyenvien", "SUSPEND", 0.0, None)
    with pytest.raises(AlreadyDecidedError):
        store.record_decision(review.id, "chuyenvien", "KEEP", 1.0, None)
    assert store.review_queue() == []
    decision, request = store.recent_decisions()[0]
    assert (decision.action, request.id) == ("SUSPEND", review.id)


def test_store_batch_reviews(store: PortalStore) -> None:
    saved = store.save_batch_review(
        created_by="chuyenvien",
        cohort="day-5",
        api_request_id="batch-1",
        model_version="v1",
        latency_ms=33.0,
        decision_summary={"APPROVE": 1, "REVIEW": 0, "DECLINE": 1},
        results=[{"customer_id": "KH1", "full_name": "Lê Văn An"}, {"customer_id": "KH2", "full_name": "Đỗ Thị Hà"}],
    )
    assert saved.count == 2
    assert store.get_batch_review(saved.id).results[1]["full_name"] == "Đỗ Thị Hà"
    assert store.latest_batch_review().id == saved.id
    assert store.recent_batch_reviews()[0].decision_summary["DECLINE"] == 1


def test_store_unavailable(tmp_path: Path) -> None:
    broken = PortalStore(f"sqlite:///{tmp_path / 'missing-dir' / 'portal.db'}")
    assert broken.ensure_schema() is False
    assert broken.ping() is False
    with pytest.raises(StoreUnavailableError):
        broken.count_logs()


def test_store_maps_query_errors(tmp_path: Path) -> None:
    store = PortalStore(f"sqlite:///{tmp_path / 'portal.db'}")
    with pytest.raises(StoreUnavailableError):
        store.count_logs()  # inference_logs is owned by the API and does not exist yet
    store.audit("admin", "noop")
    assert store.audit_entries()[0].action == "noop"
    assert utcnow().tzinfo is None


def test_store_in_memory_database() -> None:
    assert PortalStore("sqlite://").ensure_schema() is True


# --- formatters ----------------------------------------------------------------------


def test_formatters() -> None:
    assert format_money(200000) == "200.000 NT$"
    assert format_money(None) == "—"
    assert format_number(1234567.891, 2) == "1.234.567,89"
    assert format_number(None) == "—"
    assert format_percent(0.4231) == "42,3%"
    assert format_percent(None) == "—"


def test_reason_codes_and_guardrails() -> None:
    reasons = reason_codes(["Severe Delinquency: 2 months", "Repayment Discipline: on time", "Something new"])
    assert [(r["code"], r["adverse"]) for r in reasons] == [("R01", True), ("P01", False), ("R99", True)]
    assert reasons[2]["text"] == "Something new"
    checks = guardrails({"age_verification": "PASS", "delinquency_guardrail": "ELEVATED_DEFAULT_RISK", "x": "CLEAR"})
    assert checks == [
        {"name": "Xác minh tuổi", "value": "Đạt", "ok": True},
        {"name": "Kiểm soát trễ hạn", "value": "Rủi ro vỡ nợ cao", "ok": False},
        {"name": "x", "value": "Không có", "ok": True},
    ]
