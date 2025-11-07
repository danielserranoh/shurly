from datetime import date

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from server.core import get_db
from server.utils.statistics import day, main, week, world

statistics_router = APIRouter()


@statistics_router.get("/day/{surl}")
def day_statistics(surl: str, db: Session = Depends(get_db)):
    return day(surl, db)


@statistics_router.get("/week/{surl}")
def week_statistics(surl: str, db: Session = Depends(get_db)):
    return week(surl, db)


@statistics_router.get("/world/{surl}")
def world_statistics(surl: str, db: Session = Depends(get_db)):
    return world(surl, db)


@statistics_router.get("/main")
def main_statistics(db: Session = Depends(get_db)):
    return main(db)


@statistics_router.get("/next/{surl}")
def next_statistics(surl: str, db: Session = Depends(get_db)):
    return int(day(surl, db).get(date.today(), 0) * 1.2)
