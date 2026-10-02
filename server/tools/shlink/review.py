"""
Phase 8.4 — review: a snapshot as a CSV, one row per link, for a person to decide
`keep`, `archive` or `drop`. Every row starts as `keep`: a kept link costs a row, while
a dropped one that turns out to be on a poster, a QR code or a PDF breaks for good.

The import reads only `code`, `domain` and `decision` back: the other columns help
decide. `--check-destinations` fills in each destination's HTTP status, fetched through
the link previews' SSRF guard (`guarded_request`, server/utils/opengraph.py).
"""

import asyncio
import csv
import os
from collections import defaultdict
from collections.abc import Iterable
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit

import httpx

from server.tools.shlink.export import check_links, format_gap, visits_state
from server.tools.shlink.mapping import CONDITION_TYPES, is_click
from server.utils.csv_export import spreadsheet_safe
from server.utils.opengraph import FetchRefusedError, guarded_request

COLUMNS = [
    "code",
    "domain",
    "destination",
    "title",
    "tags",
    "created",
    "visits",
    "non_bot_visits",
    "last_visit",
    "visits_export",
    "visits_lost",
    "expired",
    "capped",
    "capped_in_shurly",
    "redirect_rules",
    "rules_to_check",
    "destination_status",
    "duplicate_of",
    "case_collision",
    "decision",
]


def review_rows(
    snapshot: dict, *, statuses: dict[str, str] | None = None, now: datetime | None = None
) -> list[dict]:
    """One row per link. SnapshotError (export.py) for a snapshot that lists a link twice:
    its export wasn't whole (R17)."""
    now = now or datetime.now(timezone.utc)
    statuses = statuses or {}
    links = [entry["short_url"] for entry in snapshot["links"]]
    check_links(links)
    duplicate_of = _duplicates(links)
    collisions = _case_collisions(links)
    rows = []
    for entry in snapshot["links"]:
        link = entry["short_url"]
        meta = link.get("meta") or {}
        visits = link.get("visitsSummary") or {}
        rules = (entry.get("redirect_rules") or {}).get("redirectRules") or []
        key = _key(link)
        rows.append(
            {
                "code": link["shortCode"],
                "domain": key[0],
                "destination": link["longUrl"],
                "title": link.get("title") or "",
                "tags": ", ".join(link.get("tags") or []),
                "created": link.get("dateCreated") or "",
                "visits": visits.get("total", ""),
                "non_bot_visits": visits.get("nonBots", ""),
                "last_visit": _last_visit(entry.get("visits")),
                "visits_export": visits_state(entry),
                "visits_lost": "; ".join(map(format_gap, entry.get("visits_gaps") or [])),
                "expired": "yes" if _is_before(meta.get("validUntil"), now) else "",
                "capped": "yes" if _is_capped(meta.get("maxVisits"), visits.get("total")) else "",
                "capped_in_shurly": (
                    "yes" if _is_capped(meta.get("maxVisits"), _clicks(entry.get("visits"))) else ""
                ),
                "redirect_rules": len(rules),
                "rules_to_check": ", ".join(_conditions_without_equivalent(rules)),
                "destination_status": statuses.get(link["longUrl"], ""),
                "duplicate_of": duplicate_of.get(key, ""),
                "case_collision": ", ".join(collisions.get(key, [])),
                "decision": "keep",
            }
        )
    return rows


def write_review(rows: list[dict], path: Path) -> None:
    """Every cell through `spreadsheet_safe`: titles and destinations come from anyone who
    made a link. Readable by its owner only, and never over an existing sheet, which may
    already hold decisions."""
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(COLUMNS)
        for row in rows:
            writer.writerow([spreadsheet_safe(row[column]) for column in COLUMNS])


async def check_destinations(
    urls: Iterable[str], *, concurrency: int = 8, timeout: float = 5.0
) -> dict[str, str]:
    """Each distinct URL's HTTP status, at most `concurrency` at a time."""
    limit = asyncio.Semaphore(concurrency)

    async def check(url: str) -> tuple[str, str]:
        async with limit:
            return url, await _status(url, timeout)

    return dict(await asyncio.gather(*(check(url) for url in dict.fromkeys(urls))))


async def _status(url: str, timeout: float) -> str:
    """The final status after redirects: HEAD, or GET where a server refuses HEAD."""
    try:
        response = await guarded_request("HEAD", url, timeout)
        if response.status_code in (405, 501):
            response = await guarded_request("GET", url, timeout)
    except FetchRefusedError as refused:
        return f"refused: {refused}"
    except (httpx.TimeoutException, asyncio.TimeoutError):  # not TimeoutError before 3.11
        return "timeout"
    except (httpx.HTTPError, httpx.InvalidURL, OSError) as error:
        return f"error: {type(error).__name__}"
    return str(response.status_code)


def _key(link: dict) -> tuple[str, str]:
    """(domain, code). `shortUrl` names the host even for Shlink's default domain."""
    return (urlsplit(link["shortUrl"]).hostname or "", link["shortCode"])


def _parse(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        # Python 3.10's fromisoformat doesn't read a "Z" suffix.
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def _is_before(value: str | None, now: datetime) -> bool:
    moment = _parse(value)
    return moment is not None and moment < now


def _is_capped(max_visits: int | None, visits: int | None) -> bool:
    return max_visits is not None and visits is not None and visits >= max_visits


def _clicks(visits: list[dict] | None) -> int:
    """What Shurly's click limit counts once an import with `--visits` brings them: Shlink's cap
    counted every visit. None in the snapshot, none imported: the link keeps its whole limit."""
    return sum(map(is_click, visits or []))


def _last_visit(visits: list[dict] | None) -> str:
    dated = [(_parse(visit.get("date")), visit.get("date")) for visit in visits or []]
    dated = [(moment, raw) for moment, raw in dated if moment is not None]
    return max(dated)[1] if dated else ""


def _conditions_without_equivalent(rules: list[dict]) -> list[str]:
    types = {condition.get("type") for rule in rules for condition in rule.get("conditions", [])}
    return sorted(str(kind) for kind in types if CONDITION_TYPES.get(kind) is None)


def _duplicates(links: list[dict]) -> dict[tuple[str, str], str]:
    """Links with the destination of an older one on the same domain → its code."""
    same_destination = defaultdict(list)
    for link in links:
        same_destination[(_key(link)[0], link["longUrl"])].append(link)
    never = datetime.max.replace(tzinfo=timezone.utc)
    duplicate_of = {}
    for group in same_destination.values():
        oldest, *others = sorted(
            group, key=lambda link: (_parse(link.get("dateCreated")) or never, link["shortCode"])
        )
        for link in others:
            duplicate_of[_key(link)] = oldest["shortCode"]
    return duplicate_of


def _case_collisions(links: list[dict]) -> dict[tuple[str, str], list[str]]:
    """Codes on the same domain that differ only in case → the others' codes."""
    same_letters = defaultdict(list)
    for link in links:
        domain, code = _key(link)
        same_letters[(domain, code.lower())].append(code)
    collisions = {}
    for (domain, _), codes in same_letters.items():
        for code in codes:
            if len(codes) > 1:
                collisions[(domain, code)] = [other for other in codes if other != code]
    return collisions
