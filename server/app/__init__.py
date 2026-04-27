from fastapi import APIRouter

from server.app.analytics import analytics_router
from server.app.auth import auth_router
from server.app.campaigns import campaigns_router
from server.app.health import health_router
from server.app.statistics import statistics_router
from server.app.tags import tags_router
from server.app.urls import urls_router

api_router = APIRouter()

# Health check first so it's near the top of the OpenAPI docs.
api_router.include_router(health_router, tags=["health"])
api_router.include_router(auth_router, prefix="/auth", tags=["authentication"])
api_router.include_router(urls_router, prefix="/urls", tags=["urls"])
api_router.include_router(campaigns_router, prefix="/campaigns", tags=["campaigns"])
api_router.include_router(analytics_router, prefix="/analytics", tags=["analytics"])
api_router.include_router(statistics_router, prefix="/stats", tags=["statistics"])  # Legacy
api_router.include_router(tags_router, prefix="", tags=["tags"])
