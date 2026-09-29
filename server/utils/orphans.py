"""
Orphan visits by the path tried (ROADMAP 3.10.4): the analytics page's "Typos & broken links"
(`GET /api/v1/analytics/orphan-visits/grouped`) and the MCP's `list_orphan_visits_grouped`. One
grouping, in SQL, so neither loads the rows. And the links a typo was probably meant for.
"""

import string
from collections.abc import Collection
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import case, func
from sqlalchemy.orm import Session, joinedload

from server.core.config import settings
from server.core.models import URL, OrphanVisit, OrphanVisitType
from server.utils.access import Viewer
from server.utils.url import link_hostname, link_short_url

# What a code is made of (server/utils/url.py: generated codes and custom slugs), and its length.
CODE_CHARACTERS = frozenset(string.ascii_letters + string.digits + "_-")
LONGEST_CODE = URL.__table__.c.short_code.type.length
SUGGESTIONS = 3  # at most, per path


@dataclass(frozen=True)
class OrphanGroup:
    """A path tried on an unknown code: how often, and its first and last hit (naive UTC)."""

    attempted_path: str
    visits: int
    first_seen: datetime
    last_seen: datetime


def orphan_groups(
    db: Session,
    *,
    since: datetime,
    until: datetime | None = None,
    types: Collection[OrphanVisitType] | None = None,
    skip: int = 0,
    limit: int = 20,
) -> tuple[list[OrphanGroup], int, int]:
    """
    A page of the paths tried from `since` to `until` (naive UTC), of `types` (every type
    without): the most tried first, then the latest hit, then the path. With, over every page,
    how many hits and how many paths.
    """
    tried = [OrphanVisit.created_at >= since]
    if until is not None:
        tried.append(OrphanVisit.created_at < until)
    if types is not None:
        tried.append(OrphanVisit.type.in_(list(types)))
    visits = func.count(OrphanVisit.id)
    last = func.max(OrphanVisit.created_at)
    rows = (
        db.query(OrphanVisit.attempted_path, visits, func.min(OrphanVisit.created_at), last)
        .filter(*tried)
        .group_by(OrphanVisit.attempted_path)
        .order_by(visits.desc(), last.desc(), OrphanVisit.attempted_path)
        .offset(skip)
        .limit(limit)
        .all()
    )
    total_visits, total_paths = (
        db.query(func.count(OrphanVisit.id), func.count(func.distinct(OrphanVisit.attempted_path)))
        .filter(*tried)
        .one()
    )
    return [OrphanGroup(*row) for row in rows], total_visits, total_paths


def did_you_mean(db: Session, who: Viewer, paths: Collection[str]) -> dict[str, list[dict]]:
    """
    For each path, the links `who` sees that it's one edit from, the likeliest first: the same
    code but for case (where codes are lowercase), then the newest; SUGGESTIONS at most. One
    query per path that could be a code, found by index; none for the others.
    """
    loose = settings.short_url_mode == "loose"
    alphabet = string.ascii_lowercase if loose else string.ascii_letters
    alphabet += string.digits + "_-"
    found: dict[str, list[dict]] = {}
    for path in paths:
        typed = _typed_code(path, loose)
        if typed is None:
            found[path] = []
            continue
        links = (
            db.query(URL)
            .options(joinedload(URL.domain))
            .filter(who.sees(URL), URL.short_code.in_(sorted(one_edit_away(typed, alphabet))))
            .order_by(case((URL.short_code == typed, 0), else_=1), URL.created_at.desc(), URL.id)
            .limit(SUGGESTIONS)
            .all()
        )
        found[path] = [
            {
                "short_code": url.short_code,
                "domain": link_hostname(url),
                "short_url": link_short_url(url),
                "title": url.title,
            }
            for url in links
        ]
    return found


def one_edit_away(code: str, alphabet: str) -> set[str]:
    """`code`, and every code one edit from it: a character deleted, swapped with the next one,
    replaced or inserted. About 800 for six characters."""
    splits = [(code[:i], code[i:]) for i in range(len(code) + 1)]
    deleted = {head + tail[1:] for head, tail in splits if tail}
    swapped = {head + tail[1] + tail[0] + tail[2:] for head, tail in splits if len(tail) > 1}
    replaced = {head + c + tail[1:] for head, tail in splits if tail for c in alphabet}
    inserted = {head + c + tail for head, tail in splits for c in alphabet}
    edits = deleted | swapped | replaced | inserted | {code}
    return {edit for edit in edits if 0 < len(edit) <= LONGEST_CODE}


def _typed_code(path: str, loose: bool) -> str | None:
    """The code a path tried, as codes are kept. None when no code could be one edit from it:
    longer than a code, or with a character no code has (a scanner's /wp-login.php)."""
    typed = path.removeprefix("/")
    if not typed or len(typed) > LONGEST_CODE or not CODE_CHARACTERS.issuperset(typed):
        return None
    return typed.lower() if loose else typed
