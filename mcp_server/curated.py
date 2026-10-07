"""
Phase 5.3 — hand-curated MCP tools.

These tools sit alongside the auto-generated ones (built by `from_fastapi`
in `mcp_server/server.py`). They exist because four workflows produce
awkward shapes when projected straight from the OpenAPI schema:

* **`create_campaign_from_rows`** — the underlying endpoint takes a CSV
  string in JSON. An LLM building a campaign reasons about rows of dicts,
  not embedded CSV. This tool accepts `rows: list[dict]`, serialises to
  CSV in-memory, and reuses the existing campaign generator.
* **`add_redirect_rule`** — the underlying endpoint takes a free-form
  `conditions: list[dict]`. An LLM is more reliable when condition types
  are explicit named arguments (`device`, `language`, etc.).
* **`get_url_analytics_summary`** — answers "how is this URL doing?" in
  one call by composing overview + daily + geo, instead of forcing the
  LLM to chain three tool invocations.
* **`list_orphan_visits_grouped`** — clusters orphan visits by
  `attempted_path` so typo patterns are visible at a glance instead of
  paginating through a flat event log.

Implementation note (auth): these functions take `db: Session` and
`user: User` explicitly. Tests pass them directly. Phase 5.4 will plumb
both from the MCP request context (bearer token → user lookup →
SessionLocal) so the tools can be invoked over the network.
"""

from __future__ import annotations

import csv
import io
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import func
from sqlalchemy.orm import Session
from sqlalchemy.sql.elements import ColumnElement

from server.app.analytics import _distinct_visitors, _exclude_bots
from server.core.models import (
    Campaign,
    OrphanVisit,
    RedirectRule,
    User,
    Visitor,
)
from server.schemas.datetimes import utc_isoformat
from server.utils.access import Visibility, find_url, viewer
from server.utils.campaign import (
    generate_campaign_urls,
    parse_csv,
    validate_csv,
)
from server.utils.domain import get_or_create_default_domain
from server.utils.local_days import LocalDays, last_days
from server.utils.orphans import did_you_mean, orphan_groups, typo_hits
from server.utils.url import is_valid_url, link_hostname

# ---------------------------------------------------------------------------
# create_campaign_from_rows
# ---------------------------------------------------------------------------


def create_campaign_from_rows(
    db: Session,
    user: User,
    *,
    name: str,
    original_url: str,
    rows: list[dict[str, str]],
    visibility: Visibility = "organization",
) -> dict[str, Any]:
    """
    Create a campaign from a list of row dicts (LLM-friendly shape).

    Equivalent to `POST /api/v1/campaigns` with `csv_data` constructed from
    the rows. The header is the union of the first row's keys (rows must be
    homogeneous; mismatched keys are rejected by `validate_csv`). Like the
    endpoint, the campaign is the organization's unless `visibility="personal"`.
    """
    if not name or not name.strip():
        raise ValueError("name must be non-empty")
    # Phase 6.3 — it goes to the database as is: longer than the column was a 500.
    if len(name) > Campaign.name.type.length:
        raise ValueError(f"name must be at most {Campaign.name.type.length} characters")
    if not is_valid_url(original_url):
        raise ValueError("original_url must be a valid http/https URL")
    if not rows:
        raise ValueError("rows must contain at least one entry")

    columns = list(rows[0].keys())
    if not columns:
        raise ValueError("rows[0] must define at least one column")

    # Serialize to CSV so we can reuse the existing parse/validate path. This
    # keeps the campaign-generation behavior identical to the HTTP endpoint
    # (same uniqueness retry, same user_data shape, same column inference).
    buffer = io.StringIO()
    writer = csv.DictWriter(buffer, fieldnames=columns)
    writer.writeheader()
    writer.writerows(rows)
    csv_data = buffer.getvalue()

    parsed = parse_csv(csv_data)
    is_valid, column_names, error = validate_csv(parsed)
    if not is_valid:
        raise ValueError(f"CSV validation error: {error}")

    # Before the flush, as in the endpoint: creating the default domain commits.
    domain = get_or_create_default_domain(db)

    campaign = Campaign(
        name=name,
        original_url=original_url,
        csv_columns=column_names,
        created_by=user.id,
        organization_id=viewer(db, user).organization_for(visibility),
    )
    db.add(campaign)
    db.flush()

    urls = generate_campaign_urls(
        campaign_id=campaign.id,
        rows=parsed,
        original_url=original_url,
        created_by=user.id,
        domain_id=domain.id,
        db_session=db,
        organization_id=campaign.organization_id,
    )
    db.add_all(urls)
    db.commit()
    db.refresh(campaign)

    return {
        "id": str(campaign.id),
        "name": campaign.name,
        "original_url": campaign.original_url,
        "csv_columns": campaign.csv_columns,
        "url_count": len(urls),
        "created_at": utc_isoformat(campaign.created_at),
        "visibility": campaign.visibility,
    }


# ---------------------------------------------------------------------------
# add_redirect_rule
# ---------------------------------------------------------------------------


def add_redirect_rule(
    db: Session,
    user: User,
    *,
    short_code: str,
    target_url: str,
    domain: str | None = None,
    priority: int = 0,
    device: str | None = None,
    language: str | None = None,
    browser: str | None = None,
    query_param: str | None = None,
    query_value: str | None = None,
    before_date: str | None = None,
    after_date: str | None = None,
) -> dict[str, Any]:
    """
    Create a redirect rule using named condition args.

    Each non-None argument becomes one condition (ANDed together). At least
    one condition must be provided — a rule with no conditions never matches
    and would silently dead-end the LLM's intent. See
    `server/utils/redirect_rules.py` for the supported types.
    """
    if not is_valid_url(target_url):
        raise ValueError("target_url must be a valid http/https URL")

    conditions: list[dict[str, Any]] = []
    if device:
        conditions.append({"type": "device", "value": device})
    if language:
        conditions.append({"type": "language", "value": language})
    if browser:
        conditions.append({"type": "browser", "value": browser})
    if query_param:
        # `query_value=None` → presence-only match (rule fires whenever the
        # param is set, regardless of value). Mirrors evaluator behavior.
        cond: dict[str, Any] = {"type": "query_param", "param": query_param}
        if query_value is not None:
            cond["value"] = query_value
        conditions.append(cond)
    if before_date:
        conditions.append({"type": "before_date", "value": before_date})
    if after_date:
        conditions.append({"type": "after_date", "value": after_date})

    if not conditions:
        raise ValueError(
            "At least one condition (device/language/browser/query_param/"
            "before_date/after_date) must be provided."
        )

    # Phase 3.14.3 — the same rules as the endpoint: see the link, then be able to change it.
    who = viewer(db, user)
    url = find_url(db, who, short_code, domain)  # Phase 8.3 — the code on `domain`
    if url is None:
        raise LookupError(f"URL with short_code={short_code!r} not found for current user")
    if not who.can_change(url):
        raise PermissionError("Only its creator, or an admin or owner, can change this link.")

    rule = RedirectRule(
        url_id=url.id,
        priority=priority,
        conditions=conditions,
        target_url=target_url,
    )
    db.add(rule)
    db.commit()
    db.refresh(rule)

    return {
        "id": str(rule.id),
        "url_id": str(rule.url_id),
        "priority": rule.priority,
        "conditions": rule.conditions,
        "target_url": rule.target_url,
        "created_at": utc_isoformat(rule.created_at),
    }


# ---------------------------------------------------------------------------
# get_url_analytics_summary
# ---------------------------------------------------------------------------


def get_url_analytics_summary(
    db: Session,
    user: User,
    *,
    short_code: str,
    domain: str | None = None,
    days: int = 7,
    include_bots: bool = False,
) -> dict[str, Any]:
    """
    One-shot analytics summary: totals + daily series + top countries.

    Replaces the three-call dance (overview + daily + geo) the LLM would
    otherwise need to answer "how is this URL performing?".
    """
    if days < 1 or days > 90:
        raise ValueError("days must be between 1 and 90")

    url = find_url(db, viewer(db, user), short_code, domain)  # Phase 8.3 — the code on `domain`
    if url is None:
        raise LookupError(f"URL with short_code={short_code!r} not found for current user")

    # The app's clicks (`_exclude_bots`): never the email tracking pixel, which is an open,
    # and crawlers only with include_bots.
    base = _exclude_bots(db.query(Visitor).filter(Visitor.url_id == url.id), include_bots)

    total_clicks = base.count()
    # Unique visitors: distinct addresses, an unknown one aside (`_distinct_visitors`). A
    # count of distinct values is portable; `query.distinct(col).count()` no-ops on SQLite.
    unique_ips = base.with_entities(_distinct_visitors()).scalar() or 0

    # Daily series: the last `days` days where the viewer is (their profile's time zone,
    # else UTC), oldest → newest. The app's days (server/utils/local_days.py), so its numbers.
    local = LocalDays.of(user)
    daily = [
        {"date": day.isoformat(), "clicks": clicks} for day, clicks in last_days(base, local, days)
    ]

    # Top countries (ungrouped — we want the absolute counts, not a
    # percentage, because the LLM may want to compose other questions).
    geo_rows = (
        base.with_entities(
            Visitor.country.label("country"),
            func.count(Visitor.id).label("c"),
        )
        .group_by(Visitor.country)
        .order_by(func.count(Visitor.id).desc())
        .limit(10)
        .all()
    )
    top_countries = [{"country": r.country or "unknown", "clicks": int(r.c)} for r in geo_rows]

    return {
        "short_code": url.short_code,
        "domain": link_hostname(url),
        "original_url": url.original_url,
        "url_type": url.url_type.value if url.url_type else None,
        "totals": {
            "clicks": total_clicks,
            "unique_ips": unique_ips,
            "include_bots": include_bots,
        },
        "daily": daily,
        "timezone": local.name,
        "top_countries": top_countries,
    }


# ---------------------------------------------------------------------------
# list_orphan_visits_grouped
# ---------------------------------------------------------------------------


def list_orphan_visits_grouped(
    db: Session,
    user: User,
    *,
    since_days: int = 30,
    limit_groups: int = 20,
    typos_only: bool = False,
) -> dict[str, Any]:
    """
    Group orphan visits by `attempted_path` so the LLM can spot typo patterns, with the links a
    typo was probably meant for.

    The grouping is the analytics page's (`server/utils/orphans.py`), in SQL, over every kind of
    orphan visit and the last `since_days`; with `typos_only` (3.10.8), only the hits a person
    could have mistyped, as the page asks for them: no scanners' probes, no bots, no "/".
    `hidden_visits` and `hidden_paths` count what it left out. Orphan visits are tenant-wide
    (Phase 3.10.4): `user` decides only which links are suggested. The samples, the newest 3
    hits of each path among those counted, are this tool's own.
    """
    if since_days < 1 or since_days > 365:
        raise ValueError("since_days must be between 1 and 365")
    if limit_groups < 1 or limit_groups > 200:
        raise ValueError("limit_groups must be between 1 and 200")

    since = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(days=since_days)
    found = orphan_groups(db, since=since, typos_only=typos_only, limit=limit_groups)
    groups = found.groups
    paths = [group.attempted_path for group in groups]
    suggested = did_you_mean(db, viewer(db, user), paths)
    samples = _newest_hits(db, paths, since, typo_hits(db) if typos_only else None)

    return {
        "since_days": since_days,
        "total_visits": found.total_visits,
        "distinct_paths": found.total_paths,
        "hidden_visits": found.hidden_visits,
        "hidden_paths": found.hidden_paths,
        "groups": [
            {
                "attempted_path": group.attempted_path,
                "count": group.visits,
                "first_seen": utc_isoformat(group.first_seen),
                "last_seen": utc_isoformat(group.last_seen),
                "did_you_mean": suggested[group.attempted_path],
                "samples": samples.get(group.attempted_path, []),
            }
            for group in groups
        ],
    }


def _newest_hits(
    db: Session, paths: list[str], since: datetime, counted: ColumnElement | None = None
) -> dict[str, list[dict[str, Any]]]:
    """Each path's newest 3 hits since `since`, of those `counted` (every hit without), in one
    query. Their IPs are a decision pending (docs/PERSONAL_DATA.md): shown, as they always
    were."""
    if not paths:
        return {}
    which = [OrphanVisit.created_at >= since, OrphanVisit.attempted_path.in_(paths)]
    if counted is not None:
        which.append(counted)
    newest = (
        func.row_number()
        .over(
            partition_by=OrphanVisit.attempted_path,
            order_by=(OrphanVisit.created_at.desc(), OrphanVisit.id.desc()),
        )
        .label("newest")
    )
    ranked = db.query(OrphanVisit.id, newest).filter(*which).subquery()
    rows = (
        db.query(OrphanVisit)
        .join(ranked, ranked.c.id == OrphanVisit.id)
        .filter(ranked.c.newest <= 3)
        .order_by(ranked.c.newest)
        .all()
    )
    samples: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for r in rows:
        samples[r.attempted_path].append(
            {
                "type": r.type.value,
                "ip": r.ip,
                "user_agent": r.user_agent,
                "referer": r.referer,
                "created_at": utc_isoformat(r.created_at),
            }
        )
    return samples
