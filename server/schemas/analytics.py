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


class SeriesFields(BaseModel):
    """A series of clicks and opens: a link's (3.16) or a campaign's (3.17)."""

    group_by: str
    clicks: int
    opens: int
    stats: list[TimeseriesBucket]
    hour_of_day: list[HourCounts]
    day_of_week: list[WeekdayCounts]


class TimeseriesResponse(LinkPeriodResponse, SeriesFields):
    pass


class BreakdownItem(BaseModel):
    name: str = Field(description='The value, or "Unknown"; a referrer\'s is "Direct" without one')
    count: int
    share: float = Field(description="`count` over the response's `total`, 0 to 1, 4 decimals")


class CityItem(BaseModel):
    name: str = Field(
        description="The city's English name; \"Unknown\" without one; in a campaign's breakdown, "
        '"Other cities" for those its visits came from fewer than 5 of its links'
    )
    country: str | None = Field(
        description="Its country's ISO code: two cities of one name are two items. Null for "
        '"Unknown" and "Other cities"'
    )
    count: int
    share: float = Field(description="`count` over the response's `total`, 0 to 1, 4 decimals")


class BreakdownFields(BaseModel):
    """Visits of a kind by OS, browser, device, referrer, country and city: a link's or a
    campaign's."""

    type: str = Field(description="The kind of visit counted: clicks, opens, bots or all")
    total: int
    os: list[BreakdownItem]
    browsers: list[BreakdownItem]
    devices: list[BreakdownItem]
    referrers: list[BreakdownItem]
    countries: list[BreakdownItem]
    cities: list[CityItem] | None = Field(
        description="By city and country (Phase 8.4). Null for a campaign link: its visits are one "
        "named recipient's. A campaign's names a city only when its visits came from at least 5 "
        'of its links, and sums the rest as "Other cities"'
    )


class BreakdownResponse(LinkPeriodResponse, BreakdownFields):
    pass


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


# Phase 3.17 — per-campaign analytics (ROADMAP 3.17.1).


class CampaignPeriodResponse(BaseModel):
    """What every per-campaign response over a period starts with: the campaign, and the range."""

    campaign_id: str
    campaign_name: str
    first: date = Field(alias="from", description="The first local day counted")
    last: date = Field(alias="to", description="The last local day counted: today at the latest")
    timezone: str = Field(description="The IANA time zone the days are counted in")


class CampaignTotalsResponse(BaseModel):
    """A campaign's all-time numbers, for the header of its page."""

    campaign_id: str
    campaign_name: str
    timezone: str = Field(description="The IANA time zone `last_click_at` is given in")
    recipients: int = Field(description="Its links: one per recipient, a row of its CSV")
    clicks: int
    opens: int = Field(description="Hits on its links' email pixels that aren't a bot's")
    clicked: int = Field(description="Clicked: the recipients with at least one click")
    opened: int = Field(description="Opened: the recipients with at least one pixel open")
    click_rate: float = Field(description="clicked ÷ recipients, 0 to 1, 4 decimals")
    open_rate: float = Field(description="opened ÷ recipients, 0 to 1, 4 decimals")
    countries: int = Field(description="How many distinct countries its clicks came from")
    last_click_at: datetime | None = Field(description="The latest click, or null")


class CampaignTimeseriesResponse(CampaignPeriodResponse, SeriesFields):
    pass


class CampaignBreakdownResponse(CampaignPeriodResponse, BreakdownFields):
    pass


class RecipientRow(BaseModel):
    """A campaign's recipient, all time: their link, their CSV row, and what they did."""

    short_code: str
    short_url: str
    domain: str
    user_data: dict = Field(description="The recipient's row of the campaign's CSV")
    clicks: int
    opens: int
    first_click_at: datetime | None
    last_click_at: datetime | None
    last_open_at: datetime | None


class RecipientCounts(BaseModel):
    """How many recipients each filter gives for the search: Clicked and Opened can overlap."""

    all: int
    clicked: int = Field(description="Clicked: at least one click")
    opened: int = Field(description="Opened: at least one pixel open")
    none: int = Field(description="Neither clicked nor opened")


class RecipientsResponse(BaseModel):
    campaign_id: str
    campaign_name: str
    timezone: str = Field(description="The IANA time zone the times are given in")
    filter: str
    q: str
    sort: str
    order: str
    total: int = Field(description="How many match the filter and the search, on every page")
    page: int
    page_size: int
    pages: int
    counts: RecipientCounts
    recipients: list[RecipientRow]


# ROADMAP 3.10.4 — orphan visits by the path tried, for "Typos & broken links".


class OrphanSuggestion(BaseModel):
    """A link the path was probably meant for: one edit away, or the same code but for case."""

    short_code: str
    domain: str = Field(description="The link's domain")
    short_url: str
    title: str | None


class OrphanGroup(BaseModel):
    """A path tried on an unknown code: never an IP, a user agent or a referrer."""

    attempted_path: str
    visits: int
    first_seen: datetime = Field(description="Local, with the zone's offset, to the second")
    last_seen: datetime = Field(description="Local, with the zone's offset, to the second")
    did_you_mean: list[OrphanSuggestion] = Field(
        description="Up to 3 links the viewer sees, the likeliest first; none for a path no "
        "code could be (longer than a code, or with a character no code has)"
    )


class OrphanGroupsResponse(BaseModel):
    first: date = Field(alias="from", description="The first local day counted")
    last: date = Field(alias="to", description="The last local day counted: today at the latest")
    timezone: str = Field(description="The IANA time zone the days are counted in")
    total_visits: int = Field(description="Hits on unknown codes in the period")
    total_paths: int = Field(description="The paths they tried, on every page")
    page: int
    page_size: int
    pages: int
    groups: list[OrphanGroup]
