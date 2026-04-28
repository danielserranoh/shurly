"""
Phase 5.3 — hand-curated MCP tools.

Tests target `mcp_server.curated.*` directly (passing a test DB session and
test user) rather than going through the MCP transport layer. The MCP
wrappers in `mcp_server/server.py` are thin shims that open a SessionLocal
and resolve the user from auth context (Phase 5.4) before delegating here.
"""

from __future__ import annotations

import pytest

pytest.importorskip("fastmcp")

import asyncio  # noqa: E402

from mcp_server import curated  # noqa: E402
from server.core.models import URL, OrphanVisit, OrphanVisitType, URLType, Visitor  # noqa: E402
from server.utils.domain import get_or_create_default_domain  # noqa: E402

# ---------------------------------------------------------------------------
# Tool surface — listing must include the curated tools
# ---------------------------------------------------------------------------


def test_curated_tools_appear_in_mcp_surface():
    from mcp_server.server import _build_mcp_server

    server = _build_mcp_server()
    tools = asyncio.run(server.list_tools())
    names = {t.name for t in tools}
    expected = {
        "create_campaign_from_rows",
        "add_redirect_rule",
        "get_url_analytics_summary",
        "list_orphan_visits_grouped",
    }
    assert expected <= names, f"Missing curated tools: {expected - names}"


# ---------------------------------------------------------------------------
# create_campaign_from_rows
# ---------------------------------------------------------------------------


def test_create_campaign_from_rows_creates_one_url_per_row(db_session, test_user):
    result = curated.create_campaign_from_rows(
        db_session, test_user,
        name="Spring Outreach",
        original_url="https://example.com/landing",
        rows=[
            {"firstName": "John", "lastName": "Doe", "company": "Acme"},
            {"firstName": "Jane", "lastName": "Smith", "company": "TechCorp"},
        ],
    )
    assert result["url_count"] == 2
    assert result["csv_columns"] == ["firstName", "lastName", "company"]
    assert result["name"] == "Spring Outreach"
    # Each generated URL stores the row as user_data.
    urls = db_session.query(URL).filter(URL.url_type == URLType.CAMPAIGN).all()
    assert len(urls) == 2
    user_data_companies = sorted(u.user_data["company"] for u in urls)
    assert user_data_companies == ["Acme", "TechCorp"]


def test_create_campaign_from_rows_rejects_invalid_url(db_session, test_user):
    with pytest.raises(ValueError, match="valid http/https URL"):
        curated.create_campaign_from_rows(
            db_session, test_user,
            name="x", original_url="not-a-url",
            rows=[{"a": "1"}],
        )


def test_create_campaign_from_rows_rejects_empty_rows(db_session, test_user):
    with pytest.raises(ValueError, match="at least one entry"):
        curated.create_campaign_from_rows(
            db_session, test_user,
            name="x", original_url="https://example.com", rows=[],
        )


# ---------------------------------------------------------------------------
# add_redirect_rule
# ---------------------------------------------------------------------------


def _seed_url(db_session, user, code="abc123") -> URL:
    domain_id = get_or_create_default_domain(db_session).id
    url = URL(
        short_code=code,
        original_url="https://example.com",
        url_type=URLType.STANDARD,
        created_by=user.id,
        domain_id=domain_id,
    )
    db_session.add(url)
    db_session.commit()
    db_session.refresh(url)
    return url


def test_add_redirect_rule_builds_conditions_from_named_args(db_session, test_user):
    url = _seed_url(db_session, test_user, code="ios001")
    result = curated.add_redirect_rule(
        db_session, test_user,
        short_code="ios001",
        target_url="https://example.com/ios",
        priority=10,
        device="ios",
        language="en",
    )
    assert result["url_id"] == str(url.id)
    assert result["priority"] == 10
    assert result["target_url"] == "https://example.com/ios"
    assert {c["type"] for c in result["conditions"]} == {"device", "language"}


def test_add_redirect_rule_query_param_presence_only(db_session, test_user):
    _seed_url(db_session, test_user, code="qpres1")
    result = curated.add_redirect_rule(
        db_session, test_user,
        short_code="qpres1",
        target_url="https://example.com/track",
        query_param="utm_source",
    )
    cond = result["conditions"][0]
    assert cond == {"type": "query_param", "param": "utm_source"}


def test_add_redirect_rule_query_param_with_value(db_session, test_user):
    _seed_url(db_session, test_user, code="qval01")
    result = curated.add_redirect_rule(
        db_session, test_user,
        short_code="qval01",
        target_url="https://example.com/track",
        query_param="utm_source",
        query_value="newsletter",
    )
    cond = result["conditions"][0]
    assert cond == {
        "type": "query_param",
        "param": "utm_source",
        "value": "newsletter",
    }


def test_add_redirect_rule_requires_at_least_one_condition(db_session, test_user):
    _seed_url(db_session, test_user, code="nocond")
    with pytest.raises(ValueError, match="At least one condition"):
        curated.add_redirect_rule(
            db_session, test_user,
            short_code="nocond",
            target_url="https://example.com",
        )


def test_add_redirect_rule_rejects_unknown_short_code(db_session, test_user):
    with pytest.raises(LookupError):
        curated.add_redirect_rule(
            db_session, test_user,
            short_code="nope99",
            target_url="https://example.com",
            device="ios",
        )


# ---------------------------------------------------------------------------
# get_url_analytics_summary
# ---------------------------------------------------------------------------


def test_get_url_analytics_summary_composes_overview_daily_geo(db_session, test_user):
    from datetime import datetime, timezone

    url = _seed_url(db_session, test_user, code="anasum")
    now = datetime.now(timezone.utc)
    db_session.add_all([
        Visitor(url_id=url.id, short_code=url.short_code, ip="1.1.1.1", country="Spain", visited_at=now, is_bot=False),
        Visitor(url_id=url.id, short_code=url.short_code, ip="2.2.2.2", country="Spain", visited_at=now, is_bot=False),
        Visitor(url_id=url.id, short_code=url.short_code, ip="3.3.3.3", country="France", visited_at=now, is_bot=False),
        Visitor(url_id=url.id, short_code=url.short_code, ip="9.9.9.9", country="Botland", visited_at=now, is_bot=True),
    ])
    db_session.commit()

    result = curated.get_url_analytics_summary(
        db_session, test_user, short_code="anasum", days=7,
    )
    assert result["short_code"] == "anasum"
    assert result["totals"]["clicks"] == 3
    assert result["totals"]["unique_ips"] == 3
    assert result["totals"]["include_bots"] is False
    assert len(result["daily"]) == 7
    countries = {row["country"]: row["clicks"] for row in result["top_countries"]}
    assert countries == {"Spain": 2, "France": 1}


def test_get_url_analytics_summary_include_bots_toggle(db_session, test_user):
    from datetime import datetime, timezone

    url = _seed_url(db_session, test_user, code="botsum")
    now = datetime.now(timezone.utc)
    db_session.add_all([
        Visitor(url_id=url.id, short_code=url.short_code, ip="1.1.1.1", country="Spain", visited_at=now, is_bot=False),
        Visitor(url_id=url.id, short_code=url.short_code, ip="9.9.9.9", country="Botland", visited_at=now, is_bot=True),
    ])
    db_session.commit()

    excl = curated.get_url_analytics_summary(db_session, test_user, short_code="botsum")
    incl = curated.get_url_analytics_summary(
        db_session, test_user, short_code="botsum", include_bots=True
    )
    assert excl["totals"]["clicks"] == 1
    assert incl["totals"]["clicks"] == 2


def test_get_url_analytics_summary_rejects_unknown_short_code(db_session, test_user):
    with pytest.raises(LookupError):
        curated.get_url_analytics_summary(
            db_session, test_user, short_code="missing"
        )


# ---------------------------------------------------------------------------
# list_orphan_visits_grouped
# ---------------------------------------------------------------------------


def test_list_orphan_visits_grouped_clusters_by_path(db_session, test_user):
    from datetime import datetime, timezone

    now = datetime.now(timezone.utc)
    db_session.add_all([
        OrphanVisit(type=OrphanVisitType.INVALID_SHORT_URL, attempted_path="/badcode", ip="1.1.1.1", created_at=now),
        OrphanVisit(type=OrphanVisitType.INVALID_SHORT_URL, attempted_path="/badcode", ip="2.2.2.2", created_at=now),
        OrphanVisit(type=OrphanVisitType.INVALID_SHORT_URL, attempted_path="/badcode", ip="3.3.3.3", created_at=now),
        OrphanVisit(type=OrphanVisitType.INVALID_SHORT_URL, attempted_path="/typo1", ip="4.4.4.4", created_at=now),
        OrphanVisit(type=OrphanVisitType.BASE_URL, attempted_path="/", ip="5.5.5.5", created_at=now),
    ])
    db_session.commit()

    result = curated.list_orphan_visits_grouped(db_session, test_user, since_days=30, limit_groups=10)
    assert result["total_visits"] == 5
    assert result["distinct_paths"] == 3
    paths = {g["attempted_path"]: g["count"] for g in result["groups"]}
    assert paths == {"/badcode": 3, "/typo1": 1, "/": 1}
    badcode = next(g for g in result["groups"] if g["attempted_path"] == "/badcode")
    assert len(badcode["samples"]) == 3  # capped at 3 even though count=3


def test_list_orphan_visits_grouped_sample_cap(db_session, test_user):
    from datetime import datetime, timezone

    now = datetime.now(timezone.utc)
    db_session.add_all([
        OrphanVisit(type=OrphanVisitType.INVALID_SHORT_URL, attempted_path="/x", ip=f"1.1.1.{i}", created_at=now)
        for i in range(10)
    ])
    db_session.commit()

    result = curated.list_orphan_visits_grouped(db_session, test_user)
    group = result["groups"][0]
    assert group["count"] == 10
    assert len(group["samples"]) == 3  # samples are capped, count is not


def test_list_orphan_visits_grouped_validation():
    with pytest.raises(ValueError, match="since_days"):
        curated.list_orphan_visits_grouped(None, None, since_days=0)
    with pytest.raises(ValueError, match="limit_groups"):
        curated.list_orphan_visits_grouped(None, None, limit_groups=0)
