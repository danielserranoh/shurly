import uvicorn
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from server.app import api_router
from server.app.urls import redirect_router
from server.core import get_db
from server.core.config import settings


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

    # Include API routes with /api prefix
    app.include_router(api_router, prefix="/api")

    # Include redirect endpoint at root level (/{short_code})
    app.include_router(redirect_router)

    @app.on_event("startup")
    async def startup_event():
        """Initialize predefined tags on app startup."""
        from server.utils.tags import initialize_predefined_tags

        db = next(get_db())
        try:
            initialize_predefined_tags(db)
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
