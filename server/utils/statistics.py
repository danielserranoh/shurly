from sqlalchemy.orm import Session
from sqlalchemy import func
from server.core.models.visitor import Visitor
from server.core.models.url import URL
from datetime import datetime, timedelta
from collections import defaultdict


def day(surl: str, session: Session):
    today = datetime.now().date()
    one_week_ago = today - timedelta(days=7)

    visitors_by_date = {one_week_ago + timedelta(days=x): 0 for x in range(8)}

    visits = (
        session.query(func.date(Visitor.created_at), func.count(Visitor.id))
        .join(URL)
        .filter(URL.short_url == surl, Visitor.created_at >= one_week_ago)
        .group_by(func.date(Visitor.created_at))
        .all()
    )

    visitors_by_date.update(visits)

    return visitors_by_date


def week(surl: str, session: Session):
    today = datetime.now().date()
    seven_weeks_ago = today - timedelta(weeks=8) + timedelta(days=1)

    visitors_by_week = {}

    for i in range(8):
        week_start = seven_weeks_ago + timedelta(weeks=i)
        week_end = week_start + timedelta(weeks=1) - timedelta(days=1)
        visitors_by_week[week_start] = 0

        visit_count = (
            session.query(func.count(Visitor.id))
            .join(URL)
            .filter(
                URL.short_url == surl,
                Visitor.created_at >= week_start,
                Visitor.created_at <= week_end
            )
            .scalar()
        )

        visitors_by_week[week_start] = visit_count

    return visitors_by_week


def world(surl: str, session: Session):
    uuid = session.query(URL.id).filter(URL.short_url == surl).first()[0]

    current_time = datetime.now()
    one_week_ago = current_time - timedelta(days=7)

    stats = defaultdict(int)

    visits = session.query(Visitor.country).filter(Visitor.url_id == uuid, Visitor.created_at >= one_week_ago).all()

    for visit in visits:
        country = visit[0].split(';')[2]
        stats[country] += 1

    return dict(stats)


def main(session: Session):
    today = datetime.now().date()
    one_week_ago = today - timedelta(days=7)

    visitors_by_date = {one_week_ago + timedelta(days=x): 0 for x in range(8)}

    visits = (
        session.query(func.date(Visitor.created_at), func.count(Visitor.id))
        .join(URL)
        .filter(Visitor.created_at >= one_week_ago)
        .group_by(func.date(Visitor.created_at))
        .all()
    )

    visitors_by_date.update(visits)

    return visitors_by_date