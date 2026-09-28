"""Schemas for analytics endpoints."""

from datetime import date, datetime

from pydantic import BaseModel, Field


class DailyStats(BaseModel):
    """Daily statistics for a URL."""

    date: date
    clicks: int


class DailyStatsResponse(BaseModel):
    """Response for daily statistics."""

    short_code: str
    stats: list[DailyStats]
    total_clicks: int
    # The IANA time zone the days are counted in: `?tz=`, else the viewer's profile, else UTC.
    timezone: str = Field(description="The IANA time zone the days are counted in")


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
    # The IANA time zone the days are counted in: `?tz=`, else the viewer's profile, else UTC.
    timezone: str = Field(description="The IANA time zone the days are counted in")


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
    # The IANA time zone the days are counted in: `?tz=`, else the viewer's profile, else UTC.
    timezone: str = Field(description="The IANA time zone the days are counted in")


class OverviewStats(BaseModel):
    """Overview statistics for the user's dashboard."""

    total_urls: int
    total_campaigns: int
    total_clicks: int
    total_unique_visitors: int
    # The last 7 days where the viewer is, today included: the sum of recent_activity.
    recent_clicks_7d: int
    top_urls: list[dict]  # Top 5 URLs with click counts
    recent_activity: list[DailyStats]  # Last 7 days
    # The IANA time zone the days are counted in: `?tz=`, else the viewer's profile, else UTC.
    timezone: str = Field(description="The IANA time zone the days are counted in")


# Phase 3.16 — per-link analytics, as on Shlink's link page (ROADMAP 3.16.1).


class LinkPeriodResponse(BaseModel):
    """What every per-link response over a period starts with: the link, and the range counted."""

    short_code: str
    domain: str = Field(description="The link's domain")
    first: date = Field(alias="from", description="The first local day counted")
    last: date = Field(alias="to", description="The last local day counted: today at the latest")
    timezone: str = Field(description="The IANA time zone the days are counted in")


class LinkTotalsResponse(BaseModel):
    """A link's all-time numbers, for the header of its page."""

    short_code: str
    domain: str = Field(description="The link's domain")
    timezone: str = Field(description="The IANA time zone `last_click_at` is given in")
    clicks: int = Field(description="Every click, as `click_count`")
    opens: int = Field(description="Hits on its email tracking pixel that aren't a bot's")
    countries: int = Field(description="How many distinct countries its clicks came from")
    last_click_at: datetime | None = Field(description="The latest click, or null")


class TimeseriesBucket(BaseModel):
    start: date
    end: date = Field(description="The bucket's last day, inclusive")
    clicks: int
    opens: int


class HourCounts(BaseModel):
    hour: int = Field(description="0 to 23, local")
    clicks: int
    opens: int


class WeekdayCounts(BaseModel):
    day: int = Field(description="1 is Monday, 7 Sunday")
    clicks: int
    opens: int


class TimeseriesResponse(LinkPeriodResponse):
    group_by: str
    clicks: int
    opens: int
    stats: list[TimeseriesBucket]
    hour_of_day: list[HourCounts]
    day_of_week: list[WeekdayCounts]


class BreakdownItem(BaseModel):
    name: str = Field(description='The value, or "Unknown"; a referrer\'s is "Direct" without one')
    count: int
    share: float = Field(description="`count` over the response's `total`, 0 to 1, 4 decimals")


class BreakdownResponse(LinkPeriodResponse):
    type: str = Field(description="The kind of visit counted: clicks, opens, bots or all")
    total: int
    os: list[BreakdownItem]
    browsers: list[BreakdownItem]
    devices: list[BreakdownItem]
    referrers: list[BreakdownItem]
    countries: list[BreakdownItem]


class VisitRow(BaseModel):
    """One visit, as the list shows it: never an IP, a user agent or a full referrer."""

    visited_at: datetime = Field(description="Local, with the zone's offset, to the second")
    kind: str = Field(description="click, open or bot")
    country: str = Field(description='An ISO code, or "Unknown"')
    browser: str
    os: str
    device: str
    referrer: str = Field(description='The host, or "Direct" without one')


class VisitsResponse(LinkPeriodResponse):
    type: str = Field(description="The kind of visit listed: clicks, opens, bots or all")
    total: int = Field(description="How many match, on every page")
    page: int
    page_size: int
    pages: int
    visits: list[VisitRow]
