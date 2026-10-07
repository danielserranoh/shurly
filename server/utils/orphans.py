"""
Orphan visits by the path tried (ROADMAP 3.10.4): the analytics page's "Typos & broken links"
(`GET /api/v1/analytics/orphan-visits/grouped`) and the MCP's `list_orphan_visits_grouped`. One
grouping, in SQL, so neither loads the rows. And the links a typo was probably meant for.

Typos only (3.10.8): the hits a person could have mistyped, without scanners' probes and bots
(`typo_hits`). Every orphan visit is still recorded: the filter is the grouping's, not the log's.
"""

import string
from collections.abc import Collection
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import and_, case, func, not_
from sqlalchemy.orm import Session, joinedload
from sqlalchemy.sql.elements import ColumnElement

from server.core.config import settings
from server.core.models import URL, OrphanVisit, OrphanVisitType
from server.utils.access import Viewer
from server.utils.url import MAX_SHORT_CODE_LENGTH, link_hostname, link_short_url
from server.utils.user_agent import bot_agent

# What a code is made of (server/utils/url.py: generated codes and custom slugs), and its length.
CODE_CHARACTERS = frozenset(string.ascii_letters + string.digits + "_-")
LONGEST_CODE = MAX_SHORT_CODE_LENGTH
SUGGESTIONS = 3  # at most, per path

# A path a code could be, as `_typed_code` has it: one segment of code characters, as long as a
# code at most. In SQL: `~` on PostgreSQL, Python's `re` on SQLite (SQLAlchemy's REGEXP).
CODE_PATH = rf"^/[A-Za-z0-9_-]{{1,{LONGEST_CODE}}}$"

# What scanners try that's shaped like a code, so the shape alone doesn't tell: WordPress's and
# phpMyAdmin's doors, Exchange's (owa, ecp, autodiscover), Spring's actuator, routers' (HNAP1,
# boaform), Solr, Composer's vendor folder. Their other probes (/.env, /wp-login.php, /.git/config,
# /.well-known/…) have a dot or a slash no code has. Compared whatever the case. Kept short: a
# word here hides a person's typo of it too.
#
# It can't hide a link: a hit on a link's code finds the link, so it's no orphan. A word that is a
# link's code somewhere still isn't hidden (`_scanner_paths`), as on another domain, or in another
# case where codes keep theirs, its hits could be someone's typo of the domain or the case.
SCANNER_WORDS = frozenset(
    {
        "wp-admin",
        "wp-login",
        "wp-content",
        "wp-includes",
        "wordpress",
        "admin",
        "administrator",
        "phpmyadmin",
        "xmlrpc",
        "cgi-bin",
        "owa",
        "ecp",
        "autodiscover",
        "actuator",
        "console",
        "boaform",
        "hnap1",
        "solr",
        "vendor",
    }
)


@dataclass(frozen=True)
class OrphanGroup:
    """A path tried on an unknown code: how often, and its first and last hit (naive UTC)."""

    attempted_path: str
    visits: int
    first_seen: datetime
    last_seen: datetime


@dataclass(frozen=True)
class OrphanGroups:
    """A page of groups, with over every page how many hits and paths there are, and how many
    `typos_only` left out (none without it)."""

    groups: list[OrphanGroup]
    total_visits: int
    total_paths: int
    hidden_visits: int
    hidden_paths: int


def typo_hits(db: Session) -> ColumnElement:
    """
    The orphan visits a person could have mistyped, all of these:

    - on an unknown code (`invalid_short_url`): not "/" (`base_url`), and not a regular 404;
    - shaped like a code: one segment of code characters, as long as a code at most;
    - not one of the scanners' words (SCANNER_WORDS), unless it's a link's code;
    - not from a bot: a user agent a visit's `is_bot` would flag, from the same patterns.

    In SQL, so the page, its totals and what's hidden all count the same hits.
    """
    return and_(
        OrphanVisit.type == OrphanVisitType.INVALID_SHORT_URL,
        OrphanVisit.attempted_path.regexp_match(CODE_PATH),
        func.lower(OrphanVisit.attempted_path).not_in(_scanner_paths(db)),
        not_(bot_agent(OrphanVisit.user_agent)),
    )


def _scanner_paths(db: Session) -> list[str]:
    """SCANNER_WORDS as paths, but for those that are a link's code on any domain, in any case."""
    links = {
        code
        for (code,) in db.query(func.lower(URL.short_code))
        .filter(func.lower(URL.short_code).in_(sorted(SCANNER_WORDS)))
        .distinct()
    }
    return [f"/{word}" for word in sorted(SCANNER_WORDS - links)]


def orphan_groups(
    db: Session,
    *,
    since: datetime,
    until: datetime | None = None,
    types: Collection[OrphanVisitType] | None = None,
    typos_only: bool = False,
    skip: int = 0,
    limit: int = 20,
) -> OrphanGroups:
    """
    A page of the paths tried from `since` to `until` (naive UTC), of `types` (every type
    without), only the hits `typo_hits` keeps with `typos_only`: the most tried first, then the
    latest hit, then the path. With, over every page, how many hits and how many paths, and how
    many of those of `types` `typos_only` left out: the hits, and the paths with none shown.
    """
    tried = [OrphanVisit.created_at >= since]
    if until is not None:
        tried.append(OrphanVisit.created_at < until)
    if types is not None:
        tried.append(OrphanVisit.type.in_(list(types)))
    shown = typo_hits(db) if typos_only else None
    visits = func.count(OrphanVisit.id)
    last = func.max(OrphanVisit.created_at)
    rows = (
        db.query(OrphanVisit.attempted_path, visits, func.min(OrphanVisit.created_at), last)
        .filter(*tried, *([shown] if shown is not None else []))
        .group_by(OrphanVisit.attempted_path)
        .order_by(visits.desc(), last.desc(), OrphanVisit.attempted_path)
        .offset(skip)
        .limit(limit)
        .all()
    )
    path = OrphanVisit.attempted_path
    if shown is None:
        all_visits, all_paths = (
            db.query(func.count(OrphanVisit.id), func.count(func.distinct(path)))
            .filter(*tried)
            .one()
        )
        total_visits, total_paths = all_visits, all_paths
    else:  # one pass: every hit of `types`, and those shown
        all_visits, all_paths, total_visits, total_paths = (
            db.query(
                func.count(OrphanVisit.id),
                func.count(func.distinct(path)),
                func.count(case((shown, OrphanVisit.id))),
                func.count(func.distinct(case((shown, path)))),
            )
            .filter(*tried)
            .one()
        )
    return OrphanGroups(
        groups=[OrphanGroup(*row) for row in rows],
        total_visits=total_visits,
        total_paths=total_paths,
        hidden_visits=all_visits - total_visits,
        hidden_paths=all_paths - total_paths,
    )


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
