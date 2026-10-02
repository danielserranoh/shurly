"""
Phase 8.4 — import: a Shlink snapshot and its review sheet into Shurly.

Every link the review keeps (`keep`, `archive`, or one the review left out) arrives with
its exact code, its domain and its creation date, owned by the importing owner's
organization. Its fields, tags and redirect rules are mapped; what Shurly can't follow is
reported, never dropped silently.

It can run again. A link already there with the same destination is left as it is. One
with another destination stops the import before anything is written, and so does a
link Shurly can't take (a code too long, one of Shurly's own paths, a destination that
isn't http(s)), unless the review drops it.

With `visits` (decision A, 2026-09-28), Shlink's visits come too, as Visitor rows with
ip "unknown": Shlink exposes no addresses. That's how an imported visit is told apart,
and why unique-visitor counts only cover the cutover onward. A run brings only the
visits newer than the link's last imported one, so the cutover's final snapshot adds
what happened since the first import.

A link whose visits Shlink failed to export brings the visits the export recovered, and no
more: the date ranges it lost (the snapshot's `visits_gaps`) are named in the report.
"""

import csv
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit

from sqlalchemy import func
from sqlalchemy.orm import Session

from server.core import SessionLocal
from server.core.config import settings
from server.core.models import URL, Domain, OrgRole, RedirectRule, Tag, URLType, User, Visitor
from server.tools.shlink.export import SnapshotError, check_links, format_gap, visits_state
from server.tools.shlink.mapping import is_bot, is_pixel, map_condition
from server.utils.columns import fit, stored_referer, stored_user_agent
from server.utils.csv_export import unquote_spreadsheet_text
from server.utils.domain import normalize_hostname, serves_app_paths
from server.utils.network import UNKNOWN_IP
from server.utils.organization import get_membership
from server.utils.tags import normalize_tag_name, validate_tag_name
from server.utils.url import MAX_SHORT_CODE_LENGTH, RESERVED_SHORT_CODES, is_valid_url
from server.utils.visit_facets import kind_of

# Tests point this at their database.
session_factory = SessionLocal

# Shlink exposes no visitor addresses: an imported visit's `ip`, and how it's told apart.
IMPORTED_IP = UNKNOWN_IP  # Shlink exposes no addresses
LEGACY_TAG = "legacy"
DECISIONS = ("keep", "archive", "drop")


class ImportRefused(Exception):
    """The import can't run at all: its owner can't import, or its snapshot lists a link
    twice (R17), so another may be missing."""


@dataclass
class Report:
    created: list[str] = field(default_factory=list)
    unchanged: list[str] = field(default_factory=list)
    archived: list[str] = field(default_factory=list)
    dropped: list[str] = field(default_factory=list)
    not_reviewed: list[str] = field(default_factory=list)
    conflicts: list[str] = field(default_factory=list)
    refused: list[str] = field(default_factory=list)
    domains_created: list[str] = field(default_factory=list)
    tags_created: list[str] = field(default_factory=list)
    tags_skipped: list[str] = field(default_factory=list)
    rules_migrated: int = 0
    rules_approximated: list[str] = field(default_factory=list)
    rules_skipped: list[str] = field(default_factory=list)
    visits: int = 0
    visits_lost: list[str] = field(default_factory=list)

    @property
    def blocked(self) -> bool:
        """Conflicts and links Shurly can't take stop the import: nothing is written."""
        return bool(self.conflicts or self.refused)


def import_snapshot(
    db: Session,
    snapshot: dict,
    decisions: dict[tuple[str, str], str],
    owner: User,
    *,
    visits: bool = False,
) -> Report:
    """
    Import `snapshot` into `db`, as `owner` (an owner of their organization), with the
    review's `decisions`, keyed by (domain, code). Flushes, never commits: the caller
    commits, or rolls back a dry run or a blocked import.
    """
    try:
        check_links(entry["short_url"] for entry in snapshot["links"])
    except SnapshotError as error:
        raise ImportRefused(f"{error} Nothing was written.") from None
    membership = get_membership(db, owner)
    if not owner.is_active or membership is None or membership.role != OrgRole.OWNER:
        raise ImportRefused(
            f"{owner.email} isn't an owner of an organization: only an owner imports links."
        )

    report = Report()
    plan = []
    for entry in snapshot["links"]:
        link = entry["short_url"]
        host, code = _address(link)
        name = f"{host}/{code}"
        decision = decisions.get((host, code))
        if decision is None:
            report.not_reviewed.append(name)
            decision = "keep"
        if decision == "drop":
            report.dropped.append(name)
            continue
        why = _refusal(host, code, link["longUrl"])
        if why:
            report.refused.append(f"{name}: {why}")
            continue
        existing = (
            db.query(URL)
            .join(Domain, URL.domain_id == Domain.id)
            .filter(Domain.hostname == host, URL.short_code == code)
            .first()
        )
        if existing is not None and existing.original_url != link["longUrl"]:
            report.conflicts.append(f"{name}: already there, to {existing.original_url}")
            continue
        plan.append((entry, host, code, decision, existing))
    if report.blocked:
        return report

    domains: dict[str, Domain] = {}
    tags: dict[str, Tag | None] = {}
    for entry, host, code, decision, existing in plan:
        name = f"{host}/{code}"
        url = existing
        if url is None:
            url = _create(
                db, report, entry, host, code, owner, membership.organization_id, domains, tags
            )
            if decision == "archive":
                legacy = _tag(db, report, LEGACY_TAG, owner, tags)
                if legacy is not None and legacy not in url.tags:
                    url.tags.append(legacy)
                report.archived.append(name)
            _rules(db, report, url, entry.get("redirect_rules"), name)
            report.created.append(name)
        else:
            report.unchanged.append(name)
        if visits:
            _visits(db, report, url, entry.get("visits") or [])
            if entry.get("visits_gaps"):
                gaps = ", ".join(map(format_gap, entry["visits_gaps"]))
                report.visits_lost.append(f"{name} ({visits_state(entry)}): {gaps}")
    db.flush()
    return report


def read_decisions(path: Path) -> dict[tuple[str, str], str]:
    """
    The review sheet's decisions, keyed by (domain, code). Cells are read back from their
    spreadsheet-safe form; decisions ignore case and spaces. ValueError lists every row
    whose decision isn't keep, archive or drop.
    """
    with path.open(newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        if not {"code", "domain", "decision"} <= set(reader.fieldnames or []):
            raise ValueError(f"{path} needs code, domain and decision columns.")
        decisions, wrong = {}, []
        for row in reader:
            code = unquote_spreadsheet_text(row["code"] or "")
            domain = normalize_hostname(unquote_spreadsheet_text(row["domain"] or ""))
            decision = (row["decision"] or "").strip().lower()
            if decision not in DECISIONS:
                wrong.append(f"{domain}/{code}: {row['decision']!r}")
            decisions[(domain, code)] = decision
    if wrong:
        raise ValueError("Decisions must be keep, archive or drop:\n  " + "\n  ".join(wrong))
    return decisions


def format_report(report: Report, snapshot: dict, *, visits: bool) -> str:
    shlink = snapshot.get("shlink") or {}
    lines = [
        f"Shlink {shlink.get('version') or '?'} at {shlink.get('url')}, exported {snapshot.get('exported_at')}",
        f"  created    {len(report.created)}, {len(report.archived)} of them archived with the "
        f"`{LEGACY_TAG}` tag",
        f"  unchanged  {len(report.unchanged)}: already imported, left as they are",
        f"  dropped    {len(report.dropped)}, as the review says",
        f"  kept       {len(report.not_reviewed)} the review left out",
    ]
    if report.domains_created:
        lines.append(f"  domains created: {', '.join(report.domains_created)}")
    if report.tags_created:
        lines.append(f"  tags created: {', '.join(report.tags_created)}")
    lines += [f"  tag not migrated: {item}" for item in report.tags_skipped]
    lines.append(f"  rules migrated: {report.rules_migrated}")
    lines += [f"  rule approximated: {item}" for item in report.rules_approximated]
    lines += [f"  rule not migrated: {item}" for item in report.rules_skipped]
    if visits:
        lines.append(
            f'  visits imported: {report.visits}, with ip "{IMPORTED_IP}", which tells them apart: '
            "unique-visitor counts cover the cutover onward only"
        )
        if not any("visits" in entry for entry in snapshot["links"]):
            lines.append("  the snapshot has no visits: export it with --visits")
        if report.visits_lost:
            lines.append(
                "  visits Shlink failed to export, so not imported (the snapshot's visits_gaps, "
                "date ranges with both ends included):"
            )
            lines += [f"    {item}" for item in report.visits_lost]
            lines.append(
                "    a later run imports only the visits newer than a link's last imported one: "
                "a gap stays a gap"
            )
    if report.conflicts:
        lines.append("  conflicts, which stop the import:")
        lines += [f"    {item}" for item in report.conflicts]
    if report.refused:
        lines.append(
            "  links Shurly can't take, which stop the import unless the review drops them:"
        )
        lines += [f"    {item}" for item in report.refused]
    return "\n".join(lines)


def _address(link: dict) -> tuple[str, str]:
    """(domain, code). `shortUrl` names the host, Shlink's default domain included."""
    return normalize_hostname(urlsplit(link["shortUrl"]).hostname), link["shortCode"]


def _refusal(host: str, code: str, destination: str) -> str | None:
    if len(code) > MAX_SHORT_CODE_LENGTH:
        return f"longer than {MAX_SHORT_CODE_LENGTH} characters"
    # Exactly: imported codes keep their case. Phase 8.4 — on the app's host only: on a short
    # domain, `/mcp` is a code like any other (go.griddo.io's is a link).
    if code in RESERVED_SHORT_CODES and serves_app_paths(host):
        return "a path Shurly serves itself"
    if not is_valid_url(destination):
        return "not an http(s) destination"
    return None


def _parse(value: str | None) -> datetime | None:
    """An ISO date as an aware UTC datetime; Python 3.10's fromisoformat doesn't read "Z"."""
    if not value:
        return None
    moment = datetime.fromisoformat(value.replace("Z", "+00:00"))
    return (moment if moment.tzinfo else moment.replace(tzinfo=timezone.utc)).astimezone(
        timezone.utc
    )


def _naive_utc(value: str | None) -> datetime | None:
    """For the columns stored without a zone (URL.created_at, Visitor.visited_at): UTC."""
    moment = _parse(value)
    return moment.replace(tzinfo=None) if moment else None


def _create(db, report, entry, host, code, owner, organization_id, domains, tags) -> URL:
    link = entry["short_url"]
    meta = link.get("meta") or {}
    created = _naive_utc(link.get("dateCreated")) or datetime.utcnow()
    url = URL(
        short_code=code,
        domain_id=_domain(db, report, host, domains).id,
        original_url=link["longUrl"],
        url_type=URLType.STANDARD,
        title=fit(link.get("title"), URL.title),
        forward_parameters=bool(link.get("forwardQuery", True)),
        valid_since=_parse(meta.get("validSince")),
        valid_until=_parse(meta.get("validUntil")),
        max_visits=meta.get("maxVisits"),
        crawlable=bool(link.get("crawlable", False)),
        created_by=owner.id,
        organization_id=organization_id,
        created_at=created,
        updated_at=created,
    )
    for raw in link.get("tags") or []:
        tag = _tag(db, report, raw, owner, tags)
        if tag is not None and tag not in url.tags:
            url.tags.append(tag)
    db.add(url)
    db.flush()
    return url


def _domain(db, report, host: str, cache: dict) -> Domain:
    if host not in cache:
        domain = db.query(Domain).filter(Domain.hostname == host).first()
        if domain is None:
            domain = Domain(hostname=host, is_default=False)
            db.add(domain)
            db.flush()
            report.domains_created.append(host)
        cache[host] = domain
    return cache[host]


def _tag(db, report, raw: str, owner: User, cache: dict) -> Tag | None:
    name = normalize_tag_name(raw)
    if name not in cache:
        valid, why = validate_tag_name(name)
        tag = db.query(Tag).filter(Tag.name == name).first() if valid else None
        if not valid:
            report.tags_skipped.append(f"{raw}: {why}")
        elif tag is None:
            tag = Tag(
                name=name,
                display_name=raw.strip(),
                color=settings.user_tag_color,
                is_predefined=False,
                created_by=owner.id,
            )
            db.add(tag)
            db.flush()
            report.tags_created.append(name)
        cache[name] = tag
    return cache[name]


def _rules(db, report, url: URL, redirect_rules: dict | None, name: str) -> None:
    for rule in (redirect_rules or {}).get("redirectRules") or []:
        label = f"{name} rule {rule.get('priority')}"
        conditions, notes, missing = [], [], []
        for condition in rule.get("conditions") or []:
            mapped, note = map_condition(condition)
            if mapped is None:
                missing.append(note)
                continue
            conditions.append(mapped)
            if note:
                notes.append(note)
        if not is_valid_url(rule.get("longUrl") or ""):
            missing.append("not an http(s) destination")
        elif not conditions and not missing:
            missing.append("no conditions")  # in Shurly it would match every visit
        if missing:
            report.rules_skipped.append(f"{label}: {'; '.join(missing)}")
            continue
        db.add(
            RedirectRule(
                url_id=url.id,
                priority=rule.get("priority") or 0,
                conditions=conditions,
                target_url=rule["longUrl"],
            )
        )
        report.rules_migrated += 1
        report.rules_approximated += [f"{label}: {note}" for note in notes]


def _visits(db, report, url: URL, visits: list[dict]) -> None:
    """The link's visits newer than its last imported one (decision A)."""
    latest = (
        db.query(func.max(Visitor.visited_at))
        .filter(Visitor.url_id == url.id, Visitor.ip == IMPORTED_IP)
        .scalar()
    )
    added = []
    for visit in visits:
        moment = _naive_utc(visit.get("date"))
        if moment is None or (latest is not None and moment <= latest):
            continue
        location = visit.get("visitLocation") or {}
        added.append(
            Visitor(
                url_id=url.id,
                short_code=url.short_code,
                ip=IMPORTED_IP,
                # Phase 8.4 — an ISO code, as Shurly stores a country: names differ by provider.
                country=fit(location.get("countryCode") or None, Visitor.country),
                # Its English name, as Shurly's own visits keep one. Never the coordinates.
                city=fit(location.get("cityName") or None, Visitor.city),
                user_agent=stored_user_agent(visit.get("userAgent")),
                referer=stored_referer(visit.get("referer")),
                is_bot=is_bot(visit),
                is_pixel=is_pixel(visit),
                visited_at=moment,
            )
        )
    db.add_all(added)
    report.visits += len(added)
    # The link's last click is a click (Phase 3.16): neither Shlink's potential bots nor opens.
    clicks = [v.visited_at for v in added if kind_of(v.is_pixel, v.is_bot) == "click"]
    if clicks:
        newest = max(clicks).replace(tzinfo=timezone.utc)
        current = url.last_click_at
        if current is not None and current.tzinfo is None:  # SQLite hands back naive
            current = current.replace(tzinfo=timezone.utc)
        if current is None or current < newest:
            url.last_click_at = newest
