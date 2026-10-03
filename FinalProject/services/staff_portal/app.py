"""Staff portal application factory (FastAPI + Jinja2 + HTMX, rendered server-side).

    uvicorn staff_portal.app:app --host 0.0.0.0 --port 8030

Runs as a single process: the simulation job and the login throttle are in-memory.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from typing import Any

import httpx
from fastapi import FastAPI, Request, Response
from fastapi.responses import JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.middleware.sessions import SessionMiddleware

from credit_risk.config import get_logger, setup_logging
from staff_portal import __version__
from staff_portal.auth import LoginRequiredError, LoginThrottle
from staff_portal.catalog import Catalog, build_catalog
from staff_portal.config import PortalSettings, load_portal_settings
from staff_portal.context import PortalContext
from staff_portal.routes import admin, analyst, auth, cskh
from staff_portal.scoring_client import ScoringApiError, ScoringClient
from staff_portal.simulator import SimulationJob, SimulationManager
from staff_portal.store import PortalStore, StoreUnavailableError
from staff_portal.views import STATIC_DIR, build_templates, is_htmx, render

logger = get_logger("staff_portal")

SESSION_COOKIE = "portal_session"

_SECURITY_HEADERS = {
    "Content-Security-Policy": (
        "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; "
        "connect-src 'self'; form-action 'self'; frame-ancestors 'none'; base-uri 'self'; object-src 'none'"
    ),
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "same-origin",
    "Permissions-Policy": "camera=(), microphone=(), geolocation=()",
}


def _audit_simulation(store: PortalStore) -> Callable[[SimulationJob], None]:
    def on_finish(job: SimulationJob) -> None:
        store.audit(
            job.stopped_by or job.started_by,
            f"simulation_{job.status}",
            detail=f"{job.source_label}: {job.succeeded}/{job.requested} thành công, {job.errors} lỗi",
            rows_affected=job.succeeded,
        )

    return on_finish


def create_app(
    settings: PortalSettings | None = None,
    *,
    scoring_client: ScoringClient | None = None,
    store: PortalStore | None = None,
    catalog: Catalog | None = None,
    http_client: httpx.Client | None = None,
    simulation_seed: int | None = None,
) -> FastAPI:
    """Build the portal; collaborators can be injected (tests point them at the real scoring app)."""
    cfg = settings if settings is not None else load_portal_settings()
    portal_store = store if store is not None else PortalStore(cfg.database_url)
    scoring = (
        scoring_client
        if scoring_client is not None
        else ScoringClient(cfg.api_url, cfg.api_key, timeout_seconds=cfg.api_timeout_seconds)
    )
    cardholders = (
        catalog
        if catalog is not None
        else build_catalog(
            cfg.normal_stream,
            cfg.drifted_stream,
            size=cfg.catalog_size,
            drifted_share=cfg.catalog_drifted_share,
            seed=cfg.catalog_seed,
        )
    )
    simulator = SimulationManager(
        scoring,
        {"normal": cfg.normal_stream, "genz": cfg.drifted_stream},
        rate_per_second=cfg.simulate_rate_per_second,
        max_count=cfg.simulate_max_count,
        on_finish=_audit_simulation(portal_store),
        seed=simulation_seed,
    )
    http = http_client if http_client is not None else httpx.Client(timeout=3.0)
    portal = PortalContext(
        settings=cfg,
        store=portal_store,
        scoring=scoring,
        catalog=cardholders,
        simulator=simulator,
        throttle=LoginThrottle(cfg.login_max_failures, cfg.login_lockout_seconds),
        http=http,
    )

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        setup_logging()
        if not portal_store.ensure_schema():
            logger.warning("Portal tables not created yet; retrying on first database access")
        logger.info(
            "Staff portal started",
            extra={"event": "portal_started", "demo_mode": cfg.demo_mode, "catalog_size": len(cardholders)},
        )
        yield
        simulator.shutdown()
        if scoring_client is None:
            scoring.close()
        if http_client is None:
            http.close()

    app = FastAPI(
        title="Credit Risk Staff Portal",
        version=__version__,
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
        lifespan=lifespan,
    )
    app.state.settings = cfg
    app.state.portal = portal
    app.state.templates = build_templates(cfg)

    @app.middleware("http")
    async def security_headers(request: Request, call_next: Callable[[Request], Awaitable[Response]]) -> Response:
        response = await call_next(request)
        for name, value in _SECURITY_HEADERS.items():
            response.headers.setdefault(name, value)
        if request.url.path.startswith("/static/"):
            response.headers.setdefault("Cache-Control", "public, max-age=3600")
        else:
            response.headers.setdefault("Cache-Control", "no-store")
        return response

    app.add_middleware(
        SessionMiddleware,
        secret_key=cfg.session_secret,
        session_cookie=SESSION_COOKIE,
        max_age=cfg.session_max_age_seconds,
        same_site="lax",
        https_only=cfg.cookie_secure,
    )
    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

    @app.exception_handler(LoginRequiredError)
    async def login_required(request: Request, _: LoginRequiredError) -> Response:
        if is_htmx(request):
            return Response(status_code=401, headers={"HX-Redirect": "/login"})
        target = request.url.path + (f"?{request.url.query}" if request.url.query else "")
        return RedirectResponse(f"/login?next={target}", status_code=303)

    @app.exception_handler(StarletteHTTPException)
    async def http_error(request: Request, exc: StarletteHTTPException) -> Response:
        message = exc.detail if isinstance(exc.detail, str) else "Đã có lỗi xảy ra."
        if exc.status_code == 404 and message == "Not Found":
            message = "Không tìm thấy trang hoặc bản ghi được yêu cầu."
        template = "partials/error.html" if is_htmx(request) else "error.html"
        return render(request, template, {"status_code": exc.status_code, "message": message}, exc.status_code)

    @app.exception_handler(ScoringApiError)
    async def scoring_error(request: Request, exc: ScoringApiError) -> Response:
        message = f"API chấm điểm trả lỗi {exc.status_code} ({exc.code}). {exc.message}"
        template = "partials/error.html" if is_htmx(request) else "error.html"
        return render(request, template, {"status_code": 502, "message": message}, 502)

    @app.exception_handler(StoreUnavailableError)
    async def store_error(request: Request, exc: StoreUnavailableError) -> Response:
        template = "partials/error.html" if is_htmx(request) else "error.html"
        return render(request, template, {"status_code": 503, "message": str(exc)}, 503)

    @app.get("/health", include_in_schema=False)
    def health() -> JSONResponse:
        body: dict[str, Any] = {
            "status": "ok",
            "service": "staff-portal",
            "version": __version__,
            "demo_mode": cfg.demo_mode,
            "database": "ok" if portal_store.ping() else "down",
            "catalog_size": len(cardholders),
            "accounts": len(cfg.users),
        }
        return JSONResponse(body)

    app.include_router(auth.router)
    app.include_router(cskh.router)
    app.include_router(analyst.router)
    app.include_router(admin.router)
    return app


def __getattr__(name: str) -> Any:
    # ``uvicorn staff_portal.app:app`` builds the app lazily so importing this module stays side-effect free.
    if name == "app":
        application = create_app()
        globals()["app"] = application
        return application
    raise AttributeError(name)
