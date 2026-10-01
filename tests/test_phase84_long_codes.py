"""
Phase 8.4 — a short code can be up to 64 characters. Shlink's go.griddo.io has 57 links with
codes longer than 20, the longest 44: personalized outreach links, out there already, which must
keep working exactly as they are. The import stopped on them in production's dry run (2026-10-01).

- MAX_SHORT_CODE_LENGTH is 64, and so are the columns that keep a code, `urls.short_code` and
  `visits.short_code`: migration 0013 widens them, and its downgrade narrows them back.
- A custom code of up to 64 characters is created and redirects; 65 is refused, with a message
  that says 64. Generated codes stay 6 characters. The MCP's `create_custom_url` forwards to the
  same route (tests/test_phase84_long_codes_mcp.py).
- The import takes a 44-character code (tests/test_phase84_shlink_import.py), and "Typos & broken
  links" looks for codes that long (tests/test_orphan_groups.py).
"""

import pytest
from alembic import command
from sqlalchemy import inspect
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session

from server.app import urls as urls_module
from server.core.migrations import alembic_config, run_migrations
from server.core.models import URL, URLType, User, Visitor
from server.utils.opengraph import OpenGraphMetadata
from server.utils.url import MAX_SHORT_CODE_LENGTH

LONG = "jane-doe-acme-corp-2026-q4-outreach-followup"  # 44 characters, as Shlink's longest


@pytest.fixture
def no_og_fetch(monkeypatch):
    """Creating a link fetches its preview: never over the network in tests."""

    async def _empty(*_args, **_kwargs):
        return OpenGraphMetadata()

    monkeypatch.setattr(urls_module, "fetch_opengraph_metadata", _empty)


def _custom(client, headers, code: str):
    return client.post(
        "/api/v1/urls/custom",
        json={"url": "https://example.com/outreach", "custom_code": code},
        headers=headers,
    )


def test_the_limit_is_64_and_the_columns_keep_it():
    assert len(LONG) == 44
    assert MAX_SHORT_CODE_LENGTH == 64
    assert URL.__table__.c.short_code.type.length == MAX_SHORT_CODE_LENGTH
    assert Visitor.__table__.c.short_code.type.length == MAX_SHORT_CODE_LENGTH


class TestCustomCodes:
    def test_a_44_character_code_is_created_and_redirects(
        self, client, auth_headers, db_session, no_og_fetch
    ):
        response = _custom(client, auth_headers, LONG)

        assert response.status_code == 201, response.text
        assert response.json()["short_code"] == LONG
        hit = client.get(f"/{LONG}", follow_redirects=False)
        assert (hit.status_code, hit.headers["location"]) == (302, "https://example.com/outreach")
        assert db_session.query(Visitor.short_code).scalar() == LONG

    def test_64_is_the_longest(self, client, auth_headers, no_og_fetch):
        longest = _custom(client, auth_headers, "a" * 64)
        too_long = _custom(client, auth_headers, "a" * 65)

        assert longest.status_code == 201, longest.text
        assert too_long.status_code == 400
        assert "3-64 characters" in too_long.json()["detail"]

    def test_generated_codes_stay_6_characters(self, client, auth_headers, no_og_fetch):
        response = client.post(
            "/api/v1/urls", json={"url": "https://example.com/"}, headers=auth_headers
        )

        assert response.status_code == 201, response.text
        assert len(response.json()["short_code"]) == 6


def _code_lengths(engine) -> dict[str, int]:
    lengths = {}
    for table in ("urls", "visits"):
        (column,) = [c for c in inspect(engine).get_columns(table) if c["name"] == "short_code"]
        lengths[table] = column["type"].length
    return lengths


def _downgrade_to_0012(engine) -> None:
    config = alembic_config()
    with engine.begin() as conn:
        config.attributes["connection"] = conn
        command.downgrade(config, "0012")


class TestMigration0013:
    """On PostgreSQL, which keeps a VARCHAR's length (TEST_DATABASE_URL)."""

    def test_it_widens_both_columns_and_its_downgrade_narrows_them(self, pg_engine):
        run_migrations(pg_engine)
        assert _code_lengths(pg_engine) == {"urls": 64, "visits": 64}

        _downgrade_to_0012(pg_engine)

        assert _code_lengths(pg_engine) == {"urls": 20, "visits": 20}

    def test_the_downgrade_never_cuts_a_longer_code(self, pg_engine):
        run_migrations(pg_engine)
        with Session(pg_engine) as db:
            user = User(email="owner@griddo.io", password_hash="x", is_active=True)
            db.add(user)
            db.flush()
            db.add(
                URL(
                    short_code=LONG,
                    original_url="https://example.com/outreach",
                    url_type=URLType.STANDARD,
                    created_by=user.id,
                )
            )
            db.commit()

        with pytest.raises(DBAPIError):
            _downgrade_to_0012(pg_engine)

        assert _code_lengths(pg_engine) == {"urls": 64, "visits": 64}
