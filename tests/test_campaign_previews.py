"""
Cleanup sweep T3 — a campaign's links get their page's preview.

Every link of a campaign points to the same destination, so creating one, through the API or the
curated MCP tool, fetches that page once and stores its `page_*` columns on all of them. The fetch
runs after the links are committed (no transaction waits on the page), and a failure fails nothing:
the links just have no page preview yet, and the daily housekeeping fetches it later.
"""

import pytest

from server.core.models import URL, Campaign, URLType
from server.utils.opengraph import OpenGraphMetadata

DESTINATION = "https://example.com/webinar"
CSV = "email,company\nada@example.com,Acme\nbob@example.com,Globex\ncy@example.com,Initech"
ROWS = [
    {"email": "ada@example.com", "company": "Acme"},
    {"email": "bob@example.com", "company": "Globex"},
    {"email": "cy@example.com", "company": "Initech"},
]


class FakeFetcher:
    """Stands in for fetch_opengraph_metadata: counts calls, notes the session's state."""

    def __init__(self, db_session, answer=None, error=None):
        self.db_session = db_session
        self.answer = answer
        self.error = error
        self.calls: list[str] = []
        self.in_transaction: list[bool] = []

    async def fetch(self, url, *_args, **_kwargs):
        self.calls.append(url)
        self.in_transaction.append(self.db_session.in_transaction())
        if self.error is not None:
            raise self.error
        return self.answer


def _page():
    return OpenGraphMetadata(
        title="The webinar",
        description="Join us live",
        image_url="https://example.com/og.png",
        favicon_url="https://example.com/favicon.ico",
    )


def _install(monkeypatch, fake):
    monkeypatch.setattr("server.utils.previews.fetch_opengraph_metadata", fake.fetch)


def _campaign_links(db_session):
    db_session.expire_all()
    return db_session.query(URL).filter(URL.url_type == URLType.CAMPAIGN).all()


def _create_via_api(client, auth_headers):
    return client.post(
        "/api/v1/campaigns",
        json={"name": "Webinar", "original_url": DESTINATION, "csv_data": CSV},
        headers=auth_headers,
    )


def _create_via_mcp(db_session, user):
    pytest.importorskip("fastmcp")
    from mcp_server import curated

    return curated.create_campaign_from_rows(
        db_session, user, name="Webinar", original_url=DESTINATION, rows=ROWS
    )


def _assert_previewed(links):
    assert len(links) == 3
    for link in links:
        assert link.page_og_title == "The webinar"
        assert link.page_og_description == "Join us live"
        assert link.page_og_image_url == "https://example.com/og.png"
        assert link.page_favicon_url == "https://example.com/favicon.ico"
        assert link.page_fetched_at is not None
        # The overrides stay empty: the page's preview isn't a person's.
        assert link.og_title is None and link.og_description is None and link.og_image_url is None


# ---------------------------------------------------------------------------
# The API
# ---------------------------------------------------------------------------


def test_api_fetches_once_and_every_link_gets_the_preview(
    client, auth_headers, db_session, monkeypatch
):
    fake = FakeFetcher(db_session, answer=_page())
    _install(monkeypatch, fake)

    response = _create_via_api(client, auth_headers)

    assert response.status_code == 201
    assert response.json()["url_count"] == 3
    assert fake.calls == [DESTINATION]
    _assert_previewed(_campaign_links(db_session))


def test_api_fetches_on_the_apps_loop_with_no_transaction_open(
    client, auth_headers, db_session, monkeypatch
):
    """The sync route runs in a worker thread: the fetch goes back to the app's loop, not a new one."""
    fake = FakeFetcher(db_session, answer=_page())
    _install(monkeypatch, fake)

    def no_new_loop(*_args, **_kwargs):
        raise AssertionError("the route's fetch started an event loop of its own")

    monkeypatch.setattr("server.utils.previews.anyio.run", no_new_loop)

    assert _create_via_api(client, auth_headers).status_code == 201
    assert fake.calls == [DESTINATION]
    assert fake.in_transaction == [False]


@pytest.mark.parametrize(
    "fake_kwargs",
    [
        {"answer": OpenGraphMetadata.failed()},
        {"error": RuntimeError("the page blew up")},
    ],
    ids=["page-did-not-answer", "fetcher-raised"],
)
def test_api_a_failed_fetch_still_creates_the_campaign(
    client, auth_headers, db_session, monkeypatch, fake_kwargs
):
    fake = FakeFetcher(db_session, **fake_kwargs)
    _install(monkeypatch, fake)

    response = _create_via_api(client, auth_headers)

    assert response.status_code == 201
    assert response.json()["url_count"] == 3
    assert db_session.query(Campaign).count() == 1
    links = _campaign_links(db_session)
    assert len(links) == 3
    assert all(link.page_fetched_at is None and link.page_og_title is None for link in links)


# ---------------------------------------------------------------------------
# The curated MCP tool
# ---------------------------------------------------------------------------


def test_mcp_fetches_once_and_every_link_gets_the_preview(db_session, test_user, monkeypatch):
    fake = FakeFetcher(db_session, answer=_page())
    _install(monkeypatch, fake)

    result = _create_via_mcp(db_session, test_user)

    assert result["url_count"] == 3
    assert fake.calls == [DESTINATION]
    assert fake.in_transaction == [False]
    _assert_previewed(_campaign_links(db_session))


@pytest.mark.parametrize(
    "fake_kwargs",
    [
        {"answer": OpenGraphMetadata.failed()},
        {"error": RuntimeError("the page blew up")},
    ],
    ids=["page-did-not-answer", "fetcher-raised"],
)
def test_mcp_a_failed_fetch_still_creates_the_campaign(
    db_session, test_user, monkeypatch, fake_kwargs
):
    fake = FakeFetcher(db_session, **fake_kwargs)
    _install(monkeypatch, fake)

    result = _create_via_mcp(db_session, test_user)

    assert result["url_count"] == 3
    assert fake.calls == [DESTINATION]
    links = _campaign_links(db_session)
    assert len(links) == 3
    assert all(link.page_fetched_at is None for link in links)


# ---------------------------------------------------------------------------
# The helper
# ---------------------------------------------------------------------------


def test_helper_writes_what_store_page_preview_would(db_session, test_user, monkeypatch):
    """Long titles are cut to the column, blanks and NULs cleaned, as for a single link."""
    from server.utils.domain import get_or_create_default_domain
    from server.utils.previews import store_page_preview_on_links

    long_title = "T" * 1000
    fake = FakeFetcher(
        db_session,
        answer=OpenGraphMetadata(title=long_title, description="  \x00  ", image_url=None),
    )
    _install(monkeypatch, fake)

    domain_id = get_or_create_default_domain(db_session).id
    links = [
        URL(
            short_code=f"lnk{i}",
            original_url=DESTINATION,
            url_type=URLType.STANDARD,
            created_by=test_user.id,
            domain_id=domain_id,
        )
        for i in range(2)
    ]
    db_session.add_all(links)
    db_session.commit()

    assert store_page_preview_on_links(db_session, DESTINATION, links) is True

    column_length = URL.page_og_title.type.length
    for link in links:
        db_session.refresh(link)
        assert link.page_og_title is not None
        assert len(link.page_og_title) <= column_length
        assert link.page_og_description is None
        assert link.page_fetched_at is not None


def test_helper_does_not_fetch_without_links(db_session, monkeypatch):
    from server.utils.previews import store_page_preview_on_links

    fake = FakeFetcher(db_session, answer=_page())
    _install(monkeypatch, fake)

    assert store_page_preview_on_links(db_session, DESTINATION, []) is False
    assert fake.calls == []
