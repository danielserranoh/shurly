from fastapi import APIRouter
from server.app.code import code_router
from server.app.statistics import statistics_router

api_router = APIRouter()

api_router.include_router(code_router, tags=["code"])
api_router.include_router(statistics_router, prefix="/stats", tags=["statistics"])