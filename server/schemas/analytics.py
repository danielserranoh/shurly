"""Schemas for analytics endpoints."""

from datetime import date, datetime

from pydantic import BaseModel


class DailyStats(BaseModel):
    """Daily statistics for a URL."""

    date: date
    clicks: int


class DailyStatsResponse(BaseModel):
    """Response for daily statistics."""

    short_code: str
    stats: list[DailyStats]
    total_clicks: int


class WeeklyStats(BaseModel):
    """Weekly statistics for a URL."""

    week_start: date
    week_end: date
    clicks: int


class WeeklyStatsResponse(BaseModel):
    """Response for weekly statistics."""

    short_code: str
    stats: list[WeeklyStats]
    total_clicks: int


class GeoStats(BaseModel):
    """Geographic statistics."""

    country: str
    clicks: int


class GeoStatsResponse(BaseModel):
    """Response for geographic statistics."""

    short_code: str
    stats: list[GeoStats]
    total_clicks: int
    period_days: int


class CampaignUserStat(BaseModel):
    """Statistics for a campaign user."""

    user_data: dict
    short_code: str
    clicks: int
    unique_ips: int
    last_clicked: datetime | None = None


class CampaignUsersResponse(BaseModel):
    """Response for campaign user statistics."""

    campaign_id: str
    campaign_name: str
    users: list[CampaignUserStat]
    total_users: int


class CampaignSummary(BaseModel):
    """Summary statistics for a campaign."""

    campaign_id: str
    campaign_name: str
    original_url: str
    total_urls: int
    total_clicks: int
    unique_ips: int
    click_through_rate: float  # Percentage of URLs that have been clicked
    top_performers: list[CampaignUserStat]  # Top 5 most clicked
    daily_timeline: list[DailyStats]  # Last 7 days


class OverviewStats(BaseModel):
    """Overview statistics for the user's dashboard."""

    total_urls: int
    total_campaigns: int
    total_clicks: int
    total_unique_visitors: int
    recent_clicks_7d: int
    top_urls: list[dict]  # Top 5 URLs with click counts
    recent_activity: list[DailyStats]  # Last 7 days
