"""
Phase 8.4 — export: every short URL in Shlink's REST API, with its redirect rules and,
if asked, its visits, into one raw JSON snapshot. Read-only, and each API object is kept
exactly as Shlink returned it: the snapshot is the archive, and what the review and the
import work from.

Shlink can fail on one link's visits alone: production's answers 500 for a few links,
whatever the parameters, most likely over one visit it can't serialize. A 5xx is retried;
if it persists, the export records the failure on that link and recovers what it can of
its visits by date range (`_recover`), then carries on. Every other failure stops it.

The API key only ever travels in the `X-Api-Key` header: it's never written to the
snapshot, put in its name, or printed.
"""

import json
import os
import time
from collections.abc import Callable, Iterator
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote, urlsplit

import httpx

FORMAT = "shurly.shlink-snapshot/1"

# A 5xx is asked again this many times, after BACKOFF seconds, then twice that.
RETRIES = 2
BACKOFF = 0.5
# The requests one link's recovery may make before what's left becomes a gap.
RECOVERY_REQUESTS = 600
# Where a recovery's date ranges start: before any link Shlink can hold.
EARLIEST = datetime(1970, 1, 1, tzinfo=timezone.utc)

Get = Callable[[str, dict | None], dict]


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
    retries: int = RETRIES,
    backoff: float = BACKOFF,
    sleep: Callable[[float], None] | None = None,
    recovery_requests: int = RECOVERY_REQUESTS,
    clock: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
    progress: Callable[[str], None] = lambda message: None,
) -> dict:
    """
    One entry per short URL: `short_url` as Shlink returned it; `redirect_rules` for the
    ones that have some; `visits`, every page of them, when `visits` is set. Visits are
    personal data (user agents, referers, locations): see README.md.

    A link whose visits Shlink keeps answering 5xx to gets `visits_error` (the status and
    Shlink's detail), the visits recovered by date range in `visits`, and the ranges that
    stayed out in `visits_gaps`; its code goes in the snapshot's `visits_failed`.
    """
    get = _retrying(client, retries, backoff, sleep or time.sleep)
    health = get("/rest/health", None)
    links, failed = [], []
    for short_url in _pages(get, "/rest/v3/short-urls", "shortUrls", page_size):
        entry = {"short_url": short_url}
        code = short_url["shortCode"]
        path = f"/rest/v3/short-urls/{quote(code, safe='')}"
        # Shlink identifies a short URL by its code and domain; null is the default domain.
        domain = {"domain": short_url["domain"]} if short_url.get("domain") else {}
        if short_url.get("hasRedirectRules"):
            entry["redirect_rules"] = get(f"{path}/redirect-rules", domain)
        if visits:
            try:
                entry["visits"] = list(
                    _pages(get, f"{path}/visits", "visits", visits_page_size, domain)
                )
            except httpx.HTTPStatusError as error:
                if not _is_5xx(error):
                    raise
                status = error.response.status_code
                progress(
                    f"{code}: Shlink answered {status} to its visits; recovering them by date…"
                )
                entry["visits_error"] = {"status": status, "detail": _detail(error.response)}
                found, gaps = _recover(
                    get,
                    f"{path}/visits",
                    domain,
                    page_size=visits_page_size,
                    budget=recovery_requests,
                    until=clock(),
                    expected=(short_url.get("visitsSummary") or {}).get("total"),
                )
                entry["visits"], entry["visits_gaps"] = found, gaps
                failed.append(code)
        links.append(entry)
    snapshot = {
        "format": FORMAT,
        "exported_at": (now or datetime.now(timezone.utc)).isoformat(),
        "shlink": {"url": str(client.base_url).rstrip("/"), "version": health.get("version")},
        "links": links,
    }
    if visits:
        snapshot["visits_failed"] = failed
    return snapshot


def write_snapshot(snapshot: dict, out_dir: Path, now: datetime | None = None) -> Path:
    """
    `shlink-<host>-<UTC time>.snapshot.json` in `out_dir`, readable by its owner only,
    and never over an existing one.
    """
    host = urlsplit(snapshot["shlink"]["url"]).hostname
    stamp = (now or datetime.now(timezone.utc)).strftime("%Y%m%dT%H%M%SZ")
    path = Path(out_dir) / f"shlink-{host}-{stamp}.snapshot.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "w", encoding="utf-8") as f:
        json.dump(snapshot, f, ensure_ascii=False, indent=1)
    return path


# --- What a snapshot says about a link's visits: the export's summary, the review, the import


def visits_state(entry: dict) -> str:
    """
    `""` without visits in the snapshot; `complete`; `recovered` when Shlink failed but the
    date ranges brought every visit; `partial` when some ranges stayed out; `failed` when
    none of its visits came.
    """
    if "visits" not in entry:
        return ""
    if "visits_error" not in entry:
        return "complete"
    if not entry.get("visits_gaps"):
        return "recovered"
    return "partial" if entry["visits"] else "failed"


def format_gap(gap: dict) -> str:
    """An ISO 8601 interval, both ends included to the second; `…` for an open end. A gap
    with neither end is visits that Shlink counts but no date range reached."""
    return f"{gap.get('start') or '…'}/{gap.get('end') or '…'}"


def summary(snapshot: dict) -> list[str]:
    """What the export brought, for the operator: the links, and with visits, which failed."""
    links = snapshot["links"]
    lines = [f"{_count(links, 'link')} exported."]
    if "visits_failed" not in snapshot:
        return lines
    whole = [entry for entry in links if visits_state(entry) == "complete"]
    with_visits = [entry for entry in whole if entry["visits"]]
    lines.append(
        f"Visits exported whole for {_count(whole, 'link')}, {len(with_visits)} of them with "
        f"visits ({_count([v for entry in whole for v in entry['visits']], 'visit')})."
    )
    failed = [entry for entry in links if "visits_error" in entry]
    if not failed:
        return lines
    lines.append(
        f"Visits failed for {_count(failed, 'link')}: "
        + ", ".join(entry["short_url"]["shortCode"] for entry in failed)
    )
    for entry in failed:
        error, gaps = entry["visits_error"], entry.get("visits_gaps") or []
        lost = f"lost {_count(gaps, 'range')}: " + ", ".join(map(format_gap, gaps))
        lines.append(
            f"  {entry['short_url']['shortCode']}: Shlink answered {error['status']} "
            f"({error['detail']}). Recovered {_count(entry['visits'], 'visit')} by date, "
            + (lost if gaps else "none lost")
        )
    return lines


def _count(items: list, noun: str) -> str:
    return f"{len(items)} {noun}{'' if len(items) == 1 else 's'}"


# --- Requests ---------------------------------------------------------------------------


def _retrying(client: httpx.Client, retries: int, backoff: float, sleep) -> Get:
    """GET → its JSON. A 5xx is asked again `retries` times, waiting longer each time; any
    other error status, or the last 5xx, raises HTTPStatusError."""

    def get(path: str, params: dict | None) -> dict:
        for attempt in range(retries + 1):
            response = client.get(path, params=params)
            if not response.is_server_error or attempt == retries:
                break
            sleep(backoff * 2**attempt)
        response.raise_for_status()
        return response.json()

    return get


def _pages(
    get: Get, path: str, name: str, page_size: int, params: dict | None = None
) -> Iterator[dict]:
    page = 1
    while True:
        body = get(path, {**(params or {}), "page": page, "itemsPerPage": page_size})
        yield from body[name]["data"]
        if page >= body[name]["pagination"]["pagesCount"]:
            return
        page += 1


def _detail(response: httpx.Response) -> str:
    """Shlink's problem detail (RFC 7807), else the reason phrase."""
    try:
        body = response.json()
    except ValueError:
        body = None
    detail = (body.get("detail") or body.get("title")) if isinstance(body, dict) else None
    return str(detail or response.reason_phrase)[:300]


def _is_5xx(error: httpx.HTTPStatusError) -> bool:
    return error.response.is_server_error


# --- Recovering a link's visits by date range -----------------------------------------
#
# What Shlink's spec offers for a link's visits (getShortUrlVisits): `startDate` and
# `endDate` (ISO 8601), `page` and `itemsPerPage`, `excludeBots`. Nothing else narrows
# it: no visit id, no cursor. Shlink compares both dates inclusively, to the second, and
# lists the newest first; a page past the last one is an error, not an empty page.
#
# So a range that fails is cut in two, down to a single second; that second is then read
# one visit per page, keeping those that serialize. A second where one didn't is a gap.


def _recover(
    get: Get,
    path: str,
    params: dict,
    *,
    page_size: int,
    budget: int,
    until: datetime,
    expected: int | None,
) -> tuple[list[dict], list[dict]]:
    """The link's visits from EARLIEST to `until`, and the ranges lost, oldest first. Past
    `budget` requests, the ranges left to try become gaps as they are."""
    requests = 0

    def counted(path: str, params: dict | None) -> dict:
        nonlocal requests
        requests += 1
        return get(path, params)

    found, gaps = [], []
    # Seconds since the epoch, both ends included. A stack: the newer half comes out first,
    # so the visits stay newest first, as Shlink lists them.
    pending = [(_seconds(EARLIEST), _seconds(until))]
    while pending:
        start, end = pending.pop()
        if requests >= budget:
            gaps.append((start, end))
            continue
        window = {**params, "startDate": _iso(start), "endDate": _iso(end)}
        try:
            found += list(_pages(counted, path, "visits", page_size, window))
        except httpx.HTTPStatusError as error:
            if not _is_5xx(error):
                raise
            if start < end:
                middle = (start + end) // 2
                pending += [(start, middle), (middle + 1, end)]
                continue
            visits, lost = _one_second(counted, path, window)
            found += visits
            if lost:
                gaps.append((start, end))
    ranges = [{"start": _iso(start), "end": _iso(end)} for start, end in sorted(gaps)]
    if not ranges and expected is not None and len(found) < expected:
        # Every range answered, yet fewer visits than Shlink counts: some no date reaches.
        ranges.append({"start": None, "end": None})
    return found, ranges


def _one_second(get: Get, path: str, window: dict) -> tuple[list[dict], bool]:
    """One second's visits, one per page: those Shlink can serialize, and whether one
    failed. Until a page succeeds the count is unknown, and a page past the last one fails
    too: two failures in a row with no count end it."""
    found, lost, pages, failures, page = [], False, None, 0, 1
    while pages is None or page <= pages:
        try:
            body = get(path, {**window, "page": page, "itemsPerPage": 1})
        except httpx.HTTPStatusError as error:
            if not _is_5xx(error):
                raise
            lost, failures = True, failures + 1
            if pages is None and failures >= 2:
                break
        else:
            found += body["visits"]["data"]
            pages, failures = body["visits"]["pagination"]["pagesCount"], 0
        page += 1
    return found, lost


def _seconds(moment: datetime) -> int:
    return int(moment.timestamp())


def _iso(seconds: int) -> str:
    return datetime.fromtimestamp(seconds, tz=timezone.utc).isoformat()
