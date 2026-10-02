"""
Phase 8.3 — the cutover's default domain (ROADMAP 8.5): `promote` makes a domain the one new links
go on, and the one that was stops being it.

    python -m server.tools.domains promote go.griddo.io [--for-real]

It makes the domain's row if it's missing (the Shlink import makes go.griddo.io's, with its links),
marks it the default and unmarks the one that was, in one transaction: the app reads the default on
every request, and never sees none or two. A dry run unless --for-real; a second run finds nothing
to do. What it prints are domains and counts.

What the default decides moves at once, without a restart: the domain of new links (the API's, a
campaign's, the MCP's), the link a code names when the API isn't told the domain (`find_url`), and
where a request on a host Shurly doesn't know looks (`resolve_domain_for_host`). A link keeps its
domain: s.griddo.io's keep resolving there until it's deleted.

DEFAULT_DOMAIN is the other half: which links BASE_URL moves, and the domain of a link from before
domains (`build_short_url`, `link_hostname`). Set it to the same host on the service, in the same
window. A restart with the old one doesn't undo this: at startup, the row marked default wins
(`get_or_create_default_domain`).

In production, as a one-off ECS task: scripts/run_promote_domain.sh (DEPLOYMENT.md § The cutover).
"""

import argparse
import re
import sys
from dataclasses import dataclass

from sqlalchemy import func

from server.core import SessionLocal
from server.core.config import settings
from server.core.models import URL, Domain
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


def _links(count: int) -> str:
    return f"{count:,} link{'' if count == 1 else 's'}"


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


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m server.tools.domains")
    commands = parser.add_subparsers(dest="command", required=True)
    promoting = commands.add_parser(
        "promote", help="make a domain the default: the one new links go on"
    )
    promoting.add_argument("domain", help="e.g. go.griddo.io")
    promoting.add_argument("--for-real", action="store_true", help="write it; without, a dry run")
    args = parser.parse_args(argv)

    hostname = normalize_hostname(args.domain)
    if not DOMAIN_NAME.fullmatch(hostname):
        promoting.error(f"{args.domain!r} isn't a domain, such as go.griddo.io")
    with session_factory() as db:
        promotion = promote(db, hostname, args.for_real)
    print("\n".join(report(promotion, args.for_real)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
