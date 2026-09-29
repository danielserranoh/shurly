import os
import time
import uuid
from contextlib import asynccontextmanager

import uvicorn
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.base import BaseHTTPMiddleware

from server.app import api_router
from server.app.urls import redirect_router
from server.core import get_db
from server.core.config import settings
from server.utils.event_log import log_event
from server.utils.network import client_ip_and_source, request_host
from server.utils.nul import NulMiddleware, nul_value_error
from server.utils.rate_limit import RateLimitMiddleware


class RequestIdMiddleware(BaseHTTPMiddleware):
    """
    Phase 3.9.6 — X-Request-Id middleware.

    Generate a UUID per request unless the client supplied one; echo back in the
    response header; stash on `request.state.request_id` so handlers/log lines can
    correlate.

    Phase 5.6.0 — also writes each request's `http.request` line of the event log,
    which replaces uvicorn's access log (turned off in the image). The path goes
    without its query string, which can carry tokens. `duration_ms` runs until the
    response headers are ready, so a streamed body isn't counted. Phase 6.3 — with
    the host, and how the client IP was found (`client_ip_source`): never the IP.
    """

    async def dispatch(self, request: Request, call_next):
        rid = request.headers.get("x-request-id") or uuid.uuid4().hex
        request.state.request_id = rid
        _, ip_source = client_ip_and_source(request)
        started = time.perf_counter()
        status = 500  # what the client gets if the app raises
        try:
            response = await call_next(request)
            status = response.status_code
        finally:
            log_event(
                "http.request",
                request_id=rid,
                method=request.method,
                host=request_host(request),
                path=request.url.path,
                client_ip_source=ip_source,
                status=status,
                duration_ms=round((time.perf_counter() - started) * 1000, 1),
            )
        response.headers["x-request-id"] = rid
        return response


def _try_build_mcp_app(fastapi_app, auth=None):
    """
    Phase 5.5 — Build the MCP Streamable HTTP app for mounting under `/mcp`.

    Returns `None` when:
      * the `[mcp]` extra isn't installed (dev environments running just the API),
      * `MCP_DISABLE_MOUNT=1` is set (escape hatch for incident response).

    Production images install `--extra mcp` so the mount is active by default.
    Takes the in-construction FastAPI app explicitly to avoid a circular
    import (the MCP layer's auto-generated tools introspect this app via
    `from_fastapi(app=...)`).
    """
    if os.getenv("MCP_DISABLE_MOUNT") == "1":
        return None
    try:
        from mcp_server.server import build_mcp_for_app
    except ImportError:
        return None
    server = build_mcp_for_app(fastapi_app, auth=auth)
    # Phase 5.8 — OAuth discovery lives at the root: RFC 8414 and RFC 9728 put the
    # MCP's path after `/.well-known/`. Multi-segment paths, so no short code is
    # shadowed; the OAuth endpoints themselves are under /mcp/. None without OAuth.
    # `mcp_path="/"`, the http_app's own path below: with "/mcp" fastmcp builds /mcp/mcp.
    if server.auth is not None:
        fastapi_app.router.routes.extend(server.auth.get_well_known_routes(mcp_path="/"))
    # `path="/"` because we mount the result under `/mcp` — fastmcp would
    # otherwise produce double-prefixed URLs.
    #
    # Phase 5.6 — `stateless_http=True` is not fastmcp's default, so it has to
    # be explicit. MCP revision 2026-07-28 removed protocol-level sessions
    # (no `initialize` handshake, no `Mcp-Session-Id`); leaving fastmcp on its
    # stateful default keeps a per-task session table this deployment cannot
    # honour. The service scales to `maxTaskCount: 2` (scripts/deploy_ecs.sh)
    # with no session affinity, so a session minted on one task is unknown to
    # the other and those calls fail with `-32600 Missing session ID`; blue/green
    # deploys drop every live session for the same reason. Nothing here needs
    # cross-call state: curated tools open their own `SessionLocal` per call and
    # the bearer is resolved per request via `get_access_token()`.
    return server.http_app(path="/", transport="http", stateless_http=True)


def _seed_database():
    """
    Migrate the schema to the latest revision, then seed the default domain and
    predefined tag set, and bind legacy campaign URLs (NULL `domain_id`) to the
    default domain.

    Phase 3.14.1 — Alembic replaced `create_all()`, which never adds a column to
    an existing table. Runs on every container start, under a lock so tasks that
    boot together don't race (`server/core/migrations.py`); no separate
    bootstrap step against an RDS that lives inside the VPC.
    """
    from server.core import engine
    from server.core.migrations import run_migrations
    from server.core.models import (  # noqa: F401 — register models with Base
        URL,
        Campaign,
        Domain,
        OrphanVisit,
        RedirectRule,
        Tag,
        User,
        Visitor,
    )
    from server.utils.domain import backfill_campaign_url_domains, get_or_create_default_domain
    from server.utils.organization import ensure_memberships
    from server.utils.tags import initialize_predefined_tags

    run_migrations(engine)

    db = next(get_db())
    try:
        initialize_predefined_tags(db)
        get_or_create_default_domain(db)
        backfill_campaign_url_domains(db)
        # Phase 3.14.2 — the organization, and a membership for every active account.
        ensure_memberships(db)
        db.commit()
    finally:
        db.close()


def create_app(mcp_auth=None) -> FastAPI:
    """Create and configure the FastAPI application.

    `mcp_auth` replaces the MCP's auth provider from settings (tests: a fake Google).
    """

    # Phase 3.13.2 — accounts come from Google; POST /auth/register is for local
    # development and tests only.
    if settings.allow_password_signup:
        log_event(
            "auth.password_signup_enabled",
            warning="ALLOW_PASSWORD_SIGNUP is on: anyone can make an account with a "
            "password. Never in production.",
        )

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        # `TESTING=1` skips DB seeding (conftest manages the in-memory schema).
        if not os.getenv("TESTING"):
            _seed_database()
            # Phase 8.4 — open the geolocation database now: a missing one is logged at startup.
            from server.utils.geo import open_database

            open_database()

        # `app.state.mcp_app` is set during construction below (after the
        # routers are registered, so the MCP introspection sees them all).
        # The lifespan executes only after construction returns, so reading
        # state here is safe even though the value is set later in the call.
        mounted_mcp = getattr(app.state, "mcp_app", None)
        if mounted_mcp is not None:
            async with mounted_mcp.lifespan(app):
                yield
        else:
            yield

    app = FastAPI(
        title=settings.api_title,
        version=settings.api_version,
        description=settings.api_description,
        lifespan=lifespan,
    )

    # Phase 6.3 — rate limits (server/utils/rate_limit.py). Added first, so it runs
    # inside CORS (which answers preflights itself, and adds its headers to a 429)
    # and inside RequestIdMiddleware (which logs the 429 like any response).
    app.add_middleware(RateLimitMiddleware)

    # Phase 6.3 — a NUL character in a request is a 400 or a 422 before any route sees it:
    # PostgreSQL can't hold one, and each answered 500 (server/utils/nul.py). Outside the
    # rate limits, inside CORS and the request id, like them.
    app.add_middleware(NulMiddleware)
    app.add_exception_handler(ValueError, nul_value_error)

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=settings.cors_allow_credentials,
        allow_methods=settings.cors_allow_methods,
        allow_headers=settings.cors_allow_headers,
        expose_headers=settings.cors_expose_headers,
    )

    # Phase 3.9.6 — request-id correlation. Add after CORS so the header is on every
    # response, including the OPTIONS preflight handled by CORSMiddleware.
    app.add_middleware(RequestIdMiddleware)

    # Versioned API.
    app.include_router(api_router, prefix="/api/v1")

    # Phase 5.5 — Streamable HTTP MCP transport at /mcp. Built AFTER the API
    # router so fastmcp's OpenAPI introspection sees every tool-bearing route.
    # Build is conditional on the [mcp] extra being installed (returns None in
    # dev environments without fastmcp).
    #
    # ORDER IS LOAD-BEARING: this mount must come BEFORE `redirect_router`.
    # That router owns `/{short_code}`, which matches the bare path `/mcp` and
    # is GET-only — registered first, it answered a POST to /mcp with 405 and a
    # GET with a lookup for the short code "mcp", and the mount never saw the
    # request. Mounting first costs exactly one short code ("mcp") out of ~57
    # billion six-character combinations, and closes the trap where anyone
    # could claim the very URL people mistype when configuring a client.
    # Only the literal path is claimed: `/mcpx`, `/notmcp` etc. still resolve.
    mcp_app = _try_build_mcp_app(app, auth=mcp_auth)
    if mcp_app is not None:
        # A Starlette `Mount("/mcp")` compiles to `^/mcp(?P<path>/.*)$` — it
        # structurally does not match its own bare path, whatever the ordering.
        # So `/mcp` gets an explicit 308 of its own, registered first.
        #
        # 308, not 301/302: the redirect has to survive a POST carrying a
        # JSON-RPC body. 301/302 let a client drop the body (RFC 7231 §6.4.2 —
        # curl delivers an empty body without `--post301`), which would reach
        # the MCP app as an unparseable empty request instead of failing
        # loudly. 307/308 preserve method and body; 308 is the permanent one.
        # Note this is also why an ALB redirect rule could not have done it:
        # ALB emits only HTTP_301 and HTTP_302.
        @app.api_route("/mcp", methods=["POST", "DELETE", "GET"], include_in_schema=False)
        async def _mcp_slash_redirect(request: Request):
            from starlette.responses import RedirectResponse

            target = "/mcp/"
            if request.url.query:
                target = f"{target}?{request.url.query}"
            return RedirectResponse(target, status_code=308)

        # Phase 5.8 — the sign-in's HTML pages get their headers (CSP, no-store, …) on the way
        # out; the MCP's JSON goes through untouched (mcp_server/pages.py).
        from mcp_server.pages import PageHeaders

        app.mount("/mcp", PageHeaders(mcp_app))
        # Late-bind the lifespan so the MCP session manager starts/stops
        # with the host. We can't read `mcp_app` from the lifespan closure
        # at app-construction time (it's built right above), so we attach a
        # router-level startup that delegates to the MCP lifespan.
        app.state.mcp_app = mcp_app

    # Public unversioned routes (redirect, robots, pixel, landing). Registered
    # last so `/{short_code}` — the broadest pattern in the app — cannot shadow
    # anything above it.
    app.include_router(redirect_router)

    return app


app = create_app()


if __name__ == "__main__":
    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=8000,
        reload=True,
    )
