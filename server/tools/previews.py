"""
Phase 8.7 — previews from the page, for every link.

`backfill` fetches every link's destination, each distinct URL once (exact match), a few at a time,
and caches what the page declares on every link with that URL (the `page_*` columns, its icon
included), as creating a link does now. The links imported from Shlink, which never fetched, got
their previews this way; a later run refreshes everyone's. The overrides (og_*, what a person
typed) are never touched. A page that doesn't answer leaves its links as they were, to a later run.

    python -m server.tools.previews backfill [--for-real] [--concurrency N]

A dry run unless --for-real: everything is fetched and worked out, and nothing written. The
fetches happen outside any transaction; the writes, in one, at the end, on the links as they are
then (one whose destination changed meanwhile is skipped). What it prints are counts, never a
destination: a URL's path and query can carry personal data.

In production, as a one-off ECS task: scripts/run_backfill_previews.sh (DEPLOYMENT.md).
"""

import argparse
import asyncio
import sys
from collections import Counter
from datetime import datetime, timezone

from server.core import SessionLocal
from server.core.models import URL
from server.utils.opengraph import OpenGraphMetadata, fetch_opengraph_metadata
from server.utils.previews import store_page_preview

# Tests point these at their database and their fake pages.
session_factory = SessionLocal
fetch = fetch_opengraph_metadata

DEFAULT_CONCURRENCY = 8


async def fetch_all(urls: list[str], concurrency: int) -> dict[str, OpenGraphMetadata]:
    """Each URL's page, `concurrency` at a time."""
    gate = asyncio.Semaphore(concurrency)

    async def one(url: str) -> tuple[str, OpenGraphMetadata]:
        async with gate:
            try:
                return url, await fetch(url)
            except Exception:  # the fetcher swallows its own; this one must not stop the rest
                return url, OpenGraphMetadata.failed()

    return dict(await asyncio.gather(*(one(url) for url in urls)))


def apply(db, pages: dict[str, OpenGraphMetadata], now: datetime) -> Counter:
    """Cache each link's page on it; what was done, counted."""
    counts: Counter = Counter()
    for url in db.query(URL).filter(URL.original_url.in_(list(pages))).all():
        if store_page_preview(url, pages[url.original_url], now):
            counts["links_done"] += 1
        else:
            counts["links_unanswered"] += 1
    return counts


def backfill(db, concurrency: int = DEFAULT_CONCURRENCY, for_real: bool = False) -> Counter:
    """Fetch every link's page and cache it on the link; a dry run rolls back."""
    links = db.query(URL.original_url).all()
    distinct = sorted({original for (original,) in links})
    db.rollback()  # no transaction stays open while the pages are fetched
    pages = asyncio.run(fetch_all(distinct, concurrency))

    counts = apply(db, pages, datetime.now(timezone.utc))
    counts["links"] = len(links)
    counts["urls"] = len(distinct)
    counts["urls_failed"] = sum(not page.fetched for page in pages.values())
    counts["urls_with_preview"] = sum(
        page.fetched and page.has_metadata() for page in pages.values()
    )
    counts["urls_with_icon"] = sum(
        bool(page.fetched and page.favicon_url) for page in pages.values()
    )
    counts["links_skipped"] = (
        counts["links"] - counts["links_done"] - counts["links_unanswered"]
    )  # deleted, or pointed somewhere else, while the pages were fetched
    if for_real:
        db.commit()
    else:
        db.rollback()
    return counts


def report(counts: Counter, for_real: bool) -> list[str]:
    lines = [
        f"{counts['links']} links, {counts['urls']} distinct destinations fetched: "
        f"{counts['urls_with_preview']} with a preview, {counts['urls_with_icon']} with an icon, "
        f"{counts['urls_failed']} that didn't answer.",
        f"Previews cached on {counts['links_done']} links.",
    ]
    if counts["links_unanswered"]:
        lines.append(
            f"{counts['links_unanswered']} links whose page didn't answer are left as they were: "
            "run it again later."
        )
    if counts["links_skipped"]:
        lines.append(f"{counts['links_skipped']} links changed while it ran, and were skipped.")
    if not for_real:
        lines.append("Dry run: nothing was written. --for-real writes it.")
    return lines


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m server.tools.previews")
    commands = parser.add_subparsers(dest="command", required=True)
    backfilling = commands.add_parser("backfill", help="fetch every link's page preview and icon")
    backfilling.add_argument("--for-real", action="store_true", help="write it; without, a dry run")
    backfilling.add_argument(
        "--concurrency",
        type=int,
        default=DEFAULT_CONCURRENCY,
        metavar="N",
        help=f"pages fetched at a time (default {DEFAULT_CONCURRENCY})",
    )
    args = parser.parse_args(argv)
    if args.concurrency < 1:
        backfilling.error("--concurrency must be at least 1")

    with session_factory() as db:
        counts = backfill(db, args.concurrency, args.for_real)
    print("\n".join(report(counts, args.for_real)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
