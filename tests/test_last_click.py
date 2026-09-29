"""
A link's `last_click_at` is its latest click, as `/totals` counts one (Phase 3.16): not a bot's
visit, not an email open, not a crawler's preview and not a `?nostat` hit. The dashboard shows
it ("Last … ago", else "No clicks yet"). It used to move on every visit the redirect logged,
and the Shlink import counted Shlink's potential bots. Migration 0010 repairs what's stored.
"""

import uuid
from datetime import datetime, timezone

import pytest
from sqlalchemy import event

from server.core.models import URL, User, Visitor
from server.utils.domain import get_or_create_default_domain
from tests.test_phase84_shlink_import import (  # noqa: F401 — `owner` is the importer's fixture
    owner,
    run,
    short_url,
    visit,
)


@pytest.fixture
def link(db_session, test_user) -> URL:
    url = URL(
        short_code="lc1",
        original_url="https://example.com",
        created_by=test_user.id,
        domain_id=get_or_create_default_domain(db_session).id,
    )
    db_session.add(url)
    db_session.commit()
    return url


def _last_click(db_session, url: URL):
    db_session.refresh(url)
    return url.last_click_at


class TestTheRedirect:
    def test_a_click_sets_it_to_the_visits_time(self, client, db_session, link):
        client.get("/lc1", follow_redirects=False)

        (logged,) = db_session.query(Visitor).all()
        assert _last_click(db_session, link).replace(tzinfo=None) == logged.visited_at

    @pytest.mark.parametrize(
        "path, user_agent",
        [
            ("/lc1", "curl/8.7.1"),  # a bot's visit, logged as one
            ("/lc1", "LinkedInBot/1.0"),  # a crawler's preview, not logged
            ("/lc1?nostat", "Mozilla/5.0"),  # a QA hit, not logged
            ("/lc1/track", "Mozilla/5.0"),  # an email open
        ],
    )
    def test_nothing_else_does(self, client, db_session, link, path, user_agent):
        """Nor writes to the link: it used to set it on every hit, and roll it back unsaved."""
        statements = []

        def capture(conn, cursor, statement, *args):
            statements.append(statement.lstrip().upper())

        engine = db_session.get_bind()
        event.listen(engine, "before_cursor_execute", capture)
        try:
            client.get(path, headers={"user-agent": user_agent}, follow_redirects=False)
        finally:
            event.remove(engine, "before_cursor_execute", capture)

        assert not [s for s in statements if s.startswith("UPDATE URLS")]
        assert _last_click(db_session, link) is None


class TestTheImport:
    def test_the_latest_click_neither_a_later_bot_nor_an_open(self, db_session, owner):  # noqa: F811
        clicked = [
            visit("2025-03-02T10:00:00+00:00"),
            {**visit("2025-03-04T10:00:00+00:00"), "potentialBot": True},
            {**visit("2025-03-05T10:00:00+00:00"), "redirectUrl": None},  # the pixel
        ]
        bots_only = [{**visit("2025-03-04T10:00:00+00:00"), "potentialBot": True}]

        run(
            db_session,
            owner,
            {"short_url": short_url("clicked"), "visits": clicked},
            {"short_url": short_url("bots"), "visits": bots_only},
            visits=True,
        )
        db_session.commit()

        last = {url.short_code: url.last_click_at for url in db_session.query(URL)}
        assert last["clicked"].replace(tzinfo=None) == datetime(2025, 3, 2, 10, 0)
        assert last["bots"] is None


def test_migration_0010_repairs_what_is_stored(pg_engine):
    """
    Each link's latest click, or NULL. Read as UTC whatever the session's zone: `visited_at`
    is naive UTC, `last_click_at` a timestamptz.
    """
    from alembic import command
    from sqlalchemy import text
    from sqlalchemy.orm import Session

    from server.core.migrations import alembic_config

    config = alembic_config()
    with pg_engine.begin() as conn:
        config.attributes["connection"] = conn
        command.upgrade(config, "0009")
        db = Session(bind=conn)
        user = User(email="owner@griddo.io", password_hash="x", is_active=True)
        db.add(user)
        db.flush()
        domain = get_or_create_default_domain(db)
        stale = datetime(2026, 9, 28, 12, 0, tzinfo=timezone.utc)
        links = {
            code: URL(
                short_code=code,
                original_url="https://example.com",
                created_by=user.id,
                domain_id=domain.id,
                last_click_at=stale,
            )
            for code in ("clicked", "bots", "none")
        }
        db.add_all(links.values())
        db.flush()
        for code, at, flags in [
            ("clicked", datetime(2026, 9, 20, 8, 30), {}),
            ("clicked", datetime(2026, 9, 21, 9, 45), {}),
            ("clicked", datetime(2026, 9, 27, 7, 0), {"is_bot": True}),
            ("clicked", datetime(2026, 9, 27, 8, 0), {"is_pixel": True}),
            ("bots", datetime(2026, 9, 27, 7, 0), {"is_bot": True}),
        ]:
            # Only the columns 0009 has: the model maps later ones (0011's `city`), which an ORM
            # INSERT would name.
            db.execute(
                Visitor.__table__.insert().values(
                    id=uuid.uuid4(),
                    url_id=links[code].id,
                    short_code=code,
                    ip="203.0.113.0",
                    visited_at=at,
                    is_bot=flags.get("is_bot", False),
                    is_pixel=flags.get("is_pixel", False),
                )
            )
        db.flush()
        conn.execute(text("SET TIME ZONE 'Europe/Madrid'"))

        command.upgrade(config, "0010")

        stored = dict(conn.execute(text("SELECT short_code, last_click_at FROM urls")).all())
    assert stored["clicked"] == datetime(2026, 9, 21, 9, 45, tzinfo=timezone.utc)
    assert stored["bots"] is None
    assert stored["none"] is None
