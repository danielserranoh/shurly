from server.core import session_scope

from fastapi import APIRouter
from server.utils.statistics import day, week, world, main
from datetime import date

statistics_router = APIRouter()


@statistics_router.get("/day/{surl}")
def day_statistics(surl: str):
    with session_scope() as session:
        response = day(surl, session)
    return response


@statistics_router.get("/week/{surl}")
def week_statistics(surl: str):
    with session_scope() as session:
        response = week(surl, session)
    return response


@statistics_router.get("/world/{surl}")
def world_statistics(surl: str):
    with session_scope() as session:
        response = world(surl, session)
    return response


@statistics_router.get("/main")
def main_statistics():
    with session_scope() as session:
        response = main(session)
    return response


@statistics_router.get("/next/{surl}")
def next_statistics(surl: str):
    with session_scope() as session:
        response = int(day(surl, session).get(date.today(), 0) * 1.2)
    return response
