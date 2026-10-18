"""
Phase 8.7 — a link's social preview: the destination's own, unless a person rewrote it.

Two layers per link (server/core/models/url.py). `og_title`, `og_description` and `og_image_url`
hold only what a person typed: the overrides. The `page_*` columns cache what the page declares,
its icon included, from the last fetch. Each field's effective value is the override, else the
page's. A link has a custom preview when at least one override is set: then a social crawler gets
Shurly's preview page; without one, the same redirect as a person, to read the page's own tags.
"""

import logging
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime, timezone

import anyio
import anyio.from_thread
from sqlalchemy import inspect
from sqlalchemy.orm import Session

from server.core.models import URL
from server.utils.columns import fit
from server.utils.opengraph import OpenGraphMetadata, fetch_opengraph_metadata

logger = logging.getLogger(__name__)

# The fields a person can override, each with the page_* column it rewrites.
OVERRIDES = {
    "og_title": "page_og_title",
    "og_description": "page_og_description",
    "og_image_url": "page_og_image_url",
}


def _clean(value: str | None) -> str | None:
    """A page's value as a column keeps it: no NUL (PostgreSQL can't hold one), None for blank."""
    if value is None:
        return None
    value = value.replace("\x00", "").strip()
    return value or None


def store_page_preview(url: URL, metadata: OpenGraphMetadata, now: datetime | None = None) -> bool:
    """
    Cache what the page declares on `url`'s page_* columns, all of them, when the page answered
    (`metadata.fetched`): a page that dropped its image drops it here too. A failed fetch leaves
    them as they were. The overrides are never touched. True when stored.
    """
    if not metadata.fetched:
        return False
    url.page_og_title = fit(_clean(metadata.title), URL.page_og_title)
    url.page_og_description = _clean(metadata.description)
    url.page_og_image_url = _clean(metadata.image_url)
    url.page_favicon_url = _clean(metadata.favicon_url)
    url.page_fetched_at = now or datetime.now(timezone.utc)
    return True


# The columns a page's preview fills, as `store_page_preview` writes them.
PAGE_COLUMNS = (
    "page_og_title",
    "page_og_description",
    "page_og_image_url",
    "page_favicon_url",
    "page_fetched_at",
)

# Links updated per statement: well under any database's bound-parameter limit.
_UPDATE_BATCH = 500


async def _fetch_or_failed(destination: str) -> OpenGraphMetadata:
    """The fetcher's answer, or a failed one: an error here must not fail what called it."""
    try:
        return await fetch_opengraph_metadata(destination)
    except Exception as exc:  # noqa: BLE001 — any failure is just "no preview yet"
        logger.warning("page preview fetch failed: %s", type(exc).__name__)
        return OpenGraphMetadata.failed()


def _fetch_from_sync(destination: str) -> OpenGraphMetadata:
    """
    Run the async fetch from sync code. In an AnyIO worker thread (a sync FastAPI route, a sync
    MCP tool) it runs on the app's own event loop and this thread waits; anywhere else (a script,
    a test calling the function directly) on a short-lived loop of its own.
    """
    try:
        return anyio.from_thread.run(_fetch_or_failed, destination)
    except anyio.NoEventLoopError:
        return anyio.run(_fetch_or_failed, destination)


def store_page_preview_on_links(db: Session, destination: str, links: Sequence[URL]) -> bool:
    """
    Fetch `destination` once and cache its preview on every one of `links`, which all point to
    it (a campaign's links). Then commit. True when stored.

    Call it with the links committed and the session idle: the fetch runs with no transaction
    open, so a slow page holds no database connection or lock. A failed fetch leaves the links
    as they are (no page preview yet; the daily housekeeping refreshes them) and fails nothing.
    """
    # An expired link keeps its primary key in its identity: reading it doesn't touch the database.
    ids = [state.identity[0] for state in map(inspect, links) if state.identity]
    if not ids:
        return False
    metadata = _fetch_from_sync(destination)
    if not metadata.fetched:
        return False

    # The same values for all: computed once, as store_page_preview computes them, then
    # written in a few UPDATEs instead of loading each link.
    template = URL()
    store_page_preview(template, metadata)
    values = {column: getattr(template, column) for column in PAGE_COLUMNS}
    for start in range(0, len(ids), _UPDATE_BATCH):
        batch = ids[start : start + _UPDATE_BATCH]
        db.query(URL).filter(URL.id.in_(batch)).update(values, synchronize_session=False)
    db.commit()
    return True


def clear_page_preview(url: URL) -> None:
    """Forget the page's preview: the link points somewhere else, and that didn't answer."""
    url.page_og_title = url.page_og_description = url.page_og_image_url = None
    url.page_favicon_url = url.page_fetched_at = None


@dataclass(frozen=True)
class Preview:
    """A link's effective preview, and which of its fields a person rewrote."""

    title: str | None
    description: str | None
    image_url: str | None
    favicon_url: str | None
    title_overridden: bool
    description_overridden: bool
    image_url_overridden: bool

    @property
    def has_override(self) -> bool:
        return self.title_overridden or self.description_overridden or self.image_url_overridden


def effective_preview(url: URL) -> Preview:
    """Each field: the override, else the page's."""
    return Preview(
        title=url.og_title or url.page_og_title,
        description=url.og_description or url.page_og_description,
        image_url=url.og_image_url or url.page_og_image_url,
        favicon_url=url.page_favicon_url,
        title_overridden=bool(url.og_title),
        description_overridden=bool(url.og_description),
        image_url_overridden=bool(url.og_image_url),
    )


def blank_to_none(value: str | None) -> str | None:
    """An override typed as blank is no override: the page's value shows (schemas)."""
    if isinstance(value, str) and not value.strip():
        return None
    return value
