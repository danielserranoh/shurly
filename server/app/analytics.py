"""Analytics endpoints for URLs and campaigns."""

from datetime import datetime, timedelta
from uuid import UUID as UUIDType

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func
from sqlalchemy.orm import Query as SAQuery
from sqlalchemy.orm import Session

from server.core import get_db
from server.core.auth import get_current_user
from server.core.models import URL, Campaign, OrphanVisit, User, Visitor
from server.core.models.url import URLType
from server.utils.csv_export import stream_csv
from server.schemas.analytics import (
    CampaignSummary,
    CampaignUsersResponse,
    CampaignUserStat,
    DailyStats,
    DailyStatsResponse,
    GeoStats,
    GeoStatsResponse,
    OverviewStats,
    WeeklyStats,
    WeeklyStatsResponse,
)
from server.schemas.responses import get_responses


def _exclude_bots(query: SAQuery, include_bots: bool) -> SAQuery:
    """
    Phase 3.9.3 — analytics endpoints default to excluding bots.
    Phase 3.10.3 — also exclude email tracking pixel hits from click analytics
    (pixels are opens, not clicks; they share the visits table for timeline
    alignment but are conceptually a different metric).
    """
    q = query.filter(Visitor.is_pixel.is_(False))
    return q if include_bots else q.filter(Visitor.is_bot.is_(False))


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
    include_bots: bool = Query(False, description="Include bot/crawler visits in counts"),
    format: str = Query("json", pattern="^(json|csv)$", description="Response format"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Get daily click statistics for a URL (last 7 days).

    Returns day-by-day click counts for the last 7 days.

    **Authentication:** Required (JWT Bearer token)

    **Path Parameters:**
    - **short_code**: The short code to get statistics for

    **Responses:**
    - **200**: Daily statistics retrieved successfully - Returns 7 days of click data
    - **401**: Authentication required or invalid token
    - **404**: URL not found or doesn't belong to current user
    """
    # Verify URL exists and belongs to user
    url = db.query(URL).filter(URL.short_code == short_code, URL.created_by == current_user.id).first()
    if not url:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="URL not found",
        )

    # Get last 7 days
    today = datetime.utcnow().date()
    seven_days_ago = today - timedelta(days=6)
    # Convert to datetime for comparison
    seven_days_ago_dt = datetime.combine(seven_days_ago, datetime.min.time())

    # Query visits grouped by date
    base_q = db.query(
        func.date(Visitor.visited_at).label("visit_date"),
        func.count(Visitor.id).label("click_count"),
    ).filter(
        Visitor.short_code == short_code,
        Visitor.visited_at >= seven_days_ago_dt,
    )
    visits_by_date = (
        _exclude_bots(base_q, include_bots).group_by(func.date(Visitor.visited_at)).all()
    )

    # Create dict for easy lookup
    visits_dict = {visit.visit_date: visit.click_count for visit in visits_by_date}

    # Build stats for all 7 days (fill zeros for missing days)
    stats = []
    total_clicks = 0
    for i in range(7):
        day = seven_days_ago + timedelta(days=i)
        clicks = visits_dict.get(day, 0)
        total_clicks += clicks
        stats.append(DailyStats(date=day, clicks=clicks))

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
    include_bots: bool = Query(False, description="Include bot/crawler visits in counts"),
    format: str = Query("json", pattern="^(json|csv)$", description="Response format"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Get weekly click statistics for a URL (last 8 weeks).

    Returns week-by-week click counts for the last 8 weeks.

    **Authentication:** Required (JWT Bearer token)

    **Path Parameters:**
    - **short_code**: The short code to get statistics for

    **Responses:**
    - **200**: Weekly statistics retrieved successfully - Returns 8 weeks of click data
    - **401**: Authentication required or invalid token
    - **404**: URL not found or doesn't belong to current user
    """
    # Verify URL exists and belongs to user
    url = db.query(URL).filter(URL.short_code == short_code, URL.created_by == current_user.id).first()
    if not url:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="URL not found",
        )

    today = datetime.utcnow().date()
    eight_weeks_ago = today - timedelta(weeks=8)

    stats = []
    total_clicks = 0

    for i in range(8):
        week_start = eight_weeks_ago + timedelta(weeks=i)
        week_end = week_start + timedelta(days=6)

        # Count visits in this week
        wq = db.query(func.count(Visitor.id)).filter(
            Visitor.short_code == short_code,
            func.date(Visitor.visited_at) >= week_start,
            func.date(Visitor.visited_at) <= week_end,
        )
        click_count = _exclude_bots(wq, include_bots).scalar() or 0

        total_clicks += click_count
        stats.append(
            WeeklyStats(
                week_start=week_start,
                week_end=week_end,
                clicks=click_count,
            )
        )

    if format == "csv":
        return stream_csv(
            headers=["week_start", "week_end", "clicks"],
            rows=(
                (s.week_start.isoformat(), s.week_end.isoformat(), s.clicks)
                for s in stats
            ),
            filename=f"{short_code}-weekly.csv",
        )

    return WeeklyStatsResponse(
        short_code=short_code,
        stats=stats,
        total_clicks=total_clicks,
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
    - **404**: URL not found or doesn't belong to current user
    """
    # Verify URL exists and belongs to user
    url = db.query(URL).filter(URL.short_code == short_code, URL.created_by == current_user.id).first()
    if not url:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="URL not found",
        )

    cutoff_date = datetime.utcnow() - timedelta(days=days)

    # Query visits grouped by country
    geo_q = db.query(
        Visitor.country,
        func.count(Visitor.id).label("click_count"),
    ).filter(
        Visitor.short_code == short_code,
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
        GeoStats(country=geo.country or "Unknown", clicks=geo.click_count)
        for geo in geo_stats
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
    - **404**: Campaign not found or doesn't belong to current user
    """
    # Convert campaign_id string to UUID
    try:
        campaign_uuid = UUIDType(campaign_id)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid campaign ID format",
        )

    # Verify campaign exists and belongs to user
    campaign = (
        db.query(Campaign)
        .filter(Campaign.id == campaign_uuid, Campaign.created_by == current_user.id)
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
    short_codes = [url.short_code for url in campaign_urls]

    # Total clicks
    total_clicks = (
        _exclude_bots(
            db.query(func.count(Visitor.id)).filter(Visitor.url_id.in_(url_ids)),
            include_bots,
        )
        .scalar()
        or 0
    )

    # Unique IPs
    unique_ips = (
        _exclude_bots(
            db.query(func.count(func.distinct(Visitor.ip))).filter(Visitor.url_id.in_(url_ids)),
            include_bots,
        )
        .scalar()
        or 0
    )

    # Click-through rate (percentage of URLs that have at least one click)
    urls_with_clicks = (
        _exclude_bots(
            db.query(func.count(func.distinct(Visitor.url_id))).filter(
                Visitor.url_id.in_(url_ids)
            ),
            include_bots,
        )
        .scalar()
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
        .group_by(URL.id, URL.short_code, URL.user_data)
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

    # Daily timeline (last 7 days)
    today = datetime.utcnow().date()
    seven_days_ago = today - timedelta(days=6)

    daily_q = db.query(
        func.date(Visitor.visited_at).label("visit_date"),
        func.count(Visitor.id).label("click_count"),
    ).filter(
        Visitor.short_code.in_(short_codes),
        func.date(Visitor.visited_at) >= seven_days_ago,
    )
    daily_data = (
        _exclude_bots(daily_q, include_bots).group_by(func.date(Visitor.visited_at)).all()
    )

    daily_dict = {day.visit_date: day.click_count for day in daily_data}
    daily_timeline = []
    for i in range(7):
        day = seven_days_ago + timedelta(days=i)
        clicks = daily_dict.get(day, 0)
        daily_timeline.append(DailyStats(date=day, clicks=clicks))

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
    - **404**: Campaign not found or doesn't belong to current user
    """
    # Convert campaign_id string to UUID
    try:
        campaign_uuid = UUIDType(campaign_id)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid campaign ID format",
        )

    # Verify campaign exists and belongs to user
    campaign = (
        db.query(Campaign)
        .filter(Campaign.id == campaign_uuid, Campaign.created_by == current_user.id)
        .first()
    )
    if not campaign:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Campaign not found",
        )

    # Get all URLs with their visit stats
    campaign_urls = db.query(URL).filter(URL.campaign_id == campaign_uuid).all()

    users = []
    for url in campaign_urls:
        # Get stats for this URL
        stats_q = db.query(
            func.count(Visitor.id).label("click_count"),
            func.count(func.distinct(Visitor.ip)).label("unique_ips"),
            func.max(Visitor.visited_at).label("last_clicked"),
        ).filter(Visitor.url_id == url.id)
        stats = _exclude_bots(stats_q, include_bots).first()

        users.append(
            CampaignUserStat(
                user_data=url.user_data or {},
                short_code=url.short_code,
                clicks=stats.click_count or 0,
                unique_ips=stats.unique_ips or 0,
                last_clicked=stats.last_clicked,
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
                row.extend([
                    u.short_code,
                    u.clicks,
                    u.unique_ips,
                    u.last_clicked.isoformat() if u.last_clicked else "",
                ])
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
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Get overview statistics for the user's dashboard.

    Returns high-level analytics across all user's URLs and campaigns.

    **Authentication:** Required (JWT Bearer token)

    **Responses:**
    - **200**: Overview statistics retrieved successfully - Includes total URLs, campaigns, clicks, unique visitors, recent activity (7 days), and top 5 URLs
    - **401**: Authentication required or invalid token

    **Note:** Includes all-time totals and recent activity for the last 7 days.
    """
    # Total URLs
    total_urls = db.query(func.count(URL.id)).filter(URL.created_by == current_user.id).scalar() or 0

    # Total campaigns
    total_campaigns = (
        db.query(func.count(Campaign.id)).filter(Campaign.created_by == current_user.id).scalar() or 0
    )

    # Get all user's URLs
    user_url_ids = db.query(URL.id).filter(URL.created_by == current_user.id).all()
    url_ids = [url_id[0] for url_id in user_url_ids]

    # Total clicks (all time)
    total_clicks = (
        _exclude_bots(
            db.query(func.count(Visitor.id)).filter(Visitor.url_id.in_(url_ids)),
            include_bots,
        )
        .scalar()
        or 0
    )

    # Unique visitors (all time)
    total_unique_visitors = (
        _exclude_bots(
            db.query(func.count(func.distinct(Visitor.ip))).filter(Visitor.url_id.in_(url_ids)),
            include_bots,
        )
        .scalar()
        or 0
    )

    # Recent clicks (last 7 days)
    seven_days_ago = datetime.utcnow() - timedelta(days=7)
    recent_clicks_7d = (
        _exclude_bots(
            db.query(func.count(Visitor.id)).filter(
                Visitor.url_id.in_(url_ids), Visitor.visited_at >= seven_days_ago
            ),
            include_bots,
        )
        .scalar()
        or 0
    )

    # Top 5 URLs by click count.
    # outer-join keeps URLs with zero visits; bot filter must be expressed on the join
    # condition (not as a where) so the LEFT JOIN still emits those URL rows.
    visitor_join = URL.id == Visitor.url_id
    if not include_bots:
        visitor_join = visitor_join & (Visitor.is_bot.is_(False))
    top_urls_data = (
        db.query(
            URL.short_code,
            URL.original_url,
            URL.url_type,
            func.count(Visitor.id).label("click_count"),
        )
        .join(Visitor, visitor_join, isouter=True)
        .filter(URL.created_by == current_user.id)
        .group_by(URL.id, URL.short_code, URL.original_url, URL.url_type)
        .order_by(func.count(Visitor.id).desc())
        .limit(5)
        .all()
    )

    top_urls = [
        {
            "short_code": url.short_code,
            "original_url": url.original_url,
            "url_type": url.url_type.value,
            "clicks": url.click_count or 0,
        }
        for url in top_urls_data
    ]

    # Recent activity (last 7 days)
    today = datetime.utcnow().date()
    seven_days_ago_date = today - timedelta(days=6)

    daily_q = db.query(
        func.date(Visitor.visited_at).label("visit_date"),
        func.count(Visitor.id).label("click_count"),
    ).filter(
        Visitor.url_id.in_(url_ids),
        func.date(Visitor.visited_at) >= seven_days_ago_date,
    )
    daily_data = (
        _exclude_bots(daily_q, include_bots).group_by(func.date(Visitor.visited_at)).all()
    )

    daily_dict = {day.visit_date: day.click_count for day in daily_data}
    recent_activity = []
    for i in range(7):
        day = seven_days_ago_date + timedelta(days=i)
        clicks = daily_dict.get(day, 0)
        recent_activity.append(DailyStats(date=day, clicks=clicks))

    return OverviewStats(
        total_urls=total_urls,
        total_campaigns=total_campaigns,
        total_clicks=total_clicks,
        total_unique_visitors=total_unique_visitors,
        recent_clicks_7d=recent_clicks_7d,
        top_urls=top_urls,
        recent_activity=recent_activity,
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
