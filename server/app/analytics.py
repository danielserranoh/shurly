"""Analytics endpoints for URLs and campaigns."""

from datetime import datetime, timedelta
from uuid import UUID as UUIDType

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import func
from sqlalchemy.orm import Session

from server.core import get_db
from server.core.auth import get_current_user
from server.core.models import URL, Campaign, User, Visitor
from server.core.models.url import URLType
from server.schemas.analytics import (
    CampaignSummary,
    CampaignUserStat,
    CampaignUsersResponse,
    DailyStats,
    DailyStatsResponse,
    GeoStats,
    GeoStatsResponse,
    OverviewStats,
    WeeklyStats,
    WeeklyStatsResponse,
)

analytics_router = APIRouter()


@analytics_router.get("/urls/{short_code}/daily", response_model=DailyStatsResponse)
def get_url_daily_stats(
    short_code: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Get daily click statistics for a URL (last 7 days).
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
    visits_by_date = (
        db.query(
            func.date(Visitor.visited_at).label("visit_date"),
            func.count(Visitor.id).label("click_count"),
        )
        .filter(
            Visitor.short_code == short_code,
            Visitor.visited_at >= seven_days_ago_dt,
        )
        .group_by(func.date(Visitor.visited_at))
        .all()
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

    return DailyStatsResponse(
        short_code=short_code,
        stats=stats,
        total_clicks=total_clicks,
    )


@analytics_router.get("/urls/{short_code}/weekly", response_model=WeeklyStatsResponse)
def get_url_weekly_stats(
    short_code: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Get weekly click statistics for a URL (last 8 weeks).
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
        click_count = (
            db.query(func.count(Visitor.id))
            .filter(
                Visitor.short_code == short_code,
                func.date(Visitor.visited_at) >= week_start,
                func.date(Visitor.visited_at) <= week_end,
            )
            .scalar()
            or 0
        )

        total_clicks += click_count
        stats.append(
            WeeklyStats(
                week_start=week_start,
                week_end=week_end,
                clicks=click_count,
            )
        )

    return WeeklyStatsResponse(
        short_code=short_code,
        stats=stats,
        total_clicks=total_clicks,
    )


@analytics_router.get("/urls/{short_code}/geo", response_model=GeoStatsResponse)
def get_url_geo_stats(
    short_code: str,
    days: int = 30,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Get geographic distribution of clicks for a URL.

    Args:
        short_code: The short code to get stats for
        days: Number of days to look back (default 30)
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
    geo_stats = (
        db.query(
            Visitor.country,
            func.count(Visitor.id).label("click_count"),
        )
        .filter(
            Visitor.short_code == short_code,
            Visitor.visited_at >= cutoff_date,
            Visitor.country.isnot(None),
        )
        .group_by(Visitor.country)
        .order_by(func.count(Visitor.id).desc())
        .all()
    )

    stats = [
        GeoStats(country=geo.country or "Unknown", clicks=geo.click_count)
        for geo in geo_stats
    ]

    total_clicks = sum(stat.clicks for stat in stats)

    return GeoStatsResponse(
        short_code=short_code,
        stats=stats,
        total_clicks=total_clicks,
        period_days=days,
    )


@analytics_router.get("/campaigns/{campaign_id}/summary", response_model=CampaignSummary)
def get_campaign_summary(
    campaign_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Get summary statistics for a campaign including timeline and top performers.
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
        db.query(func.count(Visitor.id))
        .filter(Visitor.url_id.in_(url_ids))
        .scalar()
        or 0
    )

    # Unique IPs
    unique_ips = (
        db.query(func.count(func.distinct(Visitor.ip)))
        .filter(Visitor.url_id.in_(url_ids))
        .scalar()
        or 0
    )

    # Click-through rate (percentage of URLs that have at least one click)
    urls_with_clicks = (
        db.query(func.count(func.distinct(Visitor.url_id)))
        .filter(Visitor.url_id.in_(url_ids))
        .scalar()
        or 0
    )
    click_through_rate = (urls_with_clicks / len(campaign_urls) * 100) if campaign_urls else 0.0

    # Top performers (top 5 URLs by click count)
    top_performers_data = (
        db.query(
            URL.short_code,
            URL.user_data,
            func.count(Visitor.id).label("click_count"),
            func.count(func.distinct(Visitor.ip)).label("unique_ips"),
            func.max(Visitor.visited_at).label("last_clicked"),
        )
        .join(Visitor, URL.id == Visitor.url_id)
        .filter(URL.campaign_id == campaign_uuid)
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

    daily_data = (
        db.query(
            func.date(Visitor.visited_at).label("visit_date"),
            func.count(Visitor.id).label("click_count"),
        )
        .filter(
            Visitor.short_code.in_(short_codes),
            func.date(Visitor.visited_at) >= seven_days_ago,
        )
        .group_by(func.date(Visitor.visited_at))
        .all()
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


@analytics_router.get("/campaigns/{campaign_id}/users", response_model=CampaignUsersResponse)
def get_campaign_users(
    campaign_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Get detailed statistics for each user in a campaign.
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
        stats = (
            db.query(
                func.count(Visitor.id).label("click_count"),
                func.count(func.distinct(Visitor.ip)).label("unique_ips"),
                func.max(Visitor.visited_at).label("last_clicked"),
            )
            .filter(Visitor.url_id == url.id)
            .first()
        )

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

    return CampaignUsersResponse(
        campaign_id=str(campaign.id),
        campaign_name=campaign.name,
        users=users,
        total_users=len(users),
    )


@analytics_router.get("/overview", response_model=OverviewStats)
def get_overview_stats(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Get overview statistics for the user's dashboard.
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
        db.query(func.count(Visitor.id)).filter(Visitor.url_id.in_(url_ids)).scalar() or 0
    )

    # Unique visitors (all time)
    total_unique_visitors = (
        db.query(func.count(func.distinct(Visitor.ip)))
        .filter(Visitor.url_id.in_(url_ids))
        .scalar()
        or 0
    )

    # Recent clicks (last 7 days)
    seven_days_ago = datetime.utcnow() - timedelta(days=7)
    recent_clicks_7d = (
        db.query(func.count(Visitor.id))
        .filter(Visitor.url_id.in_(url_ids), Visitor.visited_at >= seven_days_ago)
        .scalar()
        or 0
    )

    # Top 5 URLs by click count
    top_urls_data = (
        db.query(
            URL.short_code,
            URL.original_url,
            URL.url_type,
            func.count(Visitor.id).label("click_count"),
        )
        .join(Visitor, URL.id == Visitor.url_id, isouter=True)
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

    daily_data = (
        db.query(
            func.date(Visitor.visited_at).label("visit_date"),
            func.count(Visitor.id).label("click_count"),
        )
        .filter(
            Visitor.url_id.in_(url_ids),
            func.date(Visitor.visited_at) >= seven_days_ago_date,
        )
        .group_by(func.date(Visitor.visited_at))
        .all()
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
