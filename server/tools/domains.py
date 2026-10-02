"""
Phase 8.3 — the cutover's default domain (ROADMAP 8.5): `promote` makes a domain the one new links
go on, and the one that was stops being it. Phase 8.5 — `retire` deletes a domain, with its links.

    python -m server.tools.domains promote go.griddo.io [--for-real]
    python -m server.tools.domains retire old.example.com [--for-real]

It makes the domain's row if it's missing (the Shlink import makes go.griddo.io's, with its links),
marks it the default and unmarks the one that was, in one transaction: the app reads the default on
every request, and never sees none or two. A dry run unless --for-real; a second run finds nothing
to do. What it prints are domains and counts.

What the default decides moves at once, without a restart: the domain of new links (the API's, a
campaign's, the MCP's), the link a code names when the API isn't told the domain (`find_url`), and
where a request on a host Shurly doesn't know looks (`resolve_domain_for_host`). A link keeps its
domain: the old default's keep resolving there until it's retired.

DEFAULT_DOMAIN is the other half: which links BASE_URL moves, and the domain of a link from before
domains (`build_short_url`, `link_hostname`). Set it to the same host on the service, in the same
window. A restart with the old one doesn't undo this: at startup, the row marked default wins
(`get_or_create_default_domain`).

`retire` deletes a domain's row and its links, with what hangs off them: their visits, redirect
rules and tag associations, campaign links among them. One transaction; a dry run runs the deletes
and rolls them back. It refuses the default domain (the row marked so, or DEFAULT_DOMAIN's: the
links from before domains count as its) and a domain it doesn't know. What stays: every other
domain's links, the tags and campaigns themselves, and orphan visits, which record no domain. No
redirect is kept: a request on the retired host looks on the default domain, like any host Shurly
doesn't know. What it prints are the links' codes and counts, never their destinations.

In production, as one-off ECS tasks: scripts/run_promote_domain.sh and scripts/run_retire_domain.sh
(DEPLOYMENT.md § The cutover).
"""

import argparse
import re
import sys
from dataclasses import dataclass

from sqlalchemy import delete, func, select

from server.core import SessionLocal
from server.core.config import settings
from server.core.models import URL, Campaign, Domain, RedirectRule, Visitor, url_tags
from server.utils.domain import normalize_hostname

# Tests point this at their database.
session_factory = SessionLocal

# A short link's host: labels of letters, digits and hyphens, none starting or ending with a hyphen,
# at least two of them. Read lowercase, as `normalize_hostname` leaves it.
_LABEL = r"(?!-)[a-z0-9-]{1,63}(?<!-)"
DOMAIN_NAME = re.compile(rf"{_LABEL}(?:\.{_LABEL})+")


@dataclass
class Promotion:
    """What `promote` found, and so did or would do."""

    hostname: str
    links: dict[str, int]  # every domain, and its links
    defaults: list[str]  # the domains marked default, before
    made: bool  # the domain had no row
    unbound: int  # links from before domains, which count as the default's

    @property
    def needed(self) -> bool:
        return self.defaults != [self.hostname]

    @property
    def demoted(self) -> list[str]:
        return [host for host in self.defaults if host != self.hostname]


def promote(db, hostname: str, for_real: bool = False) -> Promotion:
    """Make `hostname` the default domain, and no other. A dry run rolls back."""
    links = dict(
        db.query(Domain.hostname, func.count(URL.id))
        .outerjoin(URL, URL.domain_id == Domain.id)
        .group_by(Domain.hostname)
        .all()
    )
    defaults = db.query(Domain).filter(Domain.is_default.is_(True)).order_by(Domain.hostname).all()
    promotion = Promotion(
        hostname=hostname,
        links=links,
        defaults=[domain.hostname for domain in defaults],
        made=hostname not in links,
        unbound=db.query(func.count(URL.id)).filter(URL.domain_id.is_(None)).scalar(),
    )
    if promotion.needed:
        domain = db.query(Domain).filter(Domain.hostname == hostname).one_or_none()
        if domain is None:
            domain = Domain(hostname=hostname, is_default=False)
            db.add(domain)
        for other in defaults:
            other.is_default = other is domain
        domain.is_default = True
        db.flush()
    if for_real:
        db.commit()
    else:
        db.rollback()
    return promotion


def _count(count: int, noun: str) -> str:
    return f"{count:,} {noun}{'' if count == 1 else 's'}"


def _links(count: int) -> str:
    return _count(count, "link")


def report(promotion: Promotion, for_real: bool) -> list[str]:
    """What the promotion found and did (or, in a dry run, would do), line by line."""
    host = promotion.hostname
    lines = ["Domains:"]
    for name in sorted(promotion.links):
        default = "the default, " if name in promotion.defaults else ""
        lines.append(f"  {name}: {default}{_links(promotion.links[name])}")
    if not promotion.links:
        lines.append("  none yet")

    if not promotion.needed:
        lines.append(f"{host} is the default domain already: nothing to do.")
    else:
        if promotion.made:
            lines.append(
                f"{host} isn't a domain here yet: it's made, with no links. The Shlink import makes "
                "it, with its links: if that ran on this database, check the name."
            )
        was = " and ".join(promotion.demoted)
        one = len(promotion.demoted) == 1
        if for_real:
            lines.append(
                f"{host} is the default domain now"
                + (f", and {was} {'is' if one else 'are'}n't." if was else ".")
            )
        else:
            lines.append(
                f"{host} becomes the default domain"
                + (f", and {was} {'stops' if one else 'stop'} being it." if was else ".")
            )
        lines.append(
            f"New links go on {host}, and a code on several domains names {host}'s link when the "
            "API isn't told the domain. Every link keeps its domain"
            + (f": {was}'s keep resolving there." if was else ".")
        )
        if promotion.unbound:
            counts = "counts" if promotion.unbound == 1 else "count"
            lines.append(f"{_links(promotion.unbound)} from before domains {counts} as {host}'s.")

    if normalize_hostname(settings.default_domain) != host:
        lines.append(
            f"DEFAULT_DOMAIN is {settings.default_domain} here: set it to {host} on the service "
            "too, in the same window (DEPLOYMENT.md § The cutover)."
        )
    if promotion.needed and not for_real:
        lines.append("Dry run: nothing was written. --for-real writes it.")
    return lines


class Refused(Exception):
    """`retire` won't: the domain is the default, or isn't one here. Nothing was written."""


@dataclass
class RetiredLink:
    code: str
    visits: int
    rules: int
    tags: int


@dataclass
class Retirement:
    """What `retire` found, and so deleted or would delete."""

    hostname: str
    links: list[RetiredLink]
    campaigns: list[tuple[str, int, int]]  # a campaign's name, its links here, and all its links

    def total(self, field: str) -> int:
        return sum(getattr(link, field) for link in self.links)


def _refuse_default(hostname: str, domain: Domain) -> None:
    if domain.is_default:
        raise Refused(
            f"{hostname} is the default domain: new links go on it. Promote another first "
            "(python -m server.tools.domains promote), then retire this one."
        )
    if normalize_hostname(settings.default_domain) == hostname:
        raise Refused(
            f"{hostname} is DEFAULT_DOMAIN here: the links from before domains count as its, and "
            "startup makes it the default again if no row is. Set DEFAULT_DOMAIN to another "
            "domain first."
        )


def _per_link(column):
    """How many rows `column` (a foreign key to urls.id) has for the link in the query."""
    return select(func.count()).where(column == URL.id).correlate(URL).scalar_subquery()


def retire(db, hostname: str, for_real: bool = False) -> Retirement:
    """Delete `hostname`'s row and its links, with what hangs off them, in one transaction. A dry
    run runs the deletes and rolls them back. Raises Refused, before writing anything, for the
    default domain or one that isn't here."""
    domain = db.query(Domain).filter(Domain.hostname == hostname).one_or_none()
    if domain is None:
        known = ", ".join(host for (host,) in db.query(Domain.hostname).order_by(Domain.hostname))
        raise Refused(
            f"{hostname} isn't a domain here: nothing to retire. The domains here: "
            f"{known or 'none'}."
        )
    _refuse_default(hostname, domain)

    rows = (
        db.query(
            URL.short_code,
            _per_link(Visitor.url_id),
            _per_link(RedirectRule.url_id),
            _per_link(url_tags.c.url_id),
        )
        .filter(URL.domain_id == domain.id)
        .order_by(URL.short_code)
        .all()
    )
    here = func.count(URL.id).filter(URL.domain_id == domain.id)
    campaigns = (
        db.query(Campaign.name, here, func.count(URL.id))
        .join(URL, URL.campaign_id == Campaign.id)
        .group_by(Campaign.id, Campaign.name)
        .having(here > 0)
        .order_by(Campaign.name)
        .all()
    )
    retirement = Retirement(
        hostname=hostname,
        links=[RetiredLink(code, visits, rules, tags) for code, visits, rules, tags in rows],
        campaigns=[(name, mine, every) for name, mine, every in campaigns],
    )

    # What references urls.id (url_tags, redirect_rules, visits), then the links, then the
    # domain: only urls references domains.id. Orphan visits record no domain.
    on_domain = select(URL.id).where(URL.domain_id == domain.id)
    for statement in (
        delete(url_tags).where(url_tags.c.url_id.in_(on_domain)),
        delete(RedirectRule).where(RedirectRule.url_id.in_(on_domain)),
        delete(Visitor).where(Visitor.url_id.in_(on_domain)),
        delete(URL).where(URL.domain_id == domain.id),
        delete(Domain).where(Domain.id == domain.id),
    ):
        db.execute(statement.execution_options(synchronize_session=False))
    db.flush()
    if for_real:
        db.commit()
    else:
        db.rollback()
    return retirement


def _and(parts: list[str]) -> str:
    return ", ".join(parts[:-1]) + " and " + parts[-1]


def retire_report(retirement: Retirement, for_real: bool) -> list[str]:
    """What retiring the domain found and deleted (or, in a dry run, would delete), line by line:
    its links by code, with their counts. Never a destination: one can carry a recipient's
    details."""
    host = retirement.hostname
    links = retirement.links
    lines = [f"{host}: {_links(len(links)) if links else 'no links'}"]
    for link in links:
        lines.append(
            f"  {link.code}: {_count(link.visits, 'visit')}, "
            f"{_count(link.rules, 'redirect rule')}, {_count(link.tags, 'tag')}"
        )
    if retirement.campaigns:
        among = "; ".join(
            f"{name}: {mine:,} of its {_links(every)}" for name, mine, every in retirement.campaigns
        )
        lines.append(
            f"Campaign links among them: {among}. The campaigns stay, with their links on other "
            "domains."
        )

    if links:
        what = _and(
            [
                _count(retirement.total("visits"), "visit"),
                _count(retirement.total("rules"), "redirect rule"),
                _count(retirement.total("tags"), "tag association"),
            ]
        )
        if for_real:
            lines.append(
                f"{host} is retired: its row and {_links(len(links))} are deleted, with {what}."
            )
        else:
            lines.append(f"Retiring {host} deletes its row and {_links(len(links))}, with {what}.")
    elif for_real:
        lines.append(f"{host} is retired: its row is deleted.")
    else:
        lines.append(f"Retiring {host} deletes its row.")
    lines.append(
        "The tags themselves stay. Orphan visits record no domain: none are deleted. No redirect "
        f"is kept: a request on {host} looks on the default domain, like any host Shurly doesn't "
        "know."
    )
    if not for_real:
        lines.append("Dry run: nothing was written. --for-real deletes it.")
    return lines


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m server.tools.domains")
    commands = parser.add_subparsers(dest="command", required=True)
    promoting = commands.add_parser(
        "promote", help="make a domain the default: the one new links go on"
    )
    promoting.add_argument("domain", help="e.g. go.griddo.io")
    promoting.add_argument("--for-real", action="store_true", help="write it; without, a dry run")
    retiring = commands.add_parser(
        "retire", help="delete a domain, with its links and what hangs off them"
    )
    retiring.add_argument("domain", help="e.g. old.example.com")
    retiring.add_argument("--for-real", action="store_true", help="delete it; without, a dry run")
    args = parser.parse_args(argv)
    command = {"promote": promoting, "retire": retiring}[args.command]

    hostname = normalize_hostname(args.domain)
    if not DOMAIN_NAME.fullmatch(hostname):
        command.error(f"{args.domain!r} isn't a domain, such as go.griddo.io")
    with session_factory() as db:
        if args.command == "promote":
            lines = report(promote(db, hostname, args.for_real), args.for_real)
        else:
            try:
                lines = retire_report(retire(db, hostname, args.for_real), args.for_real)
            except Refused as refused:
                print(f"✗ {refused} Nothing was written.", file=sys.stderr)
                return 1
    print("\n".join(lines))
    return 0


if __name__ == "__main__":
    sys.exit(main())
