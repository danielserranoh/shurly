"""
Daily housekeeping inside the app (server/utils/housekeeping.py).

- The waitlist job deletes the entries whose latest sign-up is more than 12 months old; one at
  exactly 12 months stays.
- The previews job re-fetches the missing or 30-day-old previews, never-fetched first then oldest,
  at most 200 links a run, each distinct destination once. A page that doesn't answer leaves its
  link as it was.
- A run skips everything when another task holds the lock; one job failing doesn't stop the other.
- Each run logs `housekeeping.run` with counts only.
- The lifespan starts the loop, and cancels it at shutdown, but not under TESTING.
"""

import asyncio
import contextlib
import uuid
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

import main
from server.core.models import URL, User, WaitlistEntry
from server.utils import housekeeping
from server.utils.domain import get_or_create_default_domain
from server.utils.opengraph import OpenGraphMetadata
from tests.conftest import TestingSessionLocal

NOW = datetime(2026, 10, 18, 12, 0, tzinfo=timezone.utc)
NAIVE_NOW = NOW.replace(tzinfo=None)


def clock() -> datetime:
    return NOW


class FakeFetcher:
    """Every page answers with a title, unless it's in `down`; records what it was asked."""

    def __init__(self, down=(), raises=False):
        self.down = set(down)
        self.raises = raises
        self.asked: list[list[str]] = []

    async def __call__(self, urls: list[str]) -> dict[str, OpenGraphMetadata]:
        self.asked.append(list(urls))
        if self.raises:
            raise RuntimeError("the network is down")
        return {
            url: OpenGraphMetadata.failed()
            if url in self.down
            else OpenGraphMetadata(title=f"Title of {url}")
            for url in urls
        }


@contextlib.contextmanager
def lock_got():
    yield True


@contextlib.contextmanager
def lock_held():
    yield False


@pytest.fixture
def events(monkeypatch) -> list[tuple[str, dict]]:
    logged: list[tuple[str, dict]] = []
    monkeypatch.setattr(
        housekeeping, "log_event", lambda event, **fields: logged.append((event, fields))
    )
    return logged


@pytest.fixture
def owner(db_session) -> User:
    user = User(email="owner@example.com", password_hash="x", is_active=True)
    db_session.add(user)
    db_session.commit()
    return user


def add_waitlist(db, consent_at: datetime) -> WaitlistEntry:
    entry = WaitlistEntry(
        email=f"{uuid.uuid4().hex}@example.com",
        name="Jane Doe",
        kind="individual",
        consent_at=consent_at,
    )
    db.add(entry)
    db.commit()
    return entry


def add_link(db, owner, original_url, fetched_at=None, created_at=None) -> URL:
    url = URL(
        short_code=uuid.uuid4().hex[:8],
        original_url=original_url,
        domain_id=get_or_create_default_domain(db).id,
        created_by=owner.id,
        page_fetched_at=fetched_at,
        created_at=created_at or NAIVE_NOW,
    )
    db.add(url)
    db.commit()
    return url


def run(**kwargs) -> dict:
    kwargs.setdefault("now", clock)
    kwargs.setdefault("fetch", FakeFetcher())
    kwargs.setdefault("lock", lock_got)
    kwargs.setdefault("factory", TestingSessionLocal)
    return housekeeping.run_housekeeping(**kwargs)


# --- The waitlist ---------------------------------------------------------------------------


def test_waitlist_deletes_entries_older_than_twelve_months(db_session, events):
    a_year_ago = datetime(2025, 10, 18, 12, 0)
    kept_at_boundary = add_waitlist(db_session, a_year_ago)
    kept_recent = add_waitlist(db_session, NAIVE_NOW - timedelta(days=30))
    add_waitlist(db_session, a_year_ago - timedelta(seconds=1))
    add_waitlist(db_session, a_year_ago - timedelta(days=400))
    kept_ids = {kept_at_boundary.id, kept_recent.id}

    counts = run()

    db_session.expire_all()
    assert {entry.id for entry in db_session.query(WaitlistEntry).all()} == kept_ids
    assert counts["waitlist_deleted"] == 2


def test_a_year_before_the_29th_of_february_is_the_28th():
    leap = datetime(2028, 2, 29, 9, 30, tzinfo=timezone.utc)
    assert housekeeping._a_year_before(leap) == datetime(2027, 2, 28, 9, 30, tzinfo=timezone.utc)


def test_waitlist_cutoff_is_naive_utc_whatever_the_clocks_zone(db_session):
    madrid = timezone(timedelta(hours=2))
    add_waitlist(db_session, datetime(2025, 10, 18, 11, 59))  # 13:59 in Madrid, a year ago
    deleted = housekeeping.purge_waitlist(db_session, NOW.astimezone(madrid))
    assert deleted == 1


# --- The previews ---------------------------------------------------------------------------


def test_previews_pick_missing_and_old_ones_never_fetched_first_then_oldest(db_session, owner):
    fresh = add_link(db_session, owner, "https://fresh.example/", NOW - timedelta(days=29))
    old = add_link(db_session, owner, "https://old.example/", NOW - timedelta(days=31))
    older = add_link(db_session, owner, "https://older.example/", NOW - timedelta(days=90))
    never_late = add_link(
        db_session, owner, "https://never-late.example/", created_at=NAIVE_NOW - timedelta(days=1)
    )
    never_early = add_link(
        db_session, owner, "https://never-early.example/", created_at=NAIVE_NOW - timedelta(days=5)
    )

    picked = housekeeping.stale_links(db_session, NOW)

    assert [link_id for link_id, _ in picked] == [never_early.id, never_late.id, older.id, old.id]
    assert fresh.id not in {link_id for link_id, _ in picked}
    assert [link_id for link_id, _ in housekeeping.stale_links(db_session, NOW, limit=3)] == [
        never_early.id,
        never_late.id,
        older.id,
    ]


def test_previews_refresh_at_most_200_links_a_run(db_session, owner):
    domain_id = get_or_create_default_domain(db_session).id
    db_session.add_all(
        URL(
            short_code=f"l{n:04d}",
            original_url=f"https://example.com/{n}",
            domain_id=domain_id,
            created_by=owner.id,
            created_at=NAIVE_NOW - timedelta(days=1000 - n),
        )
        for n in range(205)
    )
    db_session.commit()
    fetcher = FakeFetcher()

    counts = run(fetch=fetcher)

    assert counts["previews_checked"] == 200
    assert counts["previews_refreshed"] == 200
    assert len(fetcher.asked[0]) == 200
    # The oldest 200: the five made last wait for tomorrow.
    db_session.expire_all()
    waiting = db_session.query(URL).filter(URL.page_fetched_at.is_(None)).all()
    assert sorted(url.short_code for url in waiting) == [f"l{n:04d}" for n in range(200, 205)]


def test_previews_fetch_each_destination_once_and_store_it_on_every_link(db_session, owner):
    shared = "https://example.com/campaign"
    links = [add_link(db_session, owner, shared) for _ in range(3)]
    other = add_link(db_session, owner, "https://example.org/")
    fetcher = FakeFetcher()

    counts = run(fetch=fetcher)

    assert fetcher.asked == [sorted([shared, "https://example.org/"])]
    db_session.expire_all()
    for link in [*links, other]:
        stored = db_session.get(URL, link.id)
        assert stored.page_og_title == f"Title of {stored.original_url}"
        assert stored.page_fetched_at is not None
    assert counts == counts | {
        "previews_checked": 4,
        "previews_refreshed": 4,
        "previews_failed": 0,
    }


def test_a_page_that_doesnt_answer_leaves_its_link_as_it_was(db_session, owner):
    stale_at = NOW - timedelta(days=60)
    down = add_link(db_session, owner, "https://down.example/", stale_at)
    up = add_link(db_session, owner, "https://up.example/", stale_at)

    counts = run(fetch=FakeFetcher(down={"https://down.example/"}))

    db_session.expire_all()
    assert db_session.get(URL, down.id).page_og_title is None
    assert db_session.get(URL, down.id).page_fetched_at.replace(tzinfo=None) == stale_at.replace(
        tzinfo=None
    )
    assert db_session.get(URL, up.id).page_og_title == "Title of https://up.example/"
    assert counts["previews_refreshed"] == 1
    assert counts["previews_failed"] == 1


def test_no_stale_preview_fetches_nothing(db_session, owner):
    add_link(db_session, owner, "https://fresh.example/", NOW - timedelta(days=1))
    fetcher = FakeFetcher()

    counts = run(fetch=fetcher)

    assert fetcher.asked == []
    assert counts["previews_checked"] == 0


def test_no_transaction_is_open_while_the_pages_are_fetched(db_session, owner, monkeypatch):
    add_link(db_session, owner, "https://example.com/")
    sessions: list = []

    def factory():
        session = TestingSessionLocal()
        sessions.append(session)
        return session

    in_transaction_during_fetch: list[bool] = []

    async def fetch(urls):
        in_transaction_during_fetch.extend(session.in_transaction() for session in sessions)
        return {url: OpenGraphMetadata(title="T") for url in urls}

    housekeeping.refresh_previews(factory, NOW, fetch)

    assert in_transaction_during_fetch and not any(in_transaction_during_fetch)


# --- The run: lock, isolation, log ----------------------------------------------------------


def test_a_held_lock_skips_the_run(db_session, owner, events):
    old_entry = add_waitlist(db_session, datetime(2020, 1, 1))
    add_link(db_session, owner, "https://example.com/")
    fetcher = FakeFetcher()

    counts = run(fetch=fetcher, lock=lock_held)

    assert counts["skipped_lock"] is True
    assert fetcher.asked == []
    db_session.expire_all()
    assert db_session.get(WaitlistEntry, old_entry.id) is not None
    assert events[-1][0] == "housekeeping.run"
    assert events[-1][1]["skipped_lock"] is True


def test_the_advisory_lock(db_session):
    """Off PostgreSQL it's always got; on it (TEST_SUITE_ON_POSTGRES), one task at a time."""
    bind = db_session.get_bind()
    key = {"key": housekeeping._HOUSEKEEPING_LOCK}

    def another_task_gets_it() -> bool:
        with bind.connect() as other:
            got = other.execute(text("SELECT pg_try_advisory_lock(:key)"), key).scalar()
            if got:
                other.execute(text("SELECT pg_advisory_unlock(:key)"), key)
            other.commit()
            return got

    with housekeeping.advisory_lock(TestingSessionLocal) as got:
        assert got is True
        if bind.dialect.name == "postgresql":
            assert another_task_gets_it() is False
            with housekeeping.advisory_lock(TestingSessionLocal) as second:
                assert second is False
    if bind.dialect.name == "postgresql":
        assert another_task_gets_it() is True


def test_a_failing_waitlist_job_doesnt_stop_the_previews(db_session, owner, monkeypatch, events):
    def broken(*_args):
        raise RuntimeError("boom")

    monkeypatch.setattr(housekeeping, "purge_waitlist", broken)
    link = add_link(db_session, owner, "https://example.com/")

    counts = run()

    db_session.expire_all()
    assert db_session.get(URL, link.id).page_og_title == "Title of https://example.com/"
    assert counts["failed_jobs"] == ["waitlist"]
    assert ("housekeeping.job_failed", {"job": "waitlist", "error": "RuntimeError"}) in events


def test_a_failing_previews_job_doesnt_stop_the_waitlist(db_session, owner, events):
    add_waitlist(db_session, datetime(2020, 1, 1))
    add_link(db_session, owner, "https://example.com/")

    counts = run(fetch=FakeFetcher(raises=True))

    db_session.expire_all()
    assert db_session.query(WaitlistEntry).count() == 0
    assert counts["waitlist_deleted"] == 1
    assert counts["failed_jobs"] == ["previews"]


def test_the_run_logs_counts_only(db_session, owner, events):
    add_waitlist(db_session, datetime(2020, 1, 1))
    add_link(db_session, owner, "https://example.com/private?email=jane.doe@example.com")

    run()

    name, fields = events[-1]
    assert name == "housekeeping.run"
    assert set(fields) == {
        "waitlist_deleted",
        "previews_checked",
        "previews_refreshed",
        "previews_failed",
        "skipped_lock",
        "failed_jobs",
        "duration_ms",
    }
    assert fields["waitlist_deleted"] == 1
    assert fields["previews_refreshed"] == 1
    assert "example.com" not in repr(events)


# --- The loop -------------------------------------------------------------------------------


def test_the_loop_waits_then_runs_once_a_day_and_survives_a_failed_run(events):
    slept: list[float] = []
    runs: list[int] = []

    async def sleep(seconds):
        slept.append(seconds)
        if len(slept) > 3:
            raise asyncio.CancelledError

    def flaky_run():
        runs.append(1)
        if len(runs) == 1:
            raise RuntimeError("database away")

    with pytest.raises(asyncio.CancelledError):
        asyncio.run(housekeeping._loop(300, 86400, sleep=sleep, run=flaky_run))

    assert slept == [300, 86400, 86400, 86400]
    assert len(runs) == 3
    assert ("housekeeping.failed", {"error": "RuntimeError"}) in events


def test_the_defaults_wait_a_few_minutes_then_a_day():
    assert 60 <= housekeeping.FIRST_RUN_DELAY <= 15 * 60
    assert housekeeping.INTERVAL == 24 * 60 * 60
    assert housekeeping.PREVIEW_LIMIT == 200


def test_the_loop_isnt_started_under_testing(monkeypatch):
    started: list = []
    monkeypatch.setattr(housekeeping, "start", lambda *a, **k: started.append(1))

    with TestClient(main.create_app()):
        pass

    assert started == []


def test_the_lifespan_starts_the_loop_and_cancels_it_at_shutdown(monkeypatch):
    monkeypatch.delenv("TESTING")
    monkeypatch.setattr(main, "_seed_database", lambda: None)
    monkeypatch.setattr("server.utils.geo.open_database", lambda: None)
    tasks: list[asyncio.Task] = []
    real_start = housekeeping.start

    def start(*_args, **_kwargs):
        task = real_start(first_delay=3600)  # never reaches a run within the test
        tasks.append(task)
        return task

    monkeypatch.setattr(housekeeping, "start", start)

    with TestClient(main.create_app()):
        assert len(tasks) == 1
        assert not tasks[0].done()

    assert tasks[0].cancelled()
