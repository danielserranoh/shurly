"""
Every MCP tool's structured output matches its declared outputSchema, dates included.

fastmcp builds each generated tool's outputSchema from the API's OpenAPI response schema, where a
datetime is `{"type": "string", "format": "date-time"}`. RFC 3339's date-time needs an offset, and
strict MCP clients (claude.ai) check the format: a naive `2026-09-29T22:04:42.082199` made
`create_short_url` create the link and then have its whole response rejected, so the assistant
never got the short code. The API now gives every UTC time with `Z` (server/schemas/datetimes.py),
and the 3.16/3.17 analytics keep the viewer's local time with its offset.

The guard: each tool, generated or curated, called through the real in-process MCP server on
seeded data, its structured output validated against its outputSchema with a FormatChecker that
enforces date-time, and every date-time-looking string in it (the curated tools' outputs are free
dicts) required to carry an offset. A schema-level check pins every response model's datetime
fields to the shared types, so a new field can't slip back to a naive one.
"""

from __future__ import annotations

import asyncio
import re
import typing
from contextlib import contextmanager
from datetime import date, datetime, timedelta, timezone

import pytest

fastmcp = pytest.importorskip("fastmcp")
jsonschema = pytest.importorskip("jsonschema")

from server.core import get_db  # noqa: E402
from server.core.models import (  # noqa: E402
    URL,
    Campaign,
    OrganizationMember,
    OrgRole,
    OrphanVisit,
    OrphanVisitType,
    RedirectRule,
    Tag,
    URLType,
    User,
    Visitor,
)
from server.utils import organization as org_service  # noqa: E402
from server.utils.domain import get_or_create_default_domain  # noqa: E402
from server.utils.opengraph import OpenGraphMetadata  # noqa: E402

API_KEY = "output-schema-key"
LOCAL_ZONE = "Asia/Kolkata"  # +05:30 all year: no DST to make a date's offset vary
LOCAL_OFFSET = "+05:30"

# RFC 3339 section 5.6: a full date, "T", a full time with an offset (Z or ±hh:mm).
_RFC3339 = re.compile(
    r"^\d{4}-\d{2}-\d{2}[Tt]\d{2}:\d{2}:\d{2}(\.\d+)?([Zz]|[+-]\d{2}:\d{2})$",
)
# What looks like a date and a time, with or without an offset.
_DATETIME_LIKE = re.compile(r"^\d{4}-\d{2}-\d{2}[Tt ]\d{2}:\d{2}")

format_checker = jsonschema.FormatChecker()


@format_checker.checks("date-time", raises=ValueError)
def _is_rfc3339_date_time(value: object) -> bool:
    """Strict, whatever else is installed: jsonschema only checks date-time with
    rfc3339-validator, and would otherwise let every string through."""
    if not isinstance(value, str):
        return True
    if not _RFC3339.match(value):
        return False
    datetime.fromisoformat(value.replace("z", "Z").replace("t", "T"))
    return True


def test_the_checker_rejects_a_date_time_without_an_offset():
    """The check the guard stands on: a naive time fails, Z and ±hh:mm pass."""
    assert not format_checker.conforms("2026-09-29T22:04:42.082199", "date-time")
    assert format_checker.conforms("2026-09-29T22:04:42.082199Z", "date-time")
    assert format_checker.conforms("2026-09-29T22:04:42+05:30", "date-time")


# ---------------------------------------------------------------------------
# The server, bound to the test database, and the seeded data
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def mcp_server():
    """Built once: the generated tools call `main.app`, whose database each test overrides."""
    from main import app
    from mcp_server.server import build_mcp_for_app

    return build_mcp_for_app(app)


@pytest.fixture(scope="module")
def tools(mcp_server) -> dict:
    return {tool.name: tool for tool in asyncio.run(mcp_server.list_tools())}


@pytest.fixture
def bound(db_session, monkeypatch):
    """The generated tools reach FastAPI on the test database; the curated ones open their
    sessions on it; nothing reaches the network for Open Graph previews."""
    from main import app
    from tests.conftest import TestingSessionLocal

    async def _preview(url: str) -> OpenGraphMetadata:
        return OpenGraphMetadata(title="A preview", description="Its description")

    monkeypatch.setattr("server.app.urls.fetch_opengraph_metadata", _preview)
    monkeypatch.setattr("server.core.SessionLocal", TestingSessionLocal)
    app.dependency_overrides[get_db] = lambda: db_session
    try:
        yield
    finally:
        app.dependency_overrides.pop(get_db, None)


@contextmanager
def _bound_access_token(token: str):
    """Bind `token`, as the real verifier reads it, the way the MCP SDK's auth middleware does
    for each HTTP request: the generated tools forward it, the curated ones read its user."""
    from mcp.server.auth.middleware.auth_context import auth_context_var
    from mcp.server.auth.middleware.bearer_auth import AuthenticatedUser

    from mcp_server.auth import ShurlyTokenVerifier
    from tests.conftest import TestingSessionLocal

    access = asyncio.run(
        ShurlyTokenVerifier(session_factory=TestingSessionLocal).verify_token(token)
    )
    assert access is not None, "the seeded API key doesn't verify"
    reset = auth_context_var.set(AuthenticatedUser(access))
    try:
        yield
    finally:
        auth_context_var.reset(reset)


@pytest.fixture
def seeded(db_session, bound) -> dict:
    """An owner of the organization with one of everything that has a date: a tagged link with
    a preview, a validity window, clicks, an open and a rule; a campaign with clicked
    recipients; an orphan visit."""
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    domain = get_or_create_default_domain(db_session)
    organization = org_service.get_or_create_default_organization(db_session)

    owner = User(email="owner@example.com", is_active=True)
    owner.set_api_key(API_KEY)
    db_session.add(owner)
    db_session.flush()
    db_session.add(
        OrganizationMember(organization_id=organization.id, user_id=owner.id, role=OrgRole.OWNER)
    )

    tag = Tag(name="launch", display_name="Launch", color="blue-500", created_by=owner.id)
    spare = Tag(name="spare", display_name="Spare", color="green-500", created_by=owner.id)
    db_session.add_all([tag, spare])
    db_session.flush()

    link = URL(
        short_code="dates1",
        domain_id=domain.id,
        original_url="https://example.com/launch",
        url_type=URLType.STANDARD,
        title="Launch",
        og_title="Launch",
        og_fetched_at=now - timedelta(days=2),
        last_click_at=now - timedelta(hours=1),
        valid_since=now - timedelta(days=3),
        valid_until=now + timedelta(days=30),
        created_by=owner.id,
        organization_id=organization.id,
    )
    link.tags.append(tag)
    db_session.add(link)

    campaign = Campaign(
        name="Autumn",
        original_url="https://example.com/autumn",
        csv_columns=["name"],
        created_by=owner.id,
        organization_id=organization.id,
    )
    campaign.tags.append(tag)
    db_session.add(campaign)
    db_session.flush()
    recipient = URL(
        short_code="autumn1",
        domain_id=domain.id,
        original_url="https://example.com/autumn",
        url_type=URLType.CAMPAIGN,
        campaign_id=campaign.id,
        user_data={"name": "Ana"},
        last_click_at=now - timedelta(hours=2),
        created_by=owner.id,
        organization_id=organization.id,
    )
    db_session.add(recipient)
    db_session.flush()

    visit = {"ip": "203.0.113.0", "country": "ES", "user_agent": "Mozilla/5.0 (Macintosh)"}
    db_session.add_all(
        [
            Visitor(
                url_id=link.id, short_code="dates1", visited_at=now - timedelta(hours=1), **visit
            ),
            Visitor(
                url_id=link.id, short_code="dates1", visited_at=now - timedelta(hours=5), **visit
            ),
            Visitor(
                url_id=link.id,
                short_code="dates1",
                visited_at=now - timedelta(hours=3),
                is_pixel=True,
                **visit,
            ),
            Visitor(
                url_id=recipient.id,
                short_code="autumn1",
                visited_at=now - timedelta(hours=2),
                **visit,
            ),
        ]
    )
    rule = RedirectRule(
        url_id=link.id,
        priority=1,
        conditions=[{"type": "device", "value": "mobile"}],
        target_url="https://m.example.com/launch",
    )
    db_session.add(rule)
    db_session.add(
        OrphanVisit(
            type=OrphanVisitType.REGULAR_404,
            attempted_path="/dates2",
            ip="203.0.113.0",
            created_at=now - timedelta(hours=4),
        )
    )
    db_session.commit()
    return {
        "code": link.short_code,
        "tag_id": str(tag.id),
        "spare_tag_id": str(spare.id),
        "campaign_id": str(campaign.id),
        "rule_id": str(rule.id),
    }


# ---------------------------------------------------------------------------
# One call per tool
# ---------------------------------------------------------------------------

_TODAY = date.today()
_PERIOD = {"from": (_TODAY - timedelta(days=7)).isoformat(), "to": _TODAY.isoformat()}
_SOON = (datetime.now(timezone.utc) + timedelta(days=1)).isoformat()
_LATER = (datetime.now(timezone.utc) + timedelta(days=10)).isoformat()

# The arguments each tool is called with; `{code}`, `{campaign_id}`, … are the seeded ids.
TOOL_CALLS: dict[str, dict] = {
    # Auth and organization
    "get_current_user_info": {},
    "update_my_profile": {"first_name": "Grace"},
    "get_organization": {},
    "list_organization_members": {},
    # Links
    "create_short_url": {"url": "https://example.com/new"},
    "create_custom_url": {
        "url": "https://example.com/custom",
        "custom_code": "mycustom",
        "valid_since": _SOON,
        "valid_until": _LATER,
    },
    "list_urls": {},
    "get_url": {"short_code": "{code}"},
    "update_url": {"short_code": "{code}", "title": "Relaunch", "valid_until": _LATER},
    "delete_url": {"short_code": "{code}"},
    "update_url_tags": {"short_code": "{code}", "tag_data": {"tag_ids": ["{spare_tag_id}"]}},
    "bulk_tag_urls": {"bulk_data": {"short_codes": ["{code}"], "tag_ids": ["{spare_tag_id}"]}},
    "get_url_preview": {"short_code": "{code}"},
    "refresh_url_preview": {"short_code": "{code}"},
    "fetch_url_metadata": {"url": "https://example.com/page"},
    # Redirect rules
    "list_redirect_rules": {"short_code": "{code}"},
    "create_redirect_rule": {
        "short_code": "{code}",
        "conditions": [{"type": "language", "value": "es"}],
        "target_url": "https://example.com/es",
    },
    "update_redirect_rule": {"short_code": "{code}", "rule_id": "{rule_id}", "priority": 5},
    "delete_redirect_rule": {"short_code": "{code}", "rule_id": "{rule_id}"},
    # Campaigns
    "create_campaign": {
        "name": "Winter",
        "original_url": "https://example.com/winter",
        "csv_data": "name,email\nAna,ana@example.com\nBea,bea@example.com\n",
    },
    "list_campaigns": {},
    "get_campaign": {"campaign_id": "{campaign_id}"},
    "delete_campaign": {"campaign_id": "{campaign_id}"},
    "export_campaign": {"campaign_id": "{campaign_id}"},
    "update_campaign_tags": {
        "campaign_id": "{campaign_id}",
        "tag_data": {"tag_ids": ["{spare_tag_id}"]},
    },
    # Analytics (UTC)
    "get_overview_stats": {},
    "get_url_daily_stats": {"short_code": "{code}"},
    "get_url_weekly_stats": {"short_code": "{code}"},
    "get_url_geo_stats": {"short_code": "{code}"},
    "get_campaign_summary": {"campaign_id": "{campaign_id}"},
    "get_campaign_users": {"campaign_id": "{campaign_id}"},
    "get_orphan_visits": {},
    # Analytics in the viewer's zone (3.16 / 3.17): local times with its offset
    "get_url_totals": {"short_code": "{code}", "tz": LOCAL_ZONE},
    "get_url_timeseries": {"short_code": "{code}", "tz": LOCAL_ZONE, **_PERIOD},
    "get_url_breakdown": {"short_code": "{code}", "tz": LOCAL_ZONE, **_PERIOD},
    "list_url_visits": {"short_code": "{code}", "tz": LOCAL_ZONE, **_PERIOD},
    "get_campaign_totals": {"campaign_id": "{campaign_id}", "tz": LOCAL_ZONE},
    "get_campaign_timeseries": {"campaign_id": "{campaign_id}", "tz": LOCAL_ZONE, **_PERIOD},
    "get_campaign_breakdown": {"campaign_id": "{campaign_id}", "tz": LOCAL_ZONE, **_PERIOD},
    "list_campaign_recipients": {"campaign_id": "{campaign_id}", "tz": LOCAL_ZONE},
    # Tags
    "list_tags": {},
    "create_tag": {"name": "Fresh"},
    "update_tag": {"tag_id": "{spare_tag_id}", "name": "Renamed"},
    "delete_tag": {"tag_id": "{spare_tag_id}"},
    # Phase 5.3 — curated
    "create_campaign_from_rows": {
        "name": "Spring",
        "original_url": "https://example.com/spring",
        "rows": [{"name": "Ana"}, {"name": "Bea"}],
    },
    "add_redirect_rule": {
        "short_code": "{code}",
        "target_url": "https://example.com/firefox",
        "browser": "firefox",
    },
    "get_url_analytics_summary": {"short_code": "{code}"},
    "list_orphan_visits_grouped": {},
}


def _fill(value, ids: dict):
    if isinstance(value, str):
        return value.format(**ids) if value.startswith("{") and value.endswith("}") else value
    if isinstance(value, list):
        return [_fill(v, ids) for v in value]
    if isinstance(value, dict):
        return {k: _fill(v, ids) for k, v in value.items()}
    return value


def _call(server, name: str, arguments: dict):
    with _bound_access_token(API_KEY):
        return asyncio.run(server.call_tool(name, arguments))


def _date_time_strings(value, path="$"):
    """Every string in the output that looks like a date and a time, with where it is."""
    if isinstance(value, str):
        if _DATETIME_LIKE.match(value):
            yield path, value
    elif isinstance(value, dict):
        for key, item in value.items():
            yield from _date_time_strings(item, f"{path}.{key}")
    elif isinstance(value, list):
        for i, item in enumerate(value):
            yield from _date_time_strings(item, f"{path}[{i}]")


def test_every_tool_is_called(tools):
    """A new tool gets a call here, so the guard covers it."""
    assert set(TOOL_CALLS) == set(tools), (
        f"missing: {sorted(set(tools) - set(TOOL_CALLS))}, "
        f"gone: {sorted(set(TOOL_CALLS) - set(tools))}"
    )


@pytest.mark.parametrize("name", sorted(TOOL_CALLS))
def test_structured_output_matches_the_output_schema(name, mcp_server, tools, seeded):
    tool = tools[name]
    result = _call(mcp_server, name, _fill(TOOL_CALLS[name], seeded))
    output = result.structured_content

    if tool.output_schema is not None:
        assert output is not None, f"{name} declares an outputSchema but returned none"
        validator_class = jsonschema.validators.validator_for(tool.output_schema)
        validator = validator_class(tool.output_schema, format_checker=format_checker)
        errors = sorted(validator.iter_errors(output), key=lambda e: list(e.absolute_path))
        assert not errors, f"{name}: " + "; ".join(
            f"{'/'.join(map(str, e.absolute_path))}: {e.message}" for e in errors
        )

    # Free dicts too (the curated tools', the hand-built ones): a date and a time has an offset.
    naive = [
        f"{path} = {value!r}"
        for path, value in _date_time_strings(output)
        if not _RFC3339.match(value)
    ]
    assert not naive, f"{name} returned dates without a time zone: {naive}"


def test_create_short_url_gives_utc_times_with_z(mcp_server, seeded):
    """The call from the report: the link, and its dates in UTC with `Z`."""
    output = _call(mcp_server, "create_short_url", {"url": "https://example.com/report"})
    link = output.structured_content
    assert link["short_code"]
    assert link["created_at"].endswith("Z")
    assert link["updated_at"].endswith("Z")
    assert link["og_fetched_at"].endswith("Z")


def test_list_urls_gives_utc_times_with_z(mcp_server, seeded):
    output = _call(mcp_server, "list_urls", {}).structured_content
    link = next(u for u in output["urls"] if u["short_code"] == seeded["code"])
    for field in ("created_at", "updated_at", "og_fetched_at", "last_click_at"):
        assert link[field].endswith("Z"), (field, link[field])
    for field in ("valid_since", "valid_until"):
        assert link[field].endswith("Z"), (field, link[field])
    assert link["tags"][0]["created_at"].endswith("Z")


def test_local_analytics_keep_the_viewers_offset(mcp_server, seeded):
    """3.16 / 3.17 give local times with the zone's offset, on purpose: never turned into Z."""
    ids = seeded
    totals = _call(mcp_server, "get_url_totals", {"short_code": ids["code"], "tz": LOCAL_ZONE})
    assert totals.structured_content["last_click_at"].endswith(LOCAL_OFFSET)

    visits = _call(
        mcp_server, "list_url_visits", {"short_code": ids["code"], "tz": LOCAL_ZONE, **_PERIOD}
    ).structured_content["visits"]
    assert visits and all(v["visited_at"].endswith(LOCAL_OFFSET) for v in visits)

    recipients = _call(
        mcp_server,
        "list_campaign_recipients",
        {"campaign_id": ids["campaign_id"], "tz": LOCAL_ZONE},
    ).structured_content["recipients"]
    assert recipients[0]["last_click_at"].endswith(LOCAL_OFFSET)

    campaign = _call(
        mcp_server, "get_campaign_totals", {"campaign_id": ids["campaign_id"], "tz": LOCAL_ZONE}
    ).structured_content
    assert campaign["last_click_at"].endswith(LOCAL_OFFSET)


# ---------------------------------------------------------------------------
# The schema-level check: every response model's datetimes use the shared types
# ---------------------------------------------------------------------------


def _response_models() -> set[type]:
    """The Pydantic models the API answers with, nested ones included."""
    from fastapi.routing import APIRoute
    from pydantic import BaseModel

    from main import app

    found: set[type] = set()

    def visit(annotation) -> None:
        if isinstance(annotation, type) and issubclass(annotation, BaseModel):
            if annotation in found:
                return
            found.add(annotation)
            for field in annotation.model_fields.values():
                visit(field.annotation)
            return
        for arg in typing.get_args(annotation):
            visit(arg)

    def routes(container):
        for route in container:
            if isinstance(route, APIRoute):
                yield route
            # An included router (FastAPI 0.14x wraps it) or a mount: its routes too.
            inner = getattr(route, "original_router", None) or route
            yield from routes(getattr(inner, "routes", None) or ())

    for route in routes(app.routes):
        visit(route.response_model)
        for response in (route.responses or {}).values():
            visit(response.get("model"))
    return found


def _datetime_uses(annotation, extras: tuple = ()):
    """Each datetime in a field's type, with the Annotated metadata around it."""
    from pydantic import AwareDatetime

    if typing.get_origin(annotation) is typing.Annotated:
        base, *metadata = typing.get_args(annotation)
        yield from _datetime_uses(base, (*extras, *metadata))
    elif annotation is datetime or annotation is AwareDatetime:
        yield annotation, extras
    else:
        for arg in typing.get_args(annotation):
            yield from _datetime_uses(arg)


def test_every_response_datetime_uses_the_shared_types():
    """A UTC time is `UtcDateTime` (Z); a local one, the 3.16/3.17 analytics', `LocalDateTime`
    (an offset required). A bare `datetime` would go out naive again."""
    from pydantic import AwareDatetime

    from server.schemas.datetimes import UTC_JSON

    models = _response_models()
    assert len(models) > 30  # every route's, not an empty walk
    bare = []
    uses = 0
    for model in models:
        for name, field in model.model_fields.items():
            for base, metadata in _datetime_uses(field.annotation, tuple(field.metadata)):
                uses += 1
                if base is AwareDatetime:
                    continue  # LocalDateTime: an offset is required to build it
                if UTC_JSON not in metadata:
                    bare.append(f"{model.__module__}.{model.__qualname__}.{name}")
    assert uses > 20
    assert not bare, f"datetime fields not declared UtcDateTime or LocalDateTime: {sorted(bare)}"


# ---------------------------------------------------------------------------
# The API itself: Z out, and what it accepts unchanged
# ---------------------------------------------------------------------------


# Naive and Z only: SQLite (the suite's) keeps another offset's wall-clock time and drops the offset,
# where PostgreSQL's timestamptz converts it.
@pytest.mark.parametrize("valid_since", ["2030-01-02T03:04:05", "2030-01-02T03:04:05Z"])
def test_the_api_reads_a_time_as_before_and_writes_it_with_z(
    client, auth_headers, monkeypatch, valid_since
):
    """Naive (taken as UTC) or Z in, as before; the same UTC moment out, with Z."""

    async def _no_preview(url: str) -> OpenGraphMetadata:
        return OpenGraphMetadata()

    monkeypatch.setattr("server.app.urls.fetch_opengraph_metadata", _no_preview)
    response = client.post(
        "/api/v1/urls",
        json={"url": "https://example.com/later", "valid_since": valid_since},
        headers=auth_headers,
    )
    assert response.status_code == 201, response.text
    link = response.json()
    assert link["valid_since"] == "2030-01-02T03:04:05Z"
    assert _RFC3339.match(link["created_at"]) and link["created_at"].endswith("Z")
