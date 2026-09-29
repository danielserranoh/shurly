"""
A crawler's preview of a campaign link never carries its recipient's data (docs/PERSONAL_DATA.md,
finding 1). When a recipient shares their link, the social network's crawler asks for it: its
preview page's refresh target is the link's destination without the recipient's `user_data`,
which only people, redirected, still get.
"""

import html
from urllib.parse import parse_qs, quote, quote_plus, urlsplit

import pytest

from server.core.models import URL, Campaign, URLType
from server.utils.domain import get_or_create_default_domain

ROW = {"name": "Zelda", "email": "zelda.marker@example.com", "company": "Hyrule Ltd"}
LINKEDIN = "LinkedInBot/1.0 (compatible; Mozilla/5.0; Apache-HttpClient +http://www.linkedin.com)"
BROWSER = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 Version/18.0 Safari/605.1.15"


@pytest.fixture
def link(db_session, test_user) -> URL:
    campaign = Campaign(
        name="Q4",
        original_url="https://example.com/webinar?lang=es",
        csv_columns=list(ROW),
        created_by=test_user.id,
    )
    db_session.add(campaign)
    db_session.flush()
    url = URL(
        short_code="q4-zelda",
        original_url=campaign.original_url,
        url_type=URLType.CAMPAIGN,
        campaign_id=campaign.id,
        user_data=ROW,
        created_by=test_user.id,
        domain_id=get_or_create_default_domain(db_session).id,
    )
    db_session.add(url)
    db_session.commit()
    return url


def _leaks(body: str) -> list[str]:
    """Each of the row's values, however a page might carry it."""
    return [
        form
        for value in ROW.values()
        for form in {value, quote(value), quote_plus(value), html.escape(value)}
        if form in body
    ]


def _refresh_target(body: str) -> str:
    start = body.index('http-equiv="refresh" content="2;url=') + len(
        'http-equiv="refresh" content="2;url='
    )
    return html.unescape(body[start : body.index('"', start)])


def test_a_crawler_gets_no_recipient_data(client, link):
    response = client.get("/q4-zelda", headers={"user-agent": LINKEDIN}, follow_redirects=False)

    assert response.status_code == 200
    assert _leaks(response.text) == []
    assert _refresh_target(response.text) == "https://example.com/webinar?lang=es"


def test_what_the_shared_address_forwards_stays(client, link):
    """Its own query is the sharer's, already public: forwarded as for anyone."""
    response = client.get(
        "/q4-zelda?utm_source=linkedin", headers={"user-agent": LINKEDIN}, follow_redirects=False
    )

    assert _leaks(response.text) == []
    assert (
        _refresh_target(response.text) == "https://example.com/webinar?lang=es&utm_source=linkedin"
    )


def test_people_still_get_their_personalized_redirect(client, link):
    response = client.get(
        "/q4-zelda?utm_source=email", headers={"user-agent": BROWSER}, follow_redirects=False
    )

    assert response.status_code == 302
    location = urlsplit(response.headers["location"])
    assert (location.netloc, location.path) == ("example.com", "/webinar")
    assert parse_qs(location.query) == {
        "lang": ["es"],
        "name": ["Zelda"],
        "email": ["zelda.marker@example.com"],
        "company": ["Hyrule Ltd"],
        "utm_source": ["email"],
    }


def test_a_forwarded_parameter_still_wins_a_clash(client, link):
    """Unchanged: the shared address's own `name` replaces the row's, as it always has."""
    response = client.get(
        "/q4-zelda?name=Link", headers={"user-agent": BROWSER}, follow_redirects=False
    )

    assert parse_qs(urlsplit(response.headers["location"]).query)["name"] == ["Link"]
