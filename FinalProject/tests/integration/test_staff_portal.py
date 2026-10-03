"""Staff portal end to end against the real scoring API app (shared SQLite database).

The portal's scoring client is wired to the scoring app's ``TestClient``, so every
portal action goes through ``/api/v1/*`` and lands in ``inference_logs`` exactly
as in the compose stack.
"""

from __future__ import annotations

import csv
import dataclasses
import io
import json
import re
from collections.abc import Callable, Iterator
from typing import Any

import httpx
import pytest
from fastapi import FastAPI
from fastapi.routing import APIRoute
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text

from credit_risk.config import Settings
from credit_risk.serving.app import create_app as create_api
from staff_portal.app import create_app as create_portal
from staff_portal.catalog import build_catalog
from staff_portal.config import ExternalLinks, PortalSettings, PortalUser, hash_password
from staff_portal.routes import admin as admin_routes
from staff_portal.routes import analyst as analyst_routes
from staff_portal.routes import cskh as cskh_routes
from staff_portal.scoring_client import ScoringClient
from staff_portal.store import LogFilters

pytestmark = pytest.mark.integration

API_KEY = "test-api-key"
PASSWORDS = {"cskh": "cskh-demo-pass", "chuyenvien": "analyst-demo-pass", "admin": "admin-demo-pass"}
USERS = (
    PortalUser("cskh", "cskh", "Nguyễn Thu Trang", hash_password(PASSWORDS["cskh"], rounds=4)),
    PortalUser("chuyenvien", "analyst", "Trần Minh Khoa", hash_password(PASSWORDS["chuyenvien"], rounds=4)),
    PortalUser("admin", "admin", "Lê Quốc Việt", hash_password(PASSWORDS["admin"], rounds=4)),
)
HTMX = {"HX-Request": "true"}
DRIFT_REPORT = {
    "is_drifted": True,
    "max_psi": 0.41,
    "drift_share": 0.25,
    "analyzed_at": "2026-10-03T08:00:00+00:00",
    "window_size": 500,
    "current_samples": 500,
    "reasons": ["AGE psi=0.41"],
    "drifted_columns": ["AGE"],
}
_CSRF = re.compile(r'name="csrf_token" value="([^"]+)"')


def _drift_monitor(request: httpx.Request) -> httpx.Response:
    if request.url.path == "/drift/latest":
        return httpx.Response(200, json=DRIFT_REPORT)
    return httpx.Response(404, json={"detail": "not found"})


@dataclasses.dataclass
class Stack:
    """Scoring API + portal sharing one database."""

    api: TestClient
    app: FastAPI
    database_url: str
    clients: list[TestClient]

    def client(self) -> TestClient:
        """A fresh browser (own cookie jar)."""
        browser = TestClient(self.app)
        browser.__enter__()
        self.clients.append(browser)
        return browser

    def login(self, username: str) -> TestClient:
        """A browser logged in as ``username``."""
        browser = self.client()
        token = csrf_of(browser.get("/login").text)
        response = browser.post(
            "/login",
            data={"username": username, "password": PASSWORDS[username], "csrf_token": token},
            follow_redirects=False,
        )
        assert response.status_code == 303, response.text
        return browser

    def count_logs(self) -> int:
        """Rows in ``inference_logs``."""
        engine = create_engine(self.database_url)
        try:
            with engine.connect() as connection:
                return int(connection.execute(text("SELECT COUNT(*) FROM inference_logs")).scalar_one())
        finally:
            engine.dispose()

    def decisions_by_customer(self) -> dict[str, str]:
        """API decision of every catalog cardholder (scored directly, not through the portal)."""
        catalog = self.app.state.portal.catalog
        members = catalog.all()
        response = self.api.post(
            "/api/v1/predict/batch",
            json={"cardholders": [member.payload() for member in members]},
            headers={"X-API-Key": API_KEY},
        )
        assert response.status_code == 200, response.text
        return {
            member.customer_id: item["risk_decision"]
            for member, item in zip(members, response.json()["predictions"], strict=True)
        }


def csrf_of(html: str) -> str:
    """CSRF token embedded in a rendered page."""
    match = _CSRF.search(html)
    assert match, "page has no CSRF field"
    return match.group(1)


def page_token(browser: TestClient, path: str) -> str:
    """CSRF token of the logged-in session, read from ``path``."""
    response = browser.get(path)
    assert response.status_code == 200, response.text
    return csrf_of(response.text)


@pytest.fixture
def make_stack(settings: Settings, tmp_path: Any) -> Iterator[Callable[..., Stack]]:
    stacks: list[Stack] = []
    catalog = build_catalog(settings.paths.normal_stream, settings.paths.drifted_stream, size=120, seed=2026)

    def _make(**overrides: Any) -> Stack:
        database_url = f"sqlite:///{tmp_path / 'stack.db'}"
        api_settings = dataclasses.replace(settings, database=dataclasses.replace(settings.database, url=database_url))
        api = TestClient(create_api(api_settings))
        api.__enter__()
        portal_settings = PortalSettings(
            users=USERS,
            session_secret="portal-test-session-secret",
            api_url="http://testserver",
            api_key=API_KEY,
            database_url=database_url,
            normal_stream=settings.paths.normal_stream,
            drifted_stream=settings.paths.drifted_stream,
            links=ExternalLinks(
                grafana="http://grafana.local",
                mlflow="http://mlflow.local",
                airflow="http://airflow.local",
                alertmanager="http://alertmanager.local",
                drift_monitor="http://drift.local",
            ),
            drift_monitor_url="http://drift-monitor:8085",
            simulate_rate_per_second=0,
            **{"demo_mode": True, **overrides},
        )
        scoring = ScoringClient(portal_settings.api_url, API_KEY, client=api)
        app = create_portal(
            portal_settings,
            scoring_client=scoring,
            catalog=catalog,
            http_client=httpx.Client(transport=httpx.MockTransport(_drift_monitor)),
            simulation_seed=7,
        )
        stack = Stack(api=api, app=app, database_url=database_url, clients=[])
        stacks.append(stack)
        return stack

    yield _make
    for stack in stacks:
        for browser in stack.clients:
            browser.__exit__(None, None, None)
        stack.api.__exit__(None, None, None)


@pytest.fixture
def stack(make_stack: Callable[..., Stack]) -> Stack:
    return make_stack()


def _first_with(stack: Stack, decision: str) -> str:
    customer_id = next((cid for cid, value in stack.decisions_by_customer().items() if value == decision), None)
    if customer_id is None:
        pytest.skip(f"demo catalog has no {decision} cardholder for this model")
    return customer_id


def _submit_request(stack: Stack, browser: TestClient, customer_id: str) -> int:
    token = page_token(browser, f"/cskh/customers/{customer_id}")
    response = browser.post(
        f"/cskh/customers/{customer_id}/requests",
        data={
            "request_type": "LIMIT_INCREASE",
            "requested_amount": "300.000",
            "note": "Khách gọi tổng đài",
            "csrf_token": token,
        },
        follow_redirects=False,
    )
    assert response.status_code == 303, response.text
    return int(response.headers["location"].rsplit("/", 1)[1])


# --- health, login, session --------------------------------------------------------


def test_health_and_login_page(stack: Stack) -> None:
    browser = stack.client()
    health = browser.get("/health").json()
    assert health["status"] == "ok"
    assert health["database"] == "ok"
    assert health["accounts"] == 3
    assert health["demo_mode"] is True

    page = browser.get("/login")
    assert page.status_code == 200
    assert csrf_of(page.text)
    assert "chuyenvien" in page.text
    assert re.search(r'href="/static/css/portal\.css\?v=[0-9a-f]{12}"', page.text)
    assert "script-src 'self'" in page.headers["content-security-policy"]
    assert page.headers["x-frame-options"] == "DENY"
    assert page.headers["cache-control"] == "no-store"


def test_liveness_and_readiness_probes(stack: Stack) -> None:
    browser = stack.client()
    live = browser.get("/health/live")
    assert live.status_code == 200
    assert live.json()["status"] == "alive"

    ready = browser.get("/health/ready")
    assert ready.status_code == 200, ready.text
    body = ready.json()
    assert body["status"] == "ready"
    assert body["reasons"] == []
    assert body["checks"]["database"]["status"] == "up"
    assert body["checks"]["scoring_api"]["status"] == "up"
    assert body["checks"]["scoring_api"]["detail"] in {"ready", "degraded"}
    assert API_KEY not in ready.text


def test_readiness_degraded_when_scoring_api_down(stack: Stack, monkeypatch: pytest.MonkeyPatch) -> None:
    portal = stack.app.state.portal
    monkeypatch.setattr(
        portal.scoring,
        "readiness",
        lambda timeout_seconds=None: {"status": "unreachable", "reasons": ["Không kết nối được API chấm điểm."]},
    )
    response = stack.client().get("/health/ready")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "degraded"
    assert body["checks"]["scoring_api"] == {
        "status": "down",
        "detail": "unreachable",
        "reasons": ["Không kết nối được API chấm điểm."],
    }
    assert body["reasons"] == ["scoring API is unreachable"]


def test_probes_fail_when_database_down(stack: Stack, monkeypatch: pytest.MonkeyPatch) -> None:
    portal = stack.app.state.portal
    monkeypatch.setattr(portal.store, "ping", lambda: False)
    browser = stack.client()

    assert browser.get("/health/live").status_code == 200
    ready = browser.get("/health/ready")
    assert ready.status_code == 503
    assert ready.json()["status"] == "not_ready"
    assert ready.json()["checks"]["database"] == {"status": "down"}
    summary = browser.get("/health")
    assert summary.status_code == 503
    assert summary.json()["status"] == "down"
    assert summary.json()["database"] == "down"


def test_session_cookie_is_httponly_and_samesite_lax(stack: Stack) -> None:
    browser = stack.client()
    response = browser.get("/login")
    cookie = response.headers["set-cookie"].lower()
    assert "portal_session=" in cookie
    assert "httponly" in cookie
    assert "samesite=lax" in cookie


@pytest.mark.parametrize(("username", "home"), [("cskh", "/cskh"), ("chuyenvien", "/analyst"), ("admin", "/admin")])
def test_each_role_logs_in_to_its_home(stack: Stack, username: str, home: str) -> None:
    browser = stack.client()
    token = csrf_of(browser.get("/login").text)
    response = browser.post(
        "/login",
        data={"username": username, "password": PASSWORDS[username], "csrf_token": token},
        follow_redirects=False,
    )
    assert response.status_code == 303
    assert response.headers["location"] == home
    landing = browser.get(home)
    assert landing.status_code == 200
    assert "Đăng xuất" in landing.text
    assert browser.get("/", follow_redirects=False).headers["location"] == home
    assert browser.get("/login", follow_redirects=False).headers["location"] == home


def test_login_rejects_bad_password_and_locks_out(stack: Stack) -> None:
    browser = stack.client()
    token = csrf_of(browser.get("/login").text)
    for _ in range(5):
        response = browser.post("/login", data={"username": "admin", "password": "wrong", "csrf_token": token})
        assert response.status_code == 401
        assert "Sai tên đăng nhập hoặc mật khẩu" in response.text
    locked = browser.post("/login", data={"username": "admin", "password": PASSWORDS["admin"], "csrf_token": token})
    assert locked.status_code == 429


def test_login_requires_csrf_token(stack: Stack) -> None:
    browser = stack.client()
    browser.get("/login")
    response = browser.post("/login", data={"username": "admin", "password": PASSWORDS["admin"]})
    assert response.status_code == 403
    assert browser.get("/admin", follow_redirects=False).status_code == 303


def test_login_ignores_foreign_next_url(stack: Stack) -> None:
    browser = stack.client()
    token = csrf_of(browser.get("/login?next=//evil.example/admin").text)
    response = browser.post(
        "/login",
        data={"username": "cskh", "password": PASSWORDS["cskh"], "csrf_token": token, "next": "//evil.example/x"},
        follow_redirects=False,
    )
    assert response.headers["location"] == "/cskh"


def test_login_follows_next_inside_role_area(stack: Stack) -> None:
    browser = stack.client()
    token = csrf_of(browser.get("/login").text)
    response = browser.post(
        "/login",
        data={
            "username": "chuyenvien",
            "password": PASSWORDS["chuyenvien"],
            "csrf_token": token,
            "next": "/analyst/batch",
        },
        follow_redirects=False,
    )
    assert response.headers["location"] == "/analyst/batch"


def test_logout_ends_session(stack: Stack) -> None:
    browser = stack.login("cskh")
    token = page_token(browser, "/cskh")
    response = browser.post("/logout", data={"csrf_token": token}, follow_redirects=False)
    assert response.headers["location"] == "/login"
    assert browser.get("/cskh", follow_redirects=False).status_code == 303


@pytest.mark.parametrize("path", ["/cskh", "/analyst", "/analyst/batch", "/admin", "/admin/logs"])
def test_anonymous_is_redirected_to_login(stack: Stack, path: str) -> None:
    browser = stack.client()
    response = browser.get(path, follow_redirects=False)
    assert response.status_code == 303
    assert response.headers["location"].startswith(f"/login?next={path}")
    partial = browser.get(path, headers=HTMX, follow_redirects=False)
    assert partial.status_code == 401
    assert partial.headers["hx-redirect"] == "/login"


# --- role isolation ------------------------------------------------------------------


_ROUTERS = {"/admin": admin_routes.router, "/analyst": analyst_routes.router, "/cskh": cskh_routes.router}


def _routes(prefix: str) -> list[tuple[str, str]]:
    found = []
    for route in _ROUTERS[prefix].routes:
        assert isinstance(route, APIRoute)
        path = re.sub(r"\{[^}]+\}", "1", route.path)
        found.extend((method, path) for method in sorted(route.methods))
    return found


@pytest.mark.parametrize(
    ("username", "prefix"),
    [
        ("cskh", "/admin"),
        ("chuyenvien", "/admin"),
        ("cskh", "/analyst"),
        ("admin", "/analyst"),
        ("chuyenvien", "/cskh"),
        ("admin", "/cskh"),
    ],
)
def test_every_route_of_another_role_returns_403(stack: Stack, username: str, prefix: str) -> None:
    browser = stack.login(username)
    token = page_token(browser, {"cskh": "/cskh", "chuyenvien": "/analyst", "admin": "/admin"}[username])
    routes = _routes(prefix)
    assert len(routes) >= 4
    before = stack.count_logs()
    for method, path in routes:
        response = browser.request(
            method, path, data={"csrf_token": token, "confirmation": "XOA"} if method == "POST" else None
        )
        assert response.status_code == 403, f"{username} {method} {path} -> {response.status_code}"
        assert "Không có quyền truy cập" in response.text
    assert stack.count_logs() == before


def test_forbidden_htmx_request_gets_partial(stack: Stack) -> None:
    browser = stack.login("cskh")
    response = browser.get("/admin/status", headers=HTMX)
    assert response.status_code == 403
    assert "<html" not in response.text


# --- CSRF ----------------------------------------------------------------------------


def test_post_without_or_with_wrong_csrf_is_rejected(stack: Stack) -> None:
    browser = stack.login("cskh")
    customer = stack.app.state.portal.catalog.all()[0].customer_id
    before = stack.count_logs()
    missing = browser.post(f"/cskh/customers/{customer}/requests", data={"request_type": "LIMIT_INCREASE"})
    wrong = browser.post(
        f"/cskh/customers/{customer}/requests",
        data={"request_type": "LIMIT_INCREASE"},
        headers={"X-CSRF-Token": "forged", **HTMX},
    )
    assert missing.status_code == 403
    assert wrong.status_code == 403
    assert stack.count_logs() == before


def test_csrf_header_is_accepted_for_htmx(stack: Stack) -> None:
    browser = stack.login("cskh")
    customer = stack.app.state.portal.catalog.all()[0].customer_id
    token = page_token(browser, "/cskh")
    response = browser.post(
        f"/cskh/customers/{customer}/requests",
        data={"request_type": "CASH_ADVANCE"},
        headers={"X-CSRF-Token": token, **HTMX},
    )
    assert response.status_code == 200
    assert "decision decision--" in response.text


# --- customer service ----------------------------------------------------------------


def test_cskh_search_finds_cardholders(stack: Stack) -> None:
    browser = stack.login("cskh")
    member = stack.app.state.portal.catalog.all()[3]
    by_code = browser.get(f"/cskh/search?q={member.customer_id}", headers=HTMX)
    assert by_code.status_code == 200
    assert member.full_name in by_code.text
    assert "<html" not in by_code.text
    by_card = browser.get(f"/cskh?q={member.card_last4}")
    assert member.customer_id in by_card.text
    assert "**** " + member.card_last4 in by_card.text
    none = browser.get("/cskh/search?q=khongtontai", headers=HTMX)
    assert "Không tìm thấy" in none.text
    redirect = browser.get("/cskh/search?q=abc", follow_redirects=False)
    assert redirect.headers["location"] == "/cskh?q=abc"


def test_cskh_request_scores_through_api_and_is_logged(stack: Stack) -> None:
    browser = stack.login("cskh")
    member = stack.app.state.portal.catalog.all()[0]
    before = stack.count_logs()
    page = browser.get(f"/cskh/customers/{member.customer_id}")
    assert page.status_code == 200
    assert member.card_masked in page.text
    response = browser.post(
        f"/cskh/customers/{member.customer_id}/requests",
        data={"request_type": "LIMIT_INCREASE", "requested_amount": "250.000", "csrf_token": csrf_of(page.text)},
        headers=HTMX,
    )
    assert response.status_code == 200
    assert "Hạn mức đề xuất" in response.text
    assert "Xác suất vỡ nợ" in response.text
    assert " ms" in response.text
    assert stack.count_logs() == before + 1

    record = stack.app.state.portal.store.recent_requests("cskh", limit=1)[0]
    assert record.customer_id == member.customer_id
    assert record.requested_amount == 250000
    assert record.roundtrip_ms < 1000
    detail = browser.get(f"/cskh/requests/{record.id}")
    assert detail.status_code == 200
    assert record.api_request_id in detail.text
    assert f"/cskh/requests/{record.id}" in browser.get("/cskh").text


def test_identity_never_reaches_inference_logs(stack: Stack) -> None:
    browser = stack.login("cskh")
    member = stack.app.state.portal.catalog.all()[1]
    _submit_request(stack, browser, member.customer_id)
    row = stack.app.state.portal.store.query_logs(LogFilters(), 1, 1).rows[0]
    features = json.loads(row.features_json)
    assert set(features) == set(member.features)
    assert member.full_name not in row.features_json
    assert member.customer_id not in row.features_json


def test_decline_shows_reason_codes(stack: Stack) -> None:
    customer_id = _first_with(stack, "DECLINE")
    browser = stack.login("cskh")
    request_id = _submit_request(stack, browser, customer_id)
    page = browser.get(f"/cskh/requests/{request_id}")
    assert "Mã lý do từ chối" in page.text
    assert re.search(r'class="reason-code">R\d\d<', page.text)


def test_cskh_validation_errors(stack: Stack) -> None:
    browser = stack.login("cskh")
    member = stack.app.state.portal.catalog.all()[0]
    token = page_token(browser, "/cskh")
    bad_type = browser.post(
        f"/cskh/customers/{member.customer_id}/requests", data={"request_type": "LOAN", "csrf_token": token}
    )
    assert bad_type.status_code == 400
    bad_amount = browser.post(
        f"/cskh/customers/{member.customer_id}/requests",
        data={"request_type": "LIMIT_INCREASE", "requested_amount": "abc", "csrf_token": token},
    )
    assert bad_amount.status_code == 400
    assert browser.get("/cskh/customers/KH000000").status_code == 404
    assert browser.get("/cskh/requests/999999").status_code == 404


def test_api_outage_is_reported_not_crashed(make_stack: Callable[..., Stack], settings: Settings) -> None:
    stack = make_stack()

    def refuse(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused", request=request)

    down = ScoringClient("http://api:8000", API_KEY, client=httpx.Client(transport=httpx.MockTransport(refuse)))
    stack.app.state.portal.scoring = down
    browser = stack.login("cskh")
    member = stack.app.state.portal.catalog.all()[0]
    token = page_token(browser, "/cskh")
    response = browser.post(
        f"/cskh/customers/{member.customer_id}/requests",
        data={"request_type": "LIMIT_INCREASE", "csrf_token": token},
        headers=HTMX,
    )
    assert response.status_code == 502
    assert "API_UNREACHABLE" in response.text


# --- analyst -------------------------------------------------------------------------


def test_analyst_reviews_case_with_shap_and_records_decision(stack: Stack) -> None:
    customer_id = _first_with(stack, "REVIEW")
    request_id = _submit_request(stack, stack.login("cskh"), customer_id)
    analyst = stack.login("chuyenvien")

    queue = analyst.get("/analyst")
    assert f"/analyst/cases/{request_id}" in queue.text

    case = analyst.get(f"/analyst/cases/{request_id}")
    assert case.status_code == 200
    assert 'hx-get="/analyst/cases/' in case.text
    explain = analyst.get(f"/analyst/cases/{request_id}/explain", headers=HTMX)
    assert explain.status_code == 200
    assert "shap-row" in explain.text
    assert "<progress" in explain.text

    logs_before = stack.count_logs()
    token = csrf_of(case.text)
    limit_bal = stack.app.state.portal.catalog.get(customer_id).limit_bal
    too_high = analyst.post(
        f"/analyst/cases/{request_id}/decision",
        data={"action": "REDUCE", "new_limit": str(int(limit_bal) + 1), "csrf_token": token},
        headers=HTMX,
    )
    assert too_high.status_code == 400
    no_action = analyst.post(f"/analyst/cases/{request_id}/decision", data={"csrf_token": token})
    assert no_action.status_code == 400

    new_limit = int(limit_bal // 2)
    decided = analyst.post(
        f"/analyst/cases/{request_id}/decision",
        data={
            "action": "REDUCE",
            "new_limit": f"{new_limit:,}".replace(",", "."),
            "note": "Hạ do trễ hạn",
            "csrf_token": token,
        },
        headers=HTMX,
    )
    assert decided.status_code == 200
    assert decided.headers["hx-redirect"] == "/analyst"
    again = analyst.post(f"/analyst/cases/{request_id}/decision", data={"action": "KEEP", "csrf_token": token})
    assert again.status_code == 409

    decision = stack.app.state.portal.store.decision_for(request_id)
    assert decision.action == "REDUCE"
    assert decision.new_limit_ntd == new_limit
    assert decision.analyst == "chuyenvien"
    assert stack.count_logs() == logs_before
    assert f"/analyst/cases/{request_id}" not in analyst.get("/analyst").text.split("Đã quyết định gần đây")[0]
    assert "Hạ hạn mức" in analyst.get(f"/analyst/cases/{request_id}").text


@pytest.mark.parametrize(("action", "expected"), [("KEEP", "limit"), ("SUSPEND", 0.0)])
def test_analyst_keep_and_suspend(stack: Stack, action: str, expected: Any) -> None:
    customer_id = stack.app.state.portal.catalog.all()[0].customer_id
    request_id = _submit_request(stack, stack.login("cskh"), customer_id)
    analyst = stack.login("chuyenvien")
    token = page_token(analyst, "/analyst")
    response = analyst.post(
        f"/analyst/cases/{request_id}/decision", data={"action": action, "csrf_token": token}, follow_redirects=False
    )
    assert response.status_code == 303
    decision = stack.app.state.portal.store.decision_for(request_id)
    limit = stack.app.state.portal.catalog.get(customer_id).limit_bal
    assert decision.new_limit_ntd == (limit if expected == "limit" else expected)


def test_batch_review_and_csv_download(stack: Stack) -> None:
    analyst = stack.login("chuyenvien")
    page = analyst.get("/analyst/batch")
    assert "Kỳ sao kê ngày 05" in page.text
    members = stack.app.state.portal.catalog.by_statement_day(5)
    before = stack.count_logs()
    result = analyst.post("/analyst/batch", data={"cohort": "day-5", "csrf_token": csrf_of(page.text)}, headers=HTMX)
    assert result.status_code == 200
    assert "Tải CSV" in result.text
    assert stack.count_logs() == before + len(members)

    review = stack.app.state.portal.store.latest_batch_review()
    assert review.count == len(members)
    assert sum(review.decision_summary.values()) == len(members)
    download = analyst.get(f"/analyst/batch/{review.id}/csv")
    assert download.status_code == 200
    assert download.headers["content-type"].startswith("text/csv")
    assert f"ra-soat-han-muc-lo-{review.id}.csv" in download.headers["content-disposition"]
    assert download.content.startswith("\ufeff".encode())
    rows = list(csv.DictReader(io.StringIO(download.text.lstrip("\ufeff"))))
    assert len(rows) == len(members)
    assert {row["customer_id"] for row in rows} == {member.customer_id for member in members}
    assert all(row["risk_decision"] in {"APPROVE", "REVIEW", "DECLINE"} for row in rows)

    detail = analyst.get(f"/analyst/batch/{review.id}")
    assert members[0].full_name in detail.text
    warning = analyst.get("/analyst/early-warning")
    assert warning.status_code == 200
    assert f"lô #{review.id}" in warning.text
    assert analyst.get("/analyst/batch/999/csv").status_code == 404
    bad = analyst.post("/analyst/batch", data={"cohort": "everyone", "csrf_token": csrf_of(page.text)})
    assert bad.status_code == 400


def test_batch_without_htmx_redirects_to_detail(stack: Stack) -> None:
    analyst = stack.login("chuyenvien")
    token = page_token(analyst, "/analyst/batch")
    response = analyst.post("/analyst/batch", data={"cohort": "day-25", "csrf_token": token}, follow_redirects=False)
    assert response.status_code == 303
    assert re.fullmatch(r"/analyst/batch/\d+", response.headers["location"])


def test_early_warning_without_batch(stack: Stack) -> None:
    analyst = stack.login("chuyenvien")
    assert "Chưa có lô rà soát nào" in analyst.get("/analyst/early-warning").text


# --- admin ---------------------------------------------------------------------------


def test_admin_dashboard_status_and_links(stack: Stack) -> None:
    admin = stack.login("admin")
    page = admin.get("/admin")
    assert page.status_code == 200
    for link in ("http://grafana.local", "http://mlflow.local", "http://airflow.local", "http://alertmanager.local"):
        assert link in page.text
    status = admin.get("/admin/status", headers=HTMX)
    assert status.status_code == 200
    assert "ready" in status.text or "degraded" in status.text
    assert "DRIFT" in status.text
    assert "AGE" in status.text
    model_version = stack.api.get("/api/v1/model/info", headers={"X-API-Key": API_KEY}).json()["model_version"]
    assert model_version in status.text


def test_admin_log_table_filters_and_detail(stack: Stack) -> None:
    stack.decisions_by_customer()
    admin = stack.login("admin")
    page = admin.get("/admin")
    assert "inference_logs" in page.text
    approve = admin.get("/admin/logs?decision=APPROVE", headers=HTMX)
    assert approve.status_code == 200
    assert "badge--APPROVE" in approve.text
    assert 'badge--DECLINE">DECLINE' not in approve.text
    assert "Trang 1 /" in approve.text
    second = admin.get("/admin/logs?page=2", headers=HTMX)
    assert "Trang 2 /" in second.text
    future = admin.get("/admin/logs?start=2999-01-01T00:00", headers=HTMX)
    assert "Không có dòng log nào" in future.text
    version = stack.app.state.portal.store.model_versions()[0]
    assert admin.get(f"/admin/logs?model_version={version}", headers=HTMX).status_code == 200
    assert admin.get("/admin/logs?model_version=does-not-exist", headers=HTMX).text.count("<tr>") == 0
    assert admin.get("/admin/logs?decision=MAYBE", headers=HTMX).status_code == 400
    assert admin.get("/admin/logs?start=yesterday", headers=HTMX).status_code == 400
    redirect = admin.get("/admin/logs?decision=REVIEW", follow_redirects=False)
    assert redirect.headers["location"] == "/admin?decision=REVIEW&page=1"

    row_id = stack.app.state.portal.store.query_logs(LogFilters(), 1, 1).rows[0].id
    detail = admin.get(f"/admin/logs/{row_id}", headers=HTMX)
    assert "features_json" in detail.text
    assert "LIMIT_BAL" in detail.text
    assert admin.get("/admin/logs/999999", headers=HTMX).status_code == 404


def test_simulate_normal_adds_exactly_n_rows(stack: Stack) -> None:
    admin = stack.login("admin")
    token = page_token(admin, "/admin")
    before = stack.count_logs()
    response = admin.post(
        "/admin/simulate", data={"source": "normal", "count": "25", "csrf_token": token}, headers=HTMX
    )
    assert response.status_code == 200
    assert stack.app.state.portal.simulator.wait(timeout=60)
    assert stack.count_logs() == before + 25

    job = stack.app.state.portal.simulator.current()
    assert job["status"] == "completed"
    assert job["succeeded"] == 25
    assert job["errors"] == 0
    assert sum(job["decisions"].values()) == 25
    status = admin.get("/admin/simulate/status", headers=HTMX)
    assert "đã hoàn tất" in status.text
    assert status.headers["hx-trigger"] == "logs-changed"
    actions = [entry.action for entry in stack.app.state.portal.store.audit_entries()]
    assert "simulation_started" in actions
    assert "simulation_completed" in actions


def test_simulate_genz_sends_only_under_30(stack: Stack) -> None:
    admin = stack.login("admin")
    token = page_token(admin, "/admin")
    admin.post("/admin/simulate", data={"source": "genz", "count": "15", "csrf_token": token})
    assert stack.app.state.portal.simulator.wait(timeout=60)
    rows = stack.app.state.portal.store.query_logs(LogFilters(), 1, 15).rows
    assert len(rows) == 15
    assert all(json.loads(row.features_json)["AGE"] < 30 for row in rows)


def test_simulate_rejects_invalid_input(stack: Stack) -> None:
    admin = stack.login("admin")
    token = page_token(admin, "/admin")
    assert admin.post("/admin/simulate", data={"source": "chaos", "count": "5", "csrf_token": token}).status_code == 400
    assert (
        admin.post("/admin/simulate", data={"source": "normal", "count": "0", "csrf_token": token}).status_code == 400
    )
    assert (
        admin.post("/admin/simulate", data={"source": "normal", "count": "2001", "csrf_token": token}).status_code
        == 400
    )
    assert admin.post("/admin/simulate/stop", data={"csrf_token": token}).status_code == 409


def test_delete_logs_requires_confirmation_and_writes_audit(stack: Stack) -> None:
    stack.decisions_by_customer()
    existing = stack.count_logs()
    assert existing > 0
    admin = stack.login("admin")
    token = page_token(admin, "/admin")
    wrong = admin.post("/admin/logs/delete", data={"confirmation": "xoa", "csrf_token": token}, headers=HTMX)
    assert wrong.status_code == 400
    assert stack.count_logs() == existing

    response = admin.post("/admin/logs/delete", data={"confirmation": "XOA", "csrf_token": token}, headers=HTMX)
    assert response.status_code == 200
    assert response.headers["hx-trigger"] == "logs-changed"
    assert stack.count_logs() == 0
    assert 'hx-swap-oob="true"' in response.text

    entry = stack.app.state.portal.store.audit_entries()[0]
    assert entry.action == "delete_inference_logs"
    assert entry.actor == "admin"
    assert entry.rows_affected == existing
    assert "delete_inference_logs" in admin.get("/admin").text

    # The table itself survives: the API keeps logging after a reset.
    stack.decisions_by_customer()
    assert stack.count_logs() == len(stack.app.state.portal.catalog)


def test_delete_logs_is_blocked_when_demo_mode_is_off(make_stack: Callable[..., Stack]) -> None:
    stack = make_stack(demo_mode=False)
    stack.decisions_by_customer()
    existing = stack.count_logs()
    admin = stack.login("admin")
    page = admin.get("/admin")
    assert "PORTAL_DEMO_MODE=false" in page.text
    assert 'action="/admin/logs/delete"' not in page.text
    response = admin.post("/admin/logs/delete", data={"confirmation": "XOA", "csrf_token": csrf_of(page.text)})
    assert response.status_code == 403
    assert stack.count_logs() == existing
    assert stack.app.state.portal.store.audit_entries() == []


# --- secrets -------------------------------------------------------------------------


def test_api_key_never_appears_in_html_or_static_assets(stack: Stack) -> None:
    customer_id = stack.app.state.portal.catalog.all()[0].customer_id
    request_id = _submit_request(stack, stack.login("cskh"), customer_id)
    pages = {
        "cskh": [
            "/cskh",
            f"/cskh/customers/{customer_id}",
            f"/cskh/requests/{request_id}",
            f"/cskh/search?q={customer_id}",
        ],
        "chuyenvien": [
            "/analyst",
            f"/analyst/cases/{request_id}",
            f"/analyst/cases/{request_id}/explain",
            "/analyst/batch",
        ],
        "admin": ["/admin", "/admin/status", "/admin/logs", "/admin/simulate/status"],
    }
    bodies = [stack.client().get("/login").text]
    for username, paths in pages.items():
        browser = stack.login(username)
        for path in paths:
            response = browser.get(path, headers=HTMX if "/explain" in path or path.endswith("status") else None)
            assert response.status_code == 200, path
            bodies.append(response.text)
            bodies.append(json.dumps(dict(response.headers)))
    for asset in (
        "/static/js/portal.js",
        "/static/vendor/htmx-2.0.11.min.js",
        "/static/css/portal.css",
        "/static/css/tokens.css",
    ):
        response = stack.client().get(asset)
        assert response.status_code == 200, asset
        bodies.append(response.text)
    for body in bodies:
        assert API_KEY not in body
        assert "X-API-Key" not in body
