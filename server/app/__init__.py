from fastapi import APIRouter

from server.app.auth import auth_router
from server.app.statistics import statistics_router

api_router = APIRouter()

api_router.include_router(auth_router, prefix="/auth", tags=["authentication"])
api_router.include_router(statistics_router, prefix="/stats", tags=["statistics"])
