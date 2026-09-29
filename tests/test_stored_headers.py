"""
A visit's user agent and referrer are stored at most 1024 and 2048 characters long (ROADMAP 6.3).

The columns are Text, so any length fitted, and a scanner could store tens of KB of header on
every hit, up to what the load balancer lets through. Real ones are a few hundred characters.
Only what's stored is cut: bot detection and the redirect rules read the whole header first.

The breakdown parses the stored user agent. A real one keeps its families once cut, padding
and all. Where it can't: a user agent whose telling words all come after its first 1024
characters (padding put in front, or a bot's name at the end) parses as its first 1024 do. Its
bot flag was set from the whole of it at the visit.
"""

import pytest

from server.core.models import URL, OrphanVisit, RedirectRule, Visitor
from server.utils.columns import REFERER_LENGTH, USER_AGENT_LENGTH, stored_user_agent
from server.utils.domain import get_or_create_default_domain
from server.utils.visit_facets import families
from tests.test_phase84_shlink_export import short_url, visit
from tests.test_phase84_shlink_import import owner, run  # noqa: F401 — `owner` is a fixture

CHROME = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/129.0.0.0 Safari/537.36"
)
PADDING = " x" * 30_000  # 60 KB, nothing a parser looks for
LONG_UA = CHROME + PADDING
LONG_REFERER = "https://news.example.com/article?" + "q=a&" * 15_000


@pytest.fixture
def link(db_session, test_user) -> URL:
    url = URL(
        short_code="hdr001",
        original_url="https://example.com/destination",
        created_by=test_user.id,
        domain_id=get_or_create_default_domain(db_session).id,
    )
    db_session.add(url)
    db_session.commit()
    return url


def _headers(user_agent: str = LONG_UA, referer: str = LONG_REFERER) -> dict:
    return {"user-agent": user_agent, "referer": referer}


@pytest.mark.parametrize("path", ["/hdr001", "/hdr001/track"])
def test_a_click_or_an_open_stores_them_cut(client, db_session, link, path):
    client.get(path, headers=_headers(), follow_redirects=False)

    stored = db_session.query(Visitor).one()
    assert (stored.user_agent, stored.referer) == (
        LONG_UA[:USER_AGENT_LENGTH],
        LONG_REFERER[:REFERER_LENGTH],
    )


@pytest.mark.parametrize("path", ["/nosuch1", "/"])
def test_an_orphan_visit_stores_them_cut(client, db_session, path):
    client.get(path, headers=_headers(), follow_redirects=False)

    stored = db_session.query(OrphanVisit).one()
    assert (len(stored.user_agent), len(stored.referer)) == (1024, 2048)


def test_a_short_header_is_stored_whole(client, db_session, link):
    client.get("/hdr001", headers=_headers(CHROME, "https://t.co/x"), follow_redirects=False)

    stored = db_session.query(Visitor).one()
    assert (stored.user_agent, stored.referer) == (CHROME, "https://t.co/x")


def test_bot_detection_reads_the_whole_user_agent(client, db_session, link):
    """A bot's name past the first 1024 characters: not stored, but the visit is a bot's."""
    client.get("/hdr001", headers=_headers(CHROME + PADDING + " Googlebot/2.1"))

    stored = db_session.query(Visitor).one()
    assert "Googlebot" not in stored.user_agent
    assert stored.is_bot is True


def test_the_rules_read_the_whole_user_agent(client, db_session, link):
    db_session.add(
        RedirectRule(
            url_id=link.id,
            priority=0,
            conditions=[{"type": "device", "value": "ios"}],
            target_url="https://example.com/ios",
        )
    )
    db_session.commit()

    response = client.get(
        "/hdr001", headers=_headers("Mozilla/5.0" + PADDING + " (iPhone)"), follow_redirects=False
    )

    assert response.headers["location"] == "https://example.com/ios"


def test_an_imported_visit_stores_them_cut(db_session, owner):  # noqa: F811
    imported = {**visit("2025-03-01T10:00:00+00:00"), "userAgent": LONG_UA, "referer": LONG_REFERER}

    run(db_session, owner, {"short_url": short_url("abc"), "visits": [imported]}, visits=True)

    stored = db_session.query(Visitor).one()
    assert (len(stored.user_agent), len(stored.referer)) == (USER_AGENT_LENGTH, REFERER_LENGTH)


# Real user agents, among the longest a link sees: in-app browsers, app webviews, bots.
REAL = [
    CHROME,
    "Mozilla/5.0 (iPhone; CPU iPhone OS 17_6 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) "
    "Mobile/15E148 [FBAN/FBIOS;FBAV/482.0.0.40.108;FBBV/650210001;FBDV/iPhone15,3;FBMD/iPhone;"
    "FBSN/iOS;FBSV/17.6;FBSS/3;FBID/phone;FBLC/en_US;FBOP/5;FBRV/652020537]",
    "Mozilla/5.0 (Linux; Android 14; SM-S918B Build/UP1A.231005.007; wv) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Version/4.0 Chrome/129.0.6668.81 Mobile Safari/537.36 Instagram "
    "350.0.0.46.105 Android (34/14; 450dpi; 1080x2340; samsung; SM-S918B; dm3q; qcom; en_GB; 634108161)",
    "Mozilla/5.0 (iPhone; CPU iPhone OS 17_5 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) "
    "Mobile/15E148 [LinkedInApp]/9.29.8472",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/129.0.0.0 Safari/537.36 Edg/129.0.2792.65",
    "Mozilla/5.0 (Linux; Android 10; K) AppleWebKit/537.36 (KHTML, like Gecko) "
    "SamsungBrowser/26.0 Chrome/122.0.0.0 Mobile Safari/537.36",
    "Mozilla/5.0 AppleWebKit/537.36 (KHTML, like Gecko; compatible; bingbot/2.0; "
    "+http://www.bing.com/bingbot.htm) Chrome/116.0.1938.76 Safari/537.36",
]


@pytest.mark.parametrize("user_agent", REAL)
def test_a_real_user_agent_parses_the_same_once_cut(user_agent):
    assert len(user_agent) < USER_AGENT_LENGTH  # stored whole anyway
    assert families(stored_user_agent(user_agent + PADDING)) == families(user_agent)


def test_what_it_cannot_keep_padding_in_front():
    """Its first 1024 characters are all the breakdown sees; the visit's bot flag and the
    rules read the whole of it."""
    padded = "x" * (2 * USER_AGENT_LENGTH) + " " + CHROME

    assert families(stored_user_agent(padded)).browser != families(CHROME).browser
