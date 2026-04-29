import os
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


class RequestIdMiddleware(BaseHTTPMiddleware):
    """
    Phase 3.9.6 — X-Request-Id middleware.

    Generate a UUID per request unless the client supplied one; echo back in the
    response header; stash on `request.state.request_id` so handlers/log lines can
    correlate (CloudWatch picks up the value once we add the access log formatter).
    """

    async def dispatch(self, request: Request, call_next):
        rid = request.headers.get("x-request-id") or uuid.uuid4().hex
        request.state.request_id = rid
        response = await call_next(request)
        response.headers["x-request-id"] = rid
        return response


def _try_build_mcp_app(fastapi_app):
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
    server = build_mcp_for_app(fastapi_app)
    # `path="/"` because we mount the result under `/mcp` — fastmcp would
    # otherwise produce double-prefixed URLs.
    return server.http_app(path="/", transport="http")


def _seed_database():
    """
    Create the schema if missing, then seed the default domain and predefined tag set.

    `Base.metadata.create_all()` is idempotent — only creates tables that don't
    exist. Safe on every container start. Switch to Alembic when migrations
    arrive; until then this avoids a separate bootstrap step against an RDS
    that lives inside the VPC.
    """
    from server.core import Base, engine
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
    from server.utils.domain import get_or_create_default_domain
    from server.utils.tags import initialize_predefined_tags

    Base.metadata.create_all(bind=engine)

    db = next(get_db())
    try:
        initialize_predefined_tags(db)
        get_or_create_default_domain(db)
    finally:
        db.close()


def create_app() -> FastAPI:
    """Create and configure the FastAPI application."""

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        # `TESTING=1` skips DB seeding (conftest manages the in-memory schema).
        if not os.getenv("TESTING"):
            _seed_database()

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

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=settings.cors_allow_credentials,
        allow_methods=settings.cors_allow_methods,
        allow_headers=settings.cors_allow_headers,
    )

    # Phase 3.9.6 — request-id correlation. Add after CORS so the header is on every
    # response, including the OPTIONS preflight handled by CORSMiddleware.
    app.add_middleware(RequestIdMiddleware)

    # Versioned API.
    app.include_router(api_router, prefix="/api/v1")

    # Public unversioned routes (redirect, robots, pixel, landing).
    app.include_router(redirect_router)

    # Phase 5.5 — Streamable HTTP MCP transport at /mcp. Built AFTER the
    # routers are registered so fastmcp's OpenAPI introspection sees the
    # full route graph. Mounted last so the FastAPI routes take precedence
    # on every other path. Build is conditional on the [mcp] extra being
    # installed (returns None in dev environments without fastmcp).
    mcp_app = _try_build_mcp_app(app)
    if mcp_app is not None:
        app.mount("/mcp", mcp_app)
        # Late-bind the lifespan so the MCP session manager starts/stops
        # with the host. We can't read `mcp_app` from the lifespan closure
        # at app-construction time (it's built right above), so we attach a
        # router-level startup that delegates to the MCP lifespan.
        app.state.mcp_app = mcp_app

    return app


app = create_app()


if __name__ == "__main__":
    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=8000,
        reload=True,
    )
