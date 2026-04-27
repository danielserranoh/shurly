import uuid

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


def create_app() -> FastAPI:
    """Create and configure the FastAPI application."""
    app = FastAPI(
        title=settings.api_title,
        version=settings.api_version,
        description=settings.api_description,
    )

    # Add CORS middleware
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

    # Include API routes under /api/v1 (versioned API)
    app.include_router(api_router, prefix="/api/v1")

    # Include redirect endpoint at root level (/{short_code})
    app.include_router(redirect_router)

    @app.on_event("startup")
    async def startup_event():
        """
        Create the schema if missing, then seed the default domain and the
        predefined tag set.

        Schema creation here uses `Base.metadata.create_all()` which is idempotent:
        it only creates tables that don't exist, never drops or alters. That makes
        it safe to run on every container start. When we have non-trivial migrations
        we'll switch to Alembic; until then this avoids needing a separate
        bootstrap step against an RDS that lives inside the VPC.
        """
        import os

        # Skip during testing — conftest.py manages the in-memory schema.
        if os.getenv("TESTING"):
            return

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
            # Phase 3.10.1 — seed default domain so URLs always have a host.
            get_or_create_default_domain(db)
        finally:
            db.close()

    return app


app = create_app()


if __name__ == "__main__":
    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=8000,
        reload=True,
    )
