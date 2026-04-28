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
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import func
from sqlalchemy.orm import Session

from server.core.models import (
    URL,
    Campaign,
    OrphanVisit,
    RedirectRule,
    User,
    Visitor,
)
from server.utils.campaign import (
    generate_campaign_urls,
    parse_csv,
    validate_csv,
)
from server.utils.url import is_valid_url

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
) -> dict[str, Any]:
    """
    Create a campaign from a list of row dicts (LLM-friendly shape).

    Equivalent to `POST /api/v1/campaigns` with `csv_data` constructed from
    the rows. The header is the union of the first row's keys (rows must be
    homogeneous; mismatched keys are rejected by `validate_csv`).
    """
    if not name or not name.strip():
        raise ValueError("name must be non-empty")
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

    campaign = Campaign(
        name=name,
        original_url=original_url,
        csv_columns=column_names,
        created_by=user.id,
    )
    db.add(campaign)
    db.flush()

    urls = generate_campaign_urls(
        campaign_id=campaign.id,
        rows=parsed,
        original_url=original_url,
        created_by=user.id,
        db_session=db,
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
        "created_at": campaign.created_at.isoformat() if campaign.created_at else None,
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

    url = (
        db.query(URL)
        .filter(URL.short_code == short_code, URL.created_by == user.id)
        .first()
    )
    if url is None:
        raise LookupError(f"URL with short_code={short_code!r} not found for current user")

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
        "created_at": rule.created_at.isoformat() if rule.created_at else None,
    }


# ---------------------------------------------------------------------------
# get_url_analytics_summary
# ---------------------------------------------------------------------------


def get_url_analytics_summary(
    db: Session,
    user: User,
    *,
    short_code: str,
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

    url = (
        db.query(URL)
        .filter(URL.short_code == short_code, URL.created_by == user.id)
        .first()
    )
    if url is None:
        raise LookupError(f"URL with short_code={short_code!r} not found for current user")

    base = db.query(Visitor).filter(Visitor.url_id == url.id)
    if not include_bots:
        # Excludes both crawlers and the email tracking pixel — the same
        # filter the regular analytics endpoints apply by default.
        base = base.filter(Visitor.is_bot.is_(False), Visitor.is_pixel.is_(False))

    total_clicks = base.count()
    # `func.count(func.distinct(...))` is portable across SQLite and Postgres;
    # the previous `query.distinct(col).count()` form silently no-ops on SQLite.
    unique_ips = (
        base.with_entities(func.count(func.distinct(Visitor.ip))).scalar() or 0
    )

    # Daily series (most recent `days` calendar days, oldest → newest).
    end_date = datetime.now(timezone.utc).date()
    start_date = end_date - timedelta(days=days - 1)
    daily_rows = (
        base.with_entities(
            func.date(Visitor.visited_at).label("d"),
            func.count(Visitor.id).label("c"),
        )
        .filter(func.date(Visitor.visited_at) >= start_date)
        .group_by(func.date(Visitor.visited_at))
        .all()
    )
    counts_by_day = {str(r.d): int(r.c) for r in daily_rows}
    daily = [
        {
            "date": (start_date + timedelta(days=i)).isoformat(),
            "clicks": counts_by_day.get((start_date + timedelta(days=i)).isoformat(), 0),
        }
        for i in range(days)
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
    top_countries = [
        {"country": r.country or "unknown", "clicks": int(r.c)} for r in geo_rows
    ]

    return {
        "short_code": url.short_code,
        "original_url": url.original_url,
        "url_type": url.url_type.value if url.url_type else None,
        "totals": {
            "clicks": total_clicks,
            "unique_ips": unique_ips,
            "include_bots": include_bots,
        },
        "daily": daily,
        "top_countries": top_countries,
    }


# ---------------------------------------------------------------------------
# list_orphan_visits_grouped
# ---------------------------------------------------------------------------


def list_orphan_visits_grouped(
    db: Session,
    user: User,  # noqa: ARG001 — orphans are tenant-wide; kept for auth parity
    *,
    since_days: int = 30,
    limit_groups: int = 20,
) -> dict[str, Any]:
    """
    Group orphan visits by `attempted_path` so the LLM can spot typo patterns.

    Orphan visits are tenant-wide (Phase 3.10.4), so the `user` argument is
    accepted only for auth-context parity with the other curated tools — it
    has no scoping effect on the query.
    """
    if since_days < 1 or since_days > 365:
        raise ValueError("since_days must be between 1 and 365")
    if limit_groups < 1 or limit_groups > 200:
        raise ValueError("limit_groups must be between 1 and 200")

    cutoff = datetime.now(timezone.utc) - timedelta(days=since_days)

    rows = (
        db.query(OrphanVisit)
        .filter(OrphanVisit.created_at >= cutoff)
        .order_by(OrphanVisit.created_at.desc())
        .all()
    )

    paths = Counter(r.attempted_path for r in rows)
    samples: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for r in rows:
        bucket = samples[r.attempted_path]
        if len(bucket) < 3:
            bucket.append(
                {
                    "type": r.type.value,
                    "ip": r.ip,
                    "user_agent": r.user_agent,
                    "referer": r.referer,
                    "created_at": r.created_at.isoformat() if r.created_at else None,
                }
            )

    groups = [
        {
            "attempted_path": path,
            "count": count,
            "samples": samples[path],
        }
        for path, count in paths.most_common(limit_groups)
    ]

    return {
        "since_days": since_days,
        "total_visits": sum(paths.values()),
        "distinct_paths": len(paths),
        "groups": groups,
    }
