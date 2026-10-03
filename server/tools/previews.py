"""
Phase 8.7 — previews from the page, for the links made before them.

`backfill` fetches every link's destination, each distinct URL once (exact match), a few at a time,
and caches what the page declares on every link with that URL (the `page_*` columns, its icon
included), as creating a link does now. The links imported from Shlink, which never fetched, get
their previews this way.

It also separates the old values. Before 8.7, a link's og_* held the page's preview, copied at
create when nobody typed one (and `og_fetched_at` set), or what a person typed. So for a link whose
`og_fetched_at` is set, each og_* value that equals the page's, fetched now, was a copy: it's
cleared, and the page's shows through. One that differs stays an override: nobody's typed text is
lost, and the link's page can go back to the page's preview. A link without `og_fetched_at` keeps
its og_* as overrides. A link done this way has its `og_fetched_at` cleared, so a second run
refreshes the page's values and clears nothing new. A page that doesn't answer leaves its links
as they were, to a later run.

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
from urllib.parse import urljoin

from server.core import SessionLocal
from server.core.models import URL
from server.utils.opengraph import OpenGraphMetadata, fetch_opengraph_metadata
from server.utils.previews import OVERRIDES, store_page_preview

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


def _was_copied(url: URL, field: str) -> bool:
    """The og_* value equals what the page declares now: a copy of the page's, not typed."""
    value = getattr(url, field).strip()
    page = getattr(url, OVERRIDES[field])
    if page is None:
        return False
    if field == "og_image_url":
        # Before 8.7 an og:image was copied as written, relative or not; now it's resolved.
        value = urljoin(url.original_url, value)
    return value == page.strip()


def apply(db, pages: dict[str, OpenGraphMetadata], now: datetime) -> Counter:
    """Cache each link's page and separate its old values; what was done, counted."""
    counts: Counter = Counter()
    for url in db.query(URL).filter(URL.original_url.in_(list(pages))).all():
        metadata = pages[url.original_url]
        if not store_page_preview(url, metadata, now):
            counts["links_unanswered"] += 1
            continue
        counts["links_done"] += 1
        copied = url.og_fetched_at is not None
        for field in OVERRIDES:
            if getattr(url, field) is None:
                continue
            if copied and _was_copied(url, field):
                setattr(url, field, None)
                counts["overrides_cleared"] += 1
            else:
                counts["overrides_kept"] += 1
        url.og_fetched_at = None
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
        f"Previews cached on {counts['links_done']} links. Overrides: "
        f"{counts['overrides_cleared']} cleared (copies of the page's), "
        f"{counts['overrides_kept']} kept.",
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
    backfilling = commands.add_parser(
        "backfill", help="fetch every link's page preview and icon, and separate the old values"
    )
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
