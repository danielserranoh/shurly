"""
Daily housekeeping, inside the app: a background loop the lifespan starts (main.py).

Its first run is a few minutes after the app starts, so a deploy isn't slowed, then one a day.
Every task runs the loop, each counting from its own start. A PostgreSQL advisory lock, held while a
run lasts, keeps two runs from overlapping (one that finds it held skips); it doesn't stop two tasks
both running on the same day, at different hours, which does no harm: the jobs are idempotent. Each run does its jobs one after the other, each on
its own, so one that fails is logged and the next still runs:

- **waitlist**: deletes the entries whose latest sign-up (`consent_at`) is more than 12 months old
  (docs/PERSONAL_DATA.md § The waitlist).
- **previews**: re-fetches the page previews that are missing or more than 30 days old, at most
  `PREVIEW_LIMIT` links a run, oldest first: each distinct destination once, a few at a time
  (`fetch_all`, server/tools/previews.py), and stored as creating a link does
  (`store_page_preview`). A page that doesn't answer leaves its link as it was.

No transaction stays open while the pages are fetched: the links are read, the session closed,
the pages fetched, then the results written in a new one. Each run logs `housekeeping.run` with
counts only, never a destination or an email.
"""

import asyncio
import contextlib
import time
from collections.abc import Awaitable, Callable, Iterator
from datetime import datetime, timedelta, timezone

from sqlalchemy import case, or_, text

from server.core import SessionLocal
from server.core.models import URL, WaitlistEntry
from server.utils.event_log import log_event
from server.utils.opengraph import OpenGraphMetadata
from server.utils.previews import store_page_preview

FIRST_RUN_DELAY = 5 * 60  # seconds after the app starts
INTERVAL = 24 * 60 * 60  # seconds between runs

PREVIEW_MAX_AGE = timedelta(days=30)
PREVIEW_LIMIT = 200  # links a run
PREVIEW_CONCURRENCY = 8  # pages fetched at a time

# Any fixed number, other than the migrations' (server/core/migrations.py): every task asks
# PostgreSQL for the same advisory lock.
_HOUSEKEEPING_LOCK = 31402

# Tests point this at their database.
session_factory = SessionLocal

Clock = Callable[[], datetime]
FetchPages = Callable[[list[str]], Awaitable[dict[str, OpenGraphMetadata]]]


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


async def fetch_pages(urls: list[str]) -> dict[str, OpenGraphMetadata]:
    """Each URL's page, a few at a time, through the SSRF-guarded fetcher."""
    from server.tools.previews import fetch_all

    return await fetch_all(urls, PREVIEW_CONCURRENCY)


@contextlib.contextmanager
def advisory_lock(factory=None) -> Iterator[bool]:
    """
    Whether this run holds the housekeeping lock: PostgreSQL's `pg_try_advisory_lock`, on a
    connection of its own kept for the run and released at the end. It's the connection's lock,
    not a transaction's, so no transaction stays open meanwhile. Any other database (SQLite, in
    tests) has one process: the lock is always got.
    """
    with (factory or session_factory)() as db:
        bind = db.get_bind()
    if bind.dialect.name != "postgresql":
        yield True
        return
    with bind.connect() as connection:
        params = {"key": _HOUSEKEEPING_LOCK}
        got = bool(connection.execute(text("SELECT pg_try_advisory_lock(:key)"), params).scalar())
        connection.commit()
        try:
            yield got
        finally:
            if got:
                connection.execute(text("SELECT pg_advisory_unlock(:key)"), params)
                connection.commit()


def _a_year_before(moment: datetime) -> datetime:
    """The same moment 12 months earlier; 29 February goes to the 28th."""
    try:
        return moment.replace(year=moment.year - 1)
    except ValueError:
        return moment.replace(year=moment.year - 1, day=28)


def _naive_utc(moment: datetime) -> datetime:
    """As the waitlist's columns hold it: UTC without a zone."""
    if moment.tzinfo is not None:
        moment = moment.astimezone(timezone.utc).replace(tzinfo=None)
    return moment


def purge_waitlist(db, now: datetime) -> int:
    """Delete the entries whose latest sign-up is more than 12 months before `now`; how many."""
    cutoff = _naive_utc(_a_year_before(now))
    deleted = (
        db.query(WaitlistEntry)
        .filter(WaitlistEntry.consent_at < cutoff)
        .delete(synchronize_session=False)
    )
    db.commit()
    return deleted


def stale_links(db, now: datetime, limit: int = PREVIEW_LIMIT) -> list[tuple]:
    """
    `(id, original_url)` of the links whose preview is missing or older than `PREVIEW_MAX_AGE`,
    oldest first (never fetched before any fetched one), at most `limit`.
    """
    cutoff = now - PREVIEW_MAX_AGE
    never_fetched_first = case((URL.page_fetched_at.is_(None), 0), else_=1)
    return [
        (link_id, original)
        for link_id, original in db.query(URL.id, URL.original_url)
        .filter(or_(URL.page_fetched_at.is_(None), URL.page_fetched_at < cutoff))
        .order_by(never_fetched_first, URL.page_fetched_at, URL.created_at, URL.id)
        .limit(limit)
        .all()
    ]


def refresh_previews(factory, now: datetime, fetch: FetchPages) -> dict[str, int]:
    """Re-fetch the stale previews and store them; the links checked, refreshed and failed."""
    with factory() as db:
        links = stale_links(db, now)
    # The session is closed: no transaction while the pages are fetched.
    destinations = sorted({original for _, original in links})
    pages = asyncio.run(fetch(destinations)) if destinations else {}

    refreshed = failed = 0
    if links:
        with factory() as db:
            for url in db.query(URL).filter(URL.id.in_([link_id for link_id, _ in links])).all():
                page = pages.get(url.original_url)
                if page is None:  # pointed somewhere else while the pages were fetched
                    continue
                if store_page_preview(url, page, now):
                    refreshed += 1
                else:
                    failed += 1
            db.commit()
    return {
        "previews_checked": len(links),
        "previews_refreshed": refreshed,
        "previews_failed": failed,
    }


def run_housekeeping(
    *,
    now: Clock = utc_now,
    fetch: FetchPages | None = None,
    lock: Callable[[], contextlib.AbstractContextManager[bool]] | None = None,
    factory=None,
) -> dict:
    """
    One run: both jobs under the lock, or nothing when another task holds it. Synchronous (it
    blocks on the database and runs its own event loop for the fetches): the loop calls it in a
    thread. Returns what it logged.
    """
    factory = factory or session_factory
    fetch = fetch or fetch_pages
    lock = lock or (lambda: advisory_lock(factory))
    started = time.perf_counter()
    counts: dict = {
        "waitlist_deleted": 0,
        "previews_checked": 0,
        "previews_refreshed": 0,
        "previews_failed": 0,
        "skipped_lock": False,
    }
    failed_jobs: list[str] = []

    with lock() as got:
        if not got:
            counts["skipped_lock"] = True
        else:
            moment = now()

            def waitlist() -> None:
                with factory() as db:
                    counts["waitlist_deleted"] = purge_waitlist(db, moment)

            def previews() -> None:
                counts.update(refresh_previews(factory, moment, fetch))

            for name, job in (("waitlist", waitlist), ("previews", previews)):
                try:
                    job()
                except Exception as exc:  # one job failing mustn't stop the next
                    failed_jobs.append(name)
                    # The class only: a message can carry a destination or a statement's values.
                    log_event("housekeeping.job_failed", job=name, error=type(exc).__name__)

    counts["failed_jobs"] = failed_jobs
    counts["duration_ms"] = round((time.perf_counter() - started) * 1000, 1)
    log_event("housekeeping.run", **counts)
    return counts


async def _loop(first_delay: float, interval: float, sleep=asyncio.sleep, run=None) -> None:
    run = run or run_housekeeping
    await sleep(first_delay)
    while True:
        try:
            await asyncio.to_thread(run)
        except Exception as exc:  # the lock itself, say: the loop goes on, to tomorrow's run
            log_event("housekeeping.failed", error=type(exc).__name__)
        await sleep(interval)


def start(first_delay: float = FIRST_RUN_DELAY, interval: float = INTERVAL) -> asyncio.Task:
    """Start the loop on the running event loop; `stop` cancels it."""
    return asyncio.create_task(_loop(first_delay, interval), name="housekeeping")


async def stop(task: asyncio.Task) -> None:
    """Cancel the loop and wait for it. A run in its thread finishes on its own."""
    task.cancel()
    with contextlib.suppress(asyncio.CancelledError):
        await task
