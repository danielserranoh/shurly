"""
Unique visitors are distinct addresses, and an unknown address is no one in particular: every
visit imported from Shlink has ip "unknown" (it exposes none), and so does a visit whose address
couldn't be read. So none of them counts as a visitor, in the overview, a campaign's summary and
users, and the MCP's link summary. The Shlink importer's README says unique counts cover the
cutover onward: now they do.
"""

from datetime import datetime, timedelta

import pytest

from mcp_server import curated
from server.core.models import URL, Campaign, URLType, Visitor
from server.utils.domain import get_or_create_default_domain

# Two visitors, whatever the number of visits without an address.
IPS = ["203.0.113.0", "unknown", "unknown", "198.51.100.0", "203.0.113.0", "unknown"]


@pytest.fixture
def campaign(db_session, test_user) -> Campaign:
    campaign = Campaign(
        name="Q4", original_url="https://example.com", csv_columns=["name"], created_by=test_user.id
    )
    db_session.add(campaign)
    db_session.flush()
    url = URL(
        short_code="uv1",
        original_url="https://example.com",
        url_type=URLType.CAMPAIGN,
        campaign_id=campaign.id,
        user_data={"name": "Ana"},
        created_by=test_user.id,
        domain_id=get_or_create_default_domain(db_session).id,
    )
    db_session.add(url)
    db_session.flush()
    for n, ip in enumerate(IPS):
        db_session.add(
            Visitor(
                url_id=url.id,
                short_code=url.short_code,
                ip=ip,
                visited_at=datetime.utcnow() - timedelta(minutes=n),
            )
        )
    db_session.commit()
    return campaign


def test_the_overview(client, auth_headers, campaign):
    body = client.get("/api/v1/analytics/overview", headers=auth_headers).json()

    assert (body["total_clicks"], body["total_unique_visitors"]) == (6, 2)


def test_a_campaigns_summary(client, auth_headers, campaign):
    body = client.get(f"/api/v1/analytics/campaigns/{campaign.id}/summary", headers=auth_headers)

    assert body.json()["unique_ips"] == 2
    assert [p["unique_ips"] for p in body.json()["top_performers"]] == [2]


def test_a_campaigns_users(client, auth_headers, campaign):
    body = client.get(f"/api/v1/analytics/campaigns/{campaign.id}/users", headers=auth_headers)

    assert [u["unique_ips"] for u in body.json()["users"]] == [2]


def test_the_mcps_link_summary(db_session, test_user, campaign):
    summary = curated.get_url_analytics_summary(db_session, test_user, short_code="uv1")

    assert (summary["totals"]["clicks"], summary["totals"]["unique_ips"]) == (6, 2)
