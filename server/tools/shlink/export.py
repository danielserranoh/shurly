"""
Phase 8.4 — export: every short URL in Shlink's REST API, with its redirect rules and,
if asked, its visits, into one raw JSON snapshot. Read-only, and each API object is kept
exactly as Shlink returned it: the snapshot is the archive, and what the review and the
import work from.

The API key only ever travels in the `X-Api-Key` header: it's never written to the
snapshot, put in its name, or printed.
"""

import json
import os
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import quote, urlsplit

import httpx

FORMAT = "shurly.shlink-snapshot/1"


def shlink_client(
    url: str, api_key: str, transport: httpx.BaseTransport | None = None
) -> httpx.Client:
    options = {"transport": transport} if transport else {}
    return httpx.Client(
        base_url=url.rstrip("/"),
        headers={"X-Api-Key": api_key, "Accept": "application/json"},
        timeout=30,
        **options,
    )


def export_snapshot(
    client: httpx.Client,
    *,
    visits: bool = False,
    page_size: int = 100,
    visits_page_size: int = 1000,
    now: datetime | None = None,
) -> dict:
    """
    One entry per short URL: `short_url` as Shlink returned it; `redirect_rules` for the
    ones that have some; `visits`, every page of them, when `visits` is set. Visits are
    personal data (user agents, referers, locations): see README.md.
    """
    health = _get(client, "/rest/health")
    links = []
    for short_url in _pages(client, "/rest/v3/short-urls", "shortUrls", page_size):
        entry = {"short_url": short_url}
        path = f"/rest/v3/short-urls/{quote(short_url['shortCode'], safe='')}"
        # Shlink identifies a short URL by its code and domain; null is the default domain.
        domain = {"domain": short_url["domain"]} if short_url.get("domain") else {}
        if short_url.get("hasRedirectRules"):
            entry["redirect_rules"] = _get(client, f"{path}/redirect-rules", domain)
        if visits:
            entry["visits"] = list(
                _pages(client, f"{path}/visits", "visits", visits_page_size, domain)
            )
        links.append(entry)
    return {
        "format": FORMAT,
        "exported_at": (now or datetime.now(UTC)).isoformat(),
        "shlink": {"url": str(client.base_url).rstrip("/"), "version": health.get("version")},
        "links": links,
    }


def write_snapshot(snapshot: dict, out_dir: Path, now: datetime | None = None) -> Path:
    """
    `shlink-<host>-<UTC time>.snapshot.json` in `out_dir`, readable by its owner only,
    and never over an existing one.
    """
    host = urlsplit(snapshot["shlink"]["url"]).hostname
    stamp = (now or datetime.now(UTC)).strftime("%Y%m%dT%H%M%SZ")
    path = Path(out_dir) / f"shlink-{host}-{stamp}.snapshot.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "w", encoding="utf-8") as f:
        json.dump(snapshot, f, ensure_ascii=False, indent=1)
    return path


def _get(client: httpx.Client, path: str, params: dict | None = None) -> dict:
    response = client.get(path, params=params)
    response.raise_for_status()
    return response.json()


def _pages(
    client: httpx.Client, path: str, name: str, page_size: int, params: dict | None = None
) -> Iterator[dict]:
    page = 1
    while True:
        body = _get(client, path, {**(params or {}), "page": page, "itemsPerPage": page_size})
        yield from body[name]["data"]
        if page >= body[name]["pagination"]["pagesCount"]:
            return
        page += 1
