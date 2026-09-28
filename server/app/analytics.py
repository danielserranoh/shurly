"""Analytics endpoints for URLs and campaigns."""

from bisect import bisect_right
from collections import Counter
from datetime import date, datetime, timedelta
from typing import Annotated, Literal
from uuid import UUID as UUIDType

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BeforeValidator
from sqlalchemy import func
from sqlalchemy.orm import Query as SAQuery
from sqlalchemy.orm import Session

from server.core import get_db
from server.core.auth import get_current_user
from server.core.config import settings
from server.core.models import URL, Campaign, Domain, OrphanVisit, User, Visitor
from server.schemas.analytics import (
    BreakdownItem,
    BreakdownResponse,
    CampaignSummary,
    CampaignUsersResponse,
    CampaignUserStat,
    DailyStats,
    DailyStatsResponse,
    GeoStats,
    GeoStatsResponse,
    HourCounts,
    LinkTotalsResponse,
    OverviewStats,
    TimeseriesBucket,
    TimeseriesResponse,
    WeekdayCounts,
    WeeklyStats,
    WeeklyStatsResponse,
)
from server.schemas.responses import get_responses
from server.utils.access import LinkDomain, find_url, viewer
from server.utils.csv_export import stream_csv
from server.utils.domain import normalize_hostname
from server.utils.local_days import (
    MAX_PERIOD_DAYS,
    LocalDays,
    Period,
    PeriodError,
    count_per_period,
    last_days,
)
from server.utils.profile import clean_timezone
from server.utils.url import build_short_url, link_hostname
from server.utils.visit_facets import country_label, families, kind_of, referrer_host


def _visible_url_or_404(db: Session, user: User, short_code: str, domain: str | None) -> URL:
    """Phase 8.3 — the link a code names on `domain`, or the default rule (`find_url`)."""
    url = find_url(db, viewer(db, user), short_code, domain)
    if not url:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="URL not found")
    return url


def _exclude_bots(query: SAQuery, include_bots: bool) -> SAQuery:
    """
    Phase 3.9.3 — analytics endpoints default to excluding bots.
    Phase 3.10.3 — also exclude email tracking pixel hits from click analytics
    (pixels are opens, not clicks; they share the visits table for timeline
    alignment but are conceptually a different metric).
    """
    q = query.filter(Visitor.is_pixel.is_(False))
    return q if include_bots else q.filter(Visitor.is_bot.is_(False))


# Days are counted where the viewer is (server/utils/local_days.py): `tz`, else their
# profile's zone, else UTC. `tz` changes how visits are grouped into days, never which count.
TimeZoneParam = Annotated[
    str | None,
    BeforeValidator(clean_timezone),
    Query(
        description=(
            "IANA time zone to count days in, e.g. Europe/Madrid. Defaults to your profile's, "
            "else UTC. It changes how visits are grouped into days, not which ones count."
        ),
    ),
]

# Phase 3.16 — the kinds of visit (ROADMAP 3.16.1): every visit is exactly one.
VisitType = Literal["clicks", "opens", "bots", "all"]


def _of_type(query: SAQuery, visit_type: str) -> SAQuery:
    """
    Phase 3.16 — the visits of a kind, drawing the lines `visit_facets.kind_of` draws.
    A click is what `_exclude_bots` keeps; an open, a pixel hit that isn't a bot's; a bot's,
    any visit whose user agent was one, pixel hits included.
    """
    if visit_type == "clicks":
        return _exclude_bots(query, include_bots=False)
    if visit_type == "opens":
        return query.filter(Visitor.is_pixel.is_(True), Visitor.is_bot.is_(False))
    if visit_type == "bots":
        return query.filter(Visitor.is_bot.is_(True))
    return query


def _period(
    period: int | None = Query(
        None,
        ge=1,
        le=MAX_PERIOD_DAYS,
        description="The last N local days, today included. Default 30",
    ),
    first: date | None = Query(
        None, alias="from", description="A custom range's first local day, with `to`"
    ),
    last: date | None = Query(
        None,
        alias="to",
        description="A custom range's last local day, inclusive: after today counts to today",
    ),
    tz: TimeZoneParam = None,
    current_user: User = Depends(get_current_user),
) -> Period:
    """Phase 3.16 — the local days a per-link route counts: `period`, or `from` and `to`."""
    try:
        return Period.resolve(LocalDays.of(current_user, tz), period, first, last)
    except PeriodError as error:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(error)
        ) from None


def _period_fields(url: URL, period: Period) -> dict:
    """What every per-link response over a period starts with."""
    return {
        "short_code": url.short_code,
        "domain": link_hostname(url),
        "from": period.first,
        "to": period.last,
        "timezone": period.days.name,
    }


def _breakdown(counts: Counter, total: int) -> list[BreakdownItem]:
    """By count, then name; each with its share of `total`."""
    ordered = sorted(counts.items(), key=lambda item: (-item[1], item[0].casefold(), item[0]))
    return [
        BreakdownItem(name=name, count=count, share=round(count / total, 4) if total else 0.0)
        for name, count in ordered
    ]


analytics_router = APIRouter()


@analytics_router.get(
    "/urls/{short_code}/daily",
    response_model=DailyStatsResponse,
    responses={
        200: {"description": "Daily statistics retrieved successfully"},
        **get_responses(401, 404),
    },
)
def get_url_daily_stats(
    short_code: str,
    domain: LinkDomain = None,
    include_bots: bool = Query(False, description="Include bot/crawler visits in counts"),
    format: str = Query("json", pattern="^(json|csv)$", description="Response format"),
    tz: TimeZoneParam = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Get daily click statistics for a URL: the last 7 days, today included.

    Days are local to your profile's time zone, or to `tz`, else UTC; `timezone` says which.

    **Authentication:** Required (JWT Bearer token)

    **Path Parameters:**
    - **short_code**: The short code to get statistics for

    **Responses:**
    - **200**: Daily statistics retrieved successfully - Returns 7 days of click data
    - **401**: Authentication required or invalid token
    - **404**: URL not found, or someone else's personal link
    """
    # Verify the user can see the URL (Phase 3.14.3 — the organization's, or their own)
    url = _visible_url_or_404(db, current_user, short_code, domain)

    # The last 7 days where the viewer is, today included. Keyed on the link, never its code:
    # the same code can name links on two domains.
    days = LocalDays.of(current_user, tz)
    visits = _exclude_bots(db.query(Visitor).filter(Visitor.url_id == url.id), include_bots)
    stats = [DailyStats(date=day, clicks=clicks) for day, clicks in last_days(visits, days, 7)]
    total_clicks = sum(day.clicks for day in stats)

    if format == "csv":
        return stream_csv(
            headers=["date", "clicks"],
            rows=((s.date.isoformat(), s.clicks) for s in stats),
            filename=f"{short_code}-daily.csv",
        )

    return DailyStatsResponse(
        short_code=short_code,
        stats=stats,
        total_clicks=total_clicks,
        timezone=days.name,
    )


@analytics_router.get(
    "/urls/{short_code}/weekly",
    response_model=WeeklyStatsResponse,
    responses={
        200: {"description": "Weekly statistics retrieved successfully"},
        **get_responses(401, 404),
    },
)
def get_url_weekly_stats(
    short_code: str,
    domain: LinkDomain = None,
    include_bots: bool = Query(False, description="Include bot/crawler visits in counts"),
    format: str = Query("json", pattern="^(json|csv)$", description="Response format"),
    tz: TimeZoneParam = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Get weekly click statistics for a URL: 8 seven-day weeks, the last ending today.

    Days are local to your profile's time zone, or to `tz`, else UTC; `timezone` says which.

    **Authentication:** Required (JWT Bearer token)

    **Path Parameters:**
    - **short_code**: The short code to get statistics for

    **Responses:**
    - **200**: Weekly statistics retrieved successfully - Returns 8 weeks of click data
    - **401**: Authentication required or invalid token
    - **404**: URL not found, or someone else's personal link
    """
    # Verify the user can see the URL (Phase 3.14.3 — the organization's, or their own)
    url = _visible_url_or_404(db, current_user, short_code, domain)

    # 8 seven-day weeks where the viewer is, the last ending today (it used to end yesterday).
    days = LocalDays.of(current_user, tz)
    first = days.today() - timedelta(days=8 * 7 - 1)
    visits = _exclude_bots(db.query(Visitor).filter(Visitor.url_id == url.id), include_bots)
    counts = count_per_period(visits, days.bounds(first, 8 * 7)[::7])
    stats = [
        WeeklyStats(
            week_start=first + timedelta(weeks=week),
            week_end=first + timedelta(weeks=week, days=6),
            clicks=clicks,
        )
        for week, clicks in enumerate(counts)
    ]
    total_clicks = sum(counts)

    if format == "csv":
        return stream_csv(
            headers=["week_start", "week_end", "clicks"],
            rows=((s.week_start.isoformat(), s.week_end.isoformat(), s.clicks) for s in stats),
            filename=f"{short_code}-weekly.csv",
        )

    return WeeklyStatsResponse(
        short_code=short_code,
        stats=stats,
        total_clicks=total_clicks,
        timezone=days.name,
    )


@analytics_router.get(
    "/urls/{short_code}/geo",
    response_model=GeoStatsResponse,
    responses={
        200: {"description": "Geographic statistics retrieved successfully"},
        **get_responses(401, 404),
    },
)
def get_url_geo_stats(
    short_code: str,
    domain: LinkDomain = None,
    days: int = 30,
    include_bots: bool = Query(False, description="Include bot/crawler visits in counts"),
    format: str = Query("json", pattern="^(json|csv)$", description="Response format"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Get geographic distribution of clicks for a URL.

    Returns click counts grouped by country for the specified time period.

    **Authentication:** Required (JWT Bearer token)

    **Path Parameters:**
    - **short_code**: The short code to get statistics for

    **Query Parameters:**
    - **days**: Number of days to look back (default: 30)

    **Responses:**
    - **200**: Geographic statistics retrieved successfully - Returns clicks by country
    - **401**: Authentication required or invalid token
    - **404**: URL not found, or someone else's personal link
    """
    # Verify the user can see the URL (Phase 3.14.3 — the organization's, or their own)
    url = _visible_url_or_404(db, current_user, short_code, domain)

    cutoff_date = datetime.utcnow() - timedelta(days=days)

    # Query visits grouped by country
    geo_q = db.query(
        Visitor.country,
        func.count(Visitor.id).label("click_count"),
    ).filter(
        Visitor.url_id == url.id,
        Visitor.visited_at >= cutoff_date,
        Visitor.country.isnot(None),
    )
    geo_stats = (
        _exclude_bots(geo_q, include_bots)
        .group_by(Visitor.country)
        .order_by(func.count(Visitor.id).desc())
        .all()
    )

    stats = [
        GeoStats(country=geo.country or "Unknown", clicks=geo.click_count) for geo in geo_stats
    ]

    total_clicks = sum(stat.clicks for stat in stats)

    if format == "csv":
        return stream_csv(
            headers=["country", "clicks"],
            rows=((s.country, s.clicks) for s in stats),
            filename=f"{short_code}-geo.csv",
        )

    return GeoStatsResponse(
        short_code=short_code,
        stats=stats,
        total_clicks=total_clicks,
        period_days=days,
    )


@analytics_router.get(
    "/urls/{short_code}/totals",
    response_model=LinkTotalsResponse,
    responses={
        200: {"description": "The link's all-time numbers"},
        **get_responses(401, 404, 422),
    },
)
def get_url_totals(
    short_code: str,
    domain: LinkDomain = None,
    tz: TimeZoneParam = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    A link's all-time numbers, for the header of its page (Phase 3.16).

    - **clicks**: its clicks, as `click_count`: bots and email opens aside
    - **opens**: hits on its email tracking pixel that aren't a bot's. They overcount: Apple
      Mail Privacy Protection loads the pixel, like every image, when a message arrives, read
      or not
    - **countries**: how many distinct countries its clicks came from
    - **last_click_at**: its latest click, in `tz`, else your profile's zone, else UTC; null
      without one. Unlike the link's `last_click_at`, bots and crawler previews don't count
    """
    url = _visible_url_or_404(db, current_user, short_code, domain)
    days = LocalDays.of(current_user, tz)
    visits = db.query(Visitor).filter(Visitor.url_id == url.id)
    clicks, countries, last = (
        _of_type(visits, "clicks")
        .with_entities(
            func.count(Visitor.id),
            func.count(func.distinct(Visitor.country)),
            func.max(Visitor.visited_at),
        )
        .one()
    )
    opens = _of_type(visits, "opens").with_entities(func.count(Visitor.id)).scalar()
    return LinkTotalsResponse(
        short_code=url.short_code,
        domain=link_hostname(url),
        timezone=days.name,
        clicks=clicks,
        opens=opens,
        countries=countries,
        last_click_at=days.local(last).replace(microsecond=0) if last else None,
    )


@analytics_router.get(
    "/urls/{short_code}/timeseries",
    response_model=TimeseriesResponse,
    responses={
        200: {"description": "Clicks and opens over the period"},
        **get_responses(401, 404, 422),
    },
)
def get_url_timeseries(
    short_code: str,
    domain: LinkDomain = None,
    group_by: Literal["day", "week", "month"] = Query(
        "day", description="Local days, ISO weeks (from Monday) or months"
    ),
    period: Period = Depends(_period),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    A link's clicks and email opens over a period, side by side (Phase 3.16).

    - **stats**: per local day, ISO week or month of the period, oldest first, with zeros; the
      first and last buckets are clipped to it, and `end` is inclusive
    - **hour_of_day**: per local hour, 0 to 23. On the day DST ends, the hour that happens
      twice counts both times
    - **day_of_week**: per local weekday, 1 (Monday) to 7

    The period is `period` (the last N local days, today included, default 30) or `from` and
    `to`, at most 731 days. Bots count in neither. Opens overcount: Apple Mail Privacy Protection loads the pixel, like
    every image, when a message arrives, read or not.
    """
    url = _visible_url_or_404(db, current_user, short_code, domain)
    start, end = period.bounds()
    # Clicks and opens are the visits that aren't a bot's (`_of_type`, `kind_of`).
    rows = (
        db.query(Visitor.visited_at, Visitor.is_pixel)
        .filter(
            Visitor.url_id == url.id,
            Visitor.visited_at >= start,
            Visitor.visited_at < end,
            Visitor.is_bot.is_(False),
        )
        .all()
    )

    buckets = period.buckets(group_by)
    starts = [first for first, _ in buckets]
    kinds = ("click", "open")
    per_bucket = [[0, 0] for _ in buckets]
    per_hour = [[0, 0] for _ in range(24)]
    per_weekday = [[0, 0] for _ in range(7)]
    for visited_at, is_pixel in rows:
        local = period.days.local(visited_at)
        kind = kinds.index(kind_of(is_pixel, is_bot=False))
        per_bucket[bisect_right(starts, local.date()) - 1][kind] += 1
        per_hour[local.hour][kind] += 1
        per_weekday[local.isoweekday() - 1][kind] += 1

    return TimeseriesResponse(
        **_period_fields(url, period),
        group_by=group_by,
        clicks=sum(clicks for clicks, _ in per_bucket),
        opens=sum(opens for _, opens in per_bucket),
        stats=[
            TimeseriesBucket(start=first, end=last, clicks=clicks, opens=opens)
            for (first, last), (clicks, opens) in zip(buckets, per_bucket, strict=True)
        ],
        hour_of_day=[
            HourCounts(hour=hour, clicks=clicks, opens=opens)
            for hour, (clicks, opens) in enumerate(per_hour)
        ],
        day_of_week=[
            WeekdayCounts(day=day, clicks=clicks, opens=opens)
            for day, (clicks, opens) in enumerate(per_weekday, start=1)
        ],
    )


@analytics_router.get(
    "/urls/{short_code}/breakdown",
    response_model=BreakdownResponse,
    responses={
        200: {"description": "The period's visits by OS, browser, device, referrer and country"},
        **get_responses(401, 404, 422),
    },
)
def get_url_breakdown(
    short_code: str,
    domain: LinkDomain = None,
    visit_type: VisitType = Query(
        "clicks",
        alias="type",
        description="clicks; opens (email pixel hits, not a bot's); bots; or all",
    ),
    period: Period = Depends(_period),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    A link's visits of a kind over a period, by OS, browser, device, referrer and country
    (Phase 3.16).

    Every value is listed, by count and then name, with its share of `total`. OS and browser
    are families, parsed from the user agent. Device is desktop, mobile, tablet, or other (a
    bot's). A referrer is its host, "Direct" without one; a missing value is "Unknown". A
    country is an ISO code.

    The period is `period` (the last N local days, today included, default 30) or `from` and
    `to`, at most 731 days. Opens overcount: Apple Mail Privacy Protection loads the pixel, like
    every image, when a message arrives, read or not.
    """
    url = _visible_url_or_404(db, current_user, short_code, domain)
    start, end = period.bounds()
    visits = _of_type(
        db.query(Visitor).filter(
            Visitor.url_id == url.id, Visitor.visited_at >= start, Visitor.visited_at < end
        ),
        visit_type,
    )

    def grouped(column):
        # The period's rows, grouped in SQL: each distinct value is worked out once.
        return visits.with_entities(column, func.count(Visitor.id)).group_by(column).all()

    os_names, browsers, devices, referrers, countries = (Counter() for _ in range(5))
    for user_agent, count in grouped(Visitor.user_agent):
        found = families(user_agent)
        os_names[found.os] += count
        browsers[found.browser] += count
        devices[found.device] += count
    for referer, count in grouped(Visitor.referer):
        referrers[referrer_host(referer)] += count
    for country, count in grouped(Visitor.country):
        countries[country_label(country)] += count
    total = sum(countries.values())

    return BreakdownResponse(
        **_period_fields(url, period),
        type=visit_type,
        total=total,
        os=_breakdown(os_names, total),
        browsers=_breakdown(browsers, total),
        devices=_breakdown(devices, total),
        referrers=_breakdown(referrers, total),
        countries=_breakdown(countries, total),
    )


@analytics_router.get(
    "/campaigns/{campaign_id}/summary",
    response_model=CampaignSummary,
    responses={
        200: {"description": "Campaign summary retrieved successfully"},
        **get_responses(400, 401, 404),
    },
)
def get_campaign_summary(
    campaign_id: str,
    include_bots: bool = Query(False, description="Include bot/crawler visits in counts"),
    tz: TimeZoneParam = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Get summary statistics for a campaign including timeline and top performers.

    Returns comprehensive campaign analytics with daily timeline and top-performing URLs.

    **Authentication:** Required (JWT Bearer token)

    **Path Parameters:**
    - **campaign_id**: UUID of the campaign

    **Responses:**
    - **200**: Campaign summary retrieved successfully - Includes total clicks, unique IPs, CTR, daily timeline (7 days), and top 5 performers
    - **400**: Invalid campaign ID format (not a valid UUID)
    - **401**: Authentication required or invalid token
    - **404**: Campaign not found, or someone else's personal campaign
    """
    # Convert campaign_id string to UUID
    try:
        campaign_uuid = UUIDType(campaign_id)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid campaign ID format",
        ) from exc

    # Verify the user can see the campaign (Phase 3.14.3 — the organization's, or their own)
    campaign = (
        db.query(Campaign)
        .filter(Campaign.id == campaign_uuid, viewer(db, current_user).sees(Campaign))
        .first()
    )
    if not campaign:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Campaign not found",
        )

    # Get all URLs for this campaign
    campaign_urls = db.query(URL).filter(URL.campaign_id == campaign_uuid).all()
    url_ids = [url.id for url in campaign_urls]

    # Total clicks
    total_clicks = (
        _exclude_bots(
            db.query(func.count(Visitor.id)).filter(Visitor.url_id.in_(url_ids)),
            include_bots,
        ).scalar()
        or 0
    )

    # Unique IPs
    unique_ips = (
        _exclude_bots(
            db.query(func.count(func.distinct(Visitor.ip))).filter(Visitor.url_id.in_(url_ids)),
            include_bots,
        ).scalar()
        or 0
    )

    # Click-through rate (percentage of URLs that have at least one click)
    urls_with_clicks = (
        _exclude_bots(
            db.query(func.count(func.distinct(Visitor.url_id))).filter(Visitor.url_id.in_(url_ids)),
            include_bots,
        ).scalar()
        or 0
    )
    click_through_rate = (urls_with_clicks / len(campaign_urls) * 100) if campaign_urls else 0.0

    # Top performers (top 5 URLs by click count)
    top_q = (
        db.query(
            URL.short_code,
            URL.user_data,
            func.count(Visitor.id).label("click_count"),
            func.count(func.distinct(Visitor.ip)).label("unique_ips"),
            func.max(Visitor.visited_at).label("last_clicked"),
        )
        .join(Visitor, URL.id == Visitor.url_id)
        .filter(URL.campaign_id == campaign_uuid)
    )
    top_performers_data = (
        _exclude_bots(top_q, include_bots)
        # Group by the primary key only. `user_data` is JSON, which PostgreSQL can't
        # GROUP BY (no equality operator for `json`): listing it here made every
        # campaign summary a 500 on PostgreSQL while SQLite's tests passed. The other
        # selected URL columns depend on `urls.id`, so PostgreSQL accepts them as they are.
        .group_by(URL.id)
        .order_by(func.count(Visitor.id).desc())
        .limit(5)
        .all()
    )

    top_performers = [
        CampaignUserStat(
            user_data=perf.user_data or {},
            short_code=perf.short_code,
            clicks=perf.click_count,
            unique_ips=perf.unique_ips,
            last_clicked=perf.last_clicked,
        )
        for perf in top_performers_data
    ]

    # Daily timeline: the last 7 days where the viewer is, today included.
    days = LocalDays.of(current_user, tz)
    visits = _exclude_bots(db.query(Visitor).filter(Visitor.url_id.in_(url_ids)), include_bots)
    daily_timeline = [
        DailyStats(date=day, clicks=clicks) for day, clicks in last_days(visits, days, 7)
    ]

    return CampaignSummary(
        campaign_id=str(campaign.id),
        campaign_name=campaign.name,
        original_url=campaign.original_url,
        total_urls=len(campaign_urls),
        total_clicks=total_clicks,
        unique_ips=unique_ips,
        click_through_rate=round(click_through_rate, 2),
        top_performers=top_performers,
        daily_timeline=daily_timeline,
        timezone=days.name,
    )


@analytics_router.get(
    "/campaigns/{campaign_id}/users",
    response_model=CampaignUsersResponse,
    responses={
        200: {"description": "Campaign user statistics retrieved successfully"},
        **get_responses(400, 401, 404),
    },
)
def get_campaign_users(
    campaign_id: str,
    include_bots: bool = Query(False, description="Include bot/crawler visits in counts"),
    format: str = Query("json", pattern="^(json|csv)$", description="Response format"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Get detailed statistics for each user in a campaign.

    Returns per-URL statistics for all users in the campaign, sorted by clicks.

    **Authentication:** Required (JWT Bearer token)

    **Path Parameters:**
    - **campaign_id**: UUID of the campaign

    **Responses:**
    - **200**: Campaign user statistics retrieved successfully - Returns all users with their click stats, sorted by clicks descending
    - **400**: Invalid campaign ID format (not a valid UUID)
    - **401**: Authentication required or invalid token
    - **404**: Campaign not found, or someone else's personal campaign
    """
    # Convert campaign_id string to UUID
    try:
        campaign_uuid = UUIDType(campaign_id)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid campaign ID format",
        ) from exc

    # Verify the user can see the campaign (Phase 3.14.3 — the organization's, or their own)
    campaign = (
        db.query(Campaign)
        .filter(Campaign.id == campaign_uuid, viewer(db, current_user).sees(Campaign))
        .first()
    )
    if not campaign:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Campaign not found",
        )

    # Get all URLs with their visit stats
    campaign_urls = db.query(URL).filter(URL.campaign_id == campaign_uuid).all()

    # Stats for every campaign URL in one grouped query (no N+1); URLs without
    # visits are absent from the result
    stats_q = (
        db.query(
            Visitor.url_id,
            func.count(Visitor.id).label("click_count"),
            func.count(func.distinct(Visitor.ip)).label("unique_ips"),
            func.max(Visitor.visited_at).label("last_clicked"),
        )
        .join(URL, URL.id == Visitor.url_id)
        .filter(URL.campaign_id == campaign_uuid)
    )
    stats_by_url = {
        row.url_id: row
        for row in _exclude_bots(stats_q, include_bots).group_by(Visitor.url_id).all()
    }

    users = []
    for url in campaign_urls:
        stats = stats_by_url.get(url.id)
        users.append(
            CampaignUserStat(
                user_data=url.user_data or {},
                short_code=url.short_code,
                clicks=stats.click_count if stats else 0,
                unique_ips=stats.unique_ips if stats else 0,
                last_clicked=stats.last_clicked if stats else None,
            )
        )

    # Sort by clicks descending
    users.sort(key=lambda x: x.clicks, reverse=True)

    if format == "csv":
        # Flatten user_data dict into the row for spreadsheet readability
        all_keys: list[str] = []
        for u in users:
            for k in u.user_data.keys():
                if k not in all_keys:
                    all_keys.append(k)
        headers = [*all_keys, "short_code", "clicks", "unique_ips", "last_clicked"]

        def _rows():
            for u in users:
                row = [u.user_data.get(k, "") for k in all_keys]
                row.extend(
                    [
                        u.short_code,
                        u.clicks,
                        u.unique_ips,
                        u.last_clicked.isoformat() if u.last_clicked else "",
                    ]
                )
                yield row

        return stream_csv(
            headers=headers,
            rows=_rows(),
            filename=f"campaign-{campaign.id}-users.csv",
        )

    return CampaignUsersResponse(
        campaign_id=str(campaign.id),
        campaign_name=campaign.name,
        users=users,
        total_users=len(users),
    )


@analytics_router.get(
    "/overview",
    response_model=OverviewStats,
    responses={
        200: {"description": "Overview statistics retrieved successfully"},
        **get_responses(401),
    },
)
def get_overview_stats(
    include_bots: bool = Query(False, description="Include bot/crawler visits in counts"),
    tz: TimeZoneParam = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Get overview statistics for the user's dashboard.

    Returns high-level analytics across the URLs and campaigns the user can see:
    the organization's and their own personal ones.

    **Authentication:** Required (JWT Bearer token)

    **Responses:**
    - **200**: Overview statistics retrieved successfully - Includes total URLs, campaigns, clicks, unique visitors, recent activity (7 days), and top 5 URLs
    - **401**: Authentication required or invalid token

    **Note:** Includes all-time totals and recent activity for the last 7 days, today
    included, in your profile's time zone (or `tz`, else UTC; `timezone` says which).
    `recent_clicks_7d` is their sum.
    Each `top_urls` item has `short_code`, `short_url`, `title`, `original_url`,
    `url_type` and `clicks` (tracking-pixel opens are never counted as clicks).
    """
    who = viewer(db, current_user)

    # Total URLs
    total_urls = db.query(func.count(URL.id)).filter(who.sees(URL)).scalar() or 0

    # Total campaigns
    total_campaigns = db.query(func.count(Campaign.id)).filter(who.sees(Campaign)).scalar() or 0

    # Get all the URLs the user can see
    user_url_ids = db.query(URL.id).filter(who.sees(URL)).all()
    url_ids = [url_id[0] for url_id in user_url_ids]

    # Total clicks (all time)
    total_clicks = (
        _exclude_bots(
            db.query(func.count(Visitor.id)).filter(Visitor.url_id.in_(url_ids)),
            include_bots,
        ).scalar()
        or 0
    )

    # Unique visitors (all time)
    total_unique_visitors = (
        _exclude_bots(
            db.query(func.count(func.distinct(Visitor.ip))).filter(Visitor.url_id.in_(url_ids)),
            include_bots,
        ).scalar()
        or 0
    )

    # Recent activity: the last 7 days where the viewer is, today included. The headline is
    # their sum, so it matches the chart (it used to be a rolling 168 hours).
    days = LocalDays.of(current_user, tz)
    recent = _exclude_bots(db.query(Visitor).filter(Visitor.url_id.in_(url_ids)), include_bots)
    recent_activity = [
        DailyStats(date=day, clicks=clicks) for day, clicks in last_days(recent, days, 7)
    ]
    recent_clicks_7d = sum(day.clicks for day in recent_activity)

    # Top 5 URLs by click count.
    # outer-join keeps URLs with zero visits; click filters must be expressed on the join
    # condition (not as a where) so the LEFT JOIN still emits those URL rows.
    # Phase 3.11 — tracking-pixel opens are never clicks (same definition as
    # `_exclude_bots`, and as `URLResponse.click_count`), even with include_bots.
    visitor_join = (URL.id == Visitor.url_id) & (Visitor.is_pixel.is_(False))
    if not include_bots:
        visitor_join = visitor_join & (Visitor.is_bot.is_(False))
    top_urls_data = (
        db.query(
            URL.short_code,
            URL.original_url,
            URL.url_type,
            URL.title,
            Domain.hostname,
            func.count(Visitor.id).label("click_count"),
        )
        .join(Visitor, visitor_join, isouter=True)
        .outerjoin(Domain, URL.domain_id == Domain.id)
        .filter(who.sees(URL))
        .group_by(
            URL.id, URL.short_code, URL.original_url, URL.url_type, URL.title, Domain.hostname
        )
        .order_by(func.count(Visitor.id).desc())
        .limit(5)
        .all()
    )

    top_urls = [
        {
            "short_code": url.short_code,
            # Phase 3.11 — absolute short URL + title so the dashboard can render/copy links;
            # Phase 8.3 — on the link's own domain, which the dashboard links to it with
            "short_url": build_short_url(url.short_code, url.hostname),
            "domain": url.hostname or normalize_hostname(settings.default_domain),
            "title": url.title,
            "original_url": url.original_url,
            "url_type": url.url_type.value,
            "clicks": url.click_count or 0,
        }
        for url in top_urls_data
    ]

    return OverviewStats(
        total_urls=total_urls,
        total_campaigns=total_campaigns,
        total_clicks=total_clicks,
        total_unique_visitors=total_unique_visitors,
        recent_clicks_7d=recent_clicks_7d,
        top_urls=top_urls,
        recent_activity=recent_activity,
        timezone=days.name,
    )


@analytics_router.get(
    "/orphan-visits",
    responses={
        200: {"description": "Orphan visits retrieved (typo'd / unknown short codes)"},
        **get_responses(401),
    },
)
def get_orphan_visits(
    limit: int = Query(100, ge=1, le=500, description="Max number of rows"),
    skip: int = Query(0, ge=0),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Phase 3.10.4 — List orphan visits.

    Useful for catching typo'd codes leaked into print/QR campaigns. Authentication
    is required because attempted paths and IPs may be sensitive; ownership scoping
    is intentionally absent (orphan visits don't belong to any user — they're
    tenant-wide signals at single-tenant launch).
    """
    rows = (
        db.query(OrphanVisit)
        .order_by(OrphanVisit.created_at.desc())
        .offset(skip)
        .limit(limit)
        .all()
    )
    return {
        "total": db.query(func.count(OrphanVisit.id)).scalar() or 0,
        "items": [
            {
                "id": str(r.id),
                "type": r.type.value,
                "attempted_path": r.attempted_path,
                "ip": r.ip,
                "user_agent": r.user_agent,
                "referer": r.referer,
                "created_at": r.created_at.isoformat() if r.created_at else None,
            }
            for r in rows
        ],
    }
