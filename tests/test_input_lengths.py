"""
Phase 6.3 — a value too long for its column is refused or cut, never a PostgreSQL 500.

Request fields carry a max_length matching their column, so a long one is a 422.
Values from outside a schema (a fetched page's title, an address from
X-Forwarded-For) are cut to their column: a link or a redirect mustn't fail
because someone else's page or header is long. SQLite doesn't enforce VARCHAR
lengths, so the 500s only show on PostgreSQL (the tests at the end).
"""

import pytest
from annotated_types import MaxLen
from fastapi.testclient import TestClient

from server.core.models import URL, Campaign, Tag, URLType, User, WaitlistEntry
from server.schemas.campaign import CampaignCreate
from server.schemas.tag import TagCreate, TagUpdate
from server.schemas.url import URLCreate, URLCustomCreate, URLUpdate
from server.schemas.waitlist import WaitlistJoin
from server.utils.columns import fit
from server.utils.opengraph import OpenGraphMetadata

# Request fields stored in a bounded column, and that column.
_BOUNDED_FIELDS = [
    (URLCreate, "title", URL.title),
    (URLCreate, "og_title", URL.og_title),
    (URLCustomCreate, "title", URL.title),
    (URLCustomCreate, "og_title", URL.og_title),
    (URLUpdate, "title", URL.title),
    (URLUpdate, "og_title", URL.og_title),
    (CampaignCreate, "name", Campaign.name),
    (TagCreate, "name", Tag.name),
    (TagUpdate, "name", Tag.name),
    # Phase 9.1 — the waitlist's public form.
    (WaitlistJoin, "email", WaitlistEntry.email),
    (WaitlistJoin, "name", WaitlistEntry.name),
    (WaitlistJoin, "company", WaitlistEntry.company),
    (WaitlistJoin, "role", WaitlistEntry.role),
    (WaitlistJoin, "use_case", WaitlistEntry.use_case),
    (WaitlistJoin, "source", WaitlistEntry.source),
]


def _max_length(schema, field: str) -> int | None:
    lengths = [m.max_length for m in schema.model_fields[field].metadata if isinstance(m, MaxLen)]
    return lengths[0] if lengths else None


@pytest.mark.parametrize(
    ("schema", "field", "column"), _BOUNDED_FIELDS, ids=lambda x: getattr(x, "__name__", x)
)
def test_every_bounded_request_field_fits_its_column(schema, field, column):
    """Widen a schema or narrow a column and this fails: the 500 would be back."""
    assert _max_length(schema, field) is not None
    assert _max_length(schema, field) <= column.type.length


class TestFit:
    def test_cuts_to_the_column(self):
        assert fit("x" * 300, URL.og_title) == "x" * 255

    def test_leaves_short_values_and_none_alone(self):
        assert fit("Short", URL.og_title) == "Short"
        assert fit(None, URL.og_title) is None


def test_the_mcp_campaign_tool_refuses_a_name_too_long(db_session, test_user):
    """create_campaign_from_rows writes through the ORM, past CampaignCreate's check."""
    from mcp_server import curated

    with pytest.raises(ValueError, match="255"):
        curated.create_campaign_from_rows(
            db_session,
            test_user,
            name="n" * 256,
            original_url="https://example.com",
            rows=[{"email": "a@griddo.io"}],
        )
    assert db_session.query(Campaign).count() == 0


# --- On PostgreSQL, where a long value was a 500 -------------------------------------


@pytest.fixture
def pg_client(pg_engine, monkeypatch):
    """The whole app on a fresh PostgreSQL, with a signed-in user."""
    from sqlalchemy.orm import sessionmaker

    from main import create_app
    from server.core import get_db
    from server.core.auth import create_access_token
    from server.core.migrations import run_migrations

    run_migrations(pg_engine)
    make_session = sessionmaker(bind=pg_engine)

    def _db():
        db = make_session()
        try:
            yield db
        finally:
            db.close()

    app = create_app()
    app.dependency_overrides[get_db] = _db
    with make_session() as db:
        db.add(User(email="pg@griddo.io", password_hash="x", is_active=True))
        db.commit()
    headers = {"Authorization": f"Bearer {create_access_token(data={'sub': 'pg@griddo.io'})}"}
    return app, make_session, headers


def test_a_page_with_a_long_title_still_gets_its_link(pg_client, monkeypatch):
    """Someone else's page decides its title: 300 characters used to be a 500."""
    app, make_session, headers = pg_client

    async def long_title(url):
        return OpenGraphMetadata(title="T" * 300, description="d", image_url=None, url=url)

    monkeypatch.setattr("server.app.urls.fetch_opengraph_metadata", long_title)

    response = TestClient(app).post(
        "/api/v1/urls", json={"url": "https://example.com/long"}, headers=headers
    )

    assert response.status_code == 201, response.text
    with make_session() as db:
        # Phase 8.7 — the page's own title, kept apart from the overrides.
        assert db.query(URL).one().page_og_title == "T" * 255


def test_a_long_forwarded_for_still_redirects(pg_client, monkeypatch):
    """Behind a trusted proxy, X-Forwarded-For isn't an address the client can't shape."""
    from server.core.config import settings
    from server.utils.domain import get_or_create_default_domain

    app, make_session, _ = pg_client
    monkeypatch.setattr(settings, "trusted_proxies", ["172.31.0.0/16"])
    with make_session() as db:
        owner = db.query(User).one()
        db.add(
            URL(
                short_code="pglong",
                original_url="https://example.com",
                url_type=URLType.STANDARD,
                domain_id=get_or_create_default_domain(db).id,
                created_by=owner.id,
            )
        )
        db.commit()

    behind_the_alb = TestClient(app, client=("172.31.0.10", 50000))
    response = behind_the_alb.get(
        "/pglong", headers={"x-forwarded-for": "x" * 80}, follow_redirects=False
    )

    assert response.status_code == 302
