"""
An auto-generated MCP tool answers what its REST route answers.

`FastMCP.from_fastapi` turns each route into a tool that calls the API over an in-process HTTP
client (mcp_server/server.py). Nothing checked that the answer survives the trip: a renamed
argument, a body flattened the wrong way, a query parameter dropped or a response reshaped would
leave every tool listed and every test green while the assistant read something the web app
doesn't. tests/test_mcp_output_dates.py validates each tool's output against its schema, never
against the API.

Here each tool in a representative set, reads and writes, is called through the real in-process
MCP server, and its REST route through TestClient, as the same user (one API key, bound for the
MCP the way its auth middleware binds it, sent as a bearer to REST) with the same arguments, and
the MCP's `structured_content` must equal the REST JSON.

Writes can't be called twice and compared: a second create makes another link, with its own
code, id and times. So a write is made through one surface and the link it made or changed is
read back through both, and the read must equal the write's own answer.
"""

from __future__ import annotations

import asyncio
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone

import pytest

fastmcp = pytest.importorskip("fastmcp")

from server.core.models import (  # noqa: E402
    URL,
    Campaign,
    OrganizationMember,
    OrgRole,
    RedirectRule,
    Tag,
    URLType,
    User,
    Visitor,
)
from server.utils import organization as org_service  # noqa: E402
from server.utils.domain import get_or_create_default_domain  # noqa: E402
from server.utils.opengraph import OpenGraphMetadata  # noqa: E402

API_KEY = "roundtrip-key"
BEARER = {"Authorization": f"Bearer {API_KEY}"}
ZONE = "Europe/Madrid"


# ---------------------------------------------------------------------------
# The server, the caller and the data
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def mcp_server():
    """Built once: its generated tools call `main.app`, which `client` binds to each test's
    database (the same dependency override serves both surfaces)."""
    from main import app
    from mcp_server.server import build_mcp_for_app

    return build_mcp_for_app(app)


@pytest.fixture(scope="module")
def tools(mcp_server) -> dict:
    return {tool.name: tool for tool in asyncio.run(mcp_server.list_tools())}


@pytest.fixture
def preview(monkeypatch):
    """Creating a link fetches its page's preview: a fixed one, looked up where the route does,
    so both surfaces store the same thing and nothing reaches the network."""

    async def _preview(url: str) -> OpenGraphMetadata:
        return OpenGraphMetadata(title="The page", description="What the page says")

    monkeypatch.setattr("server.app.urls.fetch_opengraph_metadata", _preview)


@contextmanager
def _bound_access_token(token: str):
    """Bind `token`, as the real verifier reads it, the way the MCP SDK's auth middleware does for
    each HTTP request; the generated tools forward it to the API (tests/test_mcp_output_dates.py)."""
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


def _mcp(server, tools: dict, name: str, arguments: dict):
    """The tool's structured output, as the API's JSON.

    The envelope: an MCP structured output is always an object, so fastmcp wraps a route that
    answers a JSON array (`list_redirect_rules`) as `{"result": [...]}` and marks the tool's
    outputSchema with `x-fastmcp-wrap-result`. Unwrapped here, by that mark only, so an object
    answer that happens to have a `result` key would still be compared whole.
    """
    with _bound_access_token(API_KEY):
        result = asyncio.run(server.call_tool(name, arguments))
    output = result.structured_content
    assert output is not None, f"{name} returned no structured content"
    schema = tools[name].output_schema or {}
    if schema.get("x-fastmcp-wrap-result"):
        assert set(output) == {"result"}, output
        return output["result"]
    return output


def _rest(client, method: str, path: str, *, params=None, json=None):
    response = client.request(method, path, params=params, json=json, headers=BEARER)
    assert response.is_success, f"{method} {path}: {response.status_code} {response.text}"
    return response.json()


@pytest.fixture
def seeded(client, db_session, preview) -> dict:
    """An owner of the organization with an API key; two organization links, one tagged with
    clicks, an open and a rule; a campaign with a recipient; and someone else's personal link,
    which neither surface may show."""
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    domain = get_or_create_default_domain(db_session)
    organization = org_service.get_or_create_default_organization(db_session)

    owner = User(email="owner@example.com", is_active=True)
    owner.set_api_key(API_KEY)
    stranger = User(email="stranger@example.com", is_active=True)
    db_session.add_all([owner, stranger])
    db_session.flush()
    db_session.add(
        OrganizationMember(organization_id=organization.id, user_id=owner.id, role=OrgRole.OWNER)
    )

    tag = Tag(name="launch", display_name="Launch", color="blue-500", created_by=owner.id)
    spare = Tag(name="spare", display_name="Spare", color="green-500", created_by=owner.id)
    db_session.add_all([tag, spare])
    db_session.flush()

    common = {"domain_id": domain.id, "created_by": owner.id, "organization_id": organization.id}
    link = URL(
        short_code="trip01",
        original_url="https://example.com/launch",
        url_type=URLType.STANDARD,
        title="Launch",
        page_og_title="Launch, the page",
        page_fetched_at=now - timedelta(days=2),
        last_click_at=now - timedelta(hours=1),
        valid_until=now + timedelta(days=30),
        **common,
    )
    link.tags.append(tag)
    other = URL(
        short_code="trip02",
        original_url="https://example.com/other",
        url_type=URLType.CUSTOM,
        title="Other",
        **common,
    )
    hidden = URL(
        short_code="trip03",
        original_url="https://example.com/hidden",
        url_type=URLType.STANDARD,
        domain_id=domain.id,
        created_by=stranger.id,  # personal: no organization_id
    )
    campaign = Campaign(
        name="Autumn",
        original_url="https://example.com/autumn",
        csv_columns=["name"],
        created_by=owner.id,
        organization_id=organization.id,
    )
    db_session.add_all([link, other, hidden, campaign])
    db_session.flush()
    recipient = URL(
        short_code="autumn1",
        original_url="https://example.com/autumn",
        url_type=URLType.CAMPAIGN,
        campaign_id=campaign.id,
        user_data={"name": "Ana"},
        **common,
    )
    db_session.add(recipient)
    db_session.flush()

    visit = {"ip": "203.0.113.0", "country": "ES", "user_agent": "Mozilla/5.0 (Macintosh)"}
    db_session.add_all(
        [
            Visitor(
                url_id=link.id, short_code="trip01", visited_at=now - timedelta(hours=1), **visit
            ),
            Visitor(
                url_id=link.id, short_code="trip01", visited_at=now - timedelta(days=1), **visit
            ),
            Visitor(
                url_id=link.id,
                short_code="trip01",
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
    db_session.add(
        RedirectRule(
            url_id=link.id,
            priority=1,
            conditions=[{"type": "device", "value": "mobile"}],
            target_url="https://m.example.com/launch",
        )
    )
    db_session.commit()
    return {
        "code": "trip01",
        "tag_id": str(tag.id),
        "spare_tag_id": str(spare.id),
        "campaign_id": str(campaign.id),
    }


# ---------------------------------------------------------------------------
# Reads: the same call through both surfaces
# ---------------------------------------------------------------------------

# (tool, its arguments, the REST path, its query parameters). `{code}`, `{tag_id}`… are the seeded
# ids. The tool takes the path parameters and the query parameters as plain arguments.
READS = [
    ("list_urls", {}, "/api/v1/urls", {}),
    (
        "list_urls",
        {"q": "launch", "tags": "{tag_id}", "limit": 5},
        "/api/v1/urls",
        {"q": "launch", "tags": "{tag_id}", "limit": 5},
    ),
    ("list_urls", {"url_type": ["custom"]}, "/api/v1/urls", {"url_type": ["custom"]}),
    ("get_url", {"short_code": "{code}"}, "/api/v1/urls/{code}", {}),
    (
        "get_url_totals",
        {"short_code": "{code}", "tz": ZONE},
        "/api/v1/analytics/urls/{code}/totals",
        {"tz": ZONE},
    ),
    (
        "get_url_totals",
        {"short_code": "{code}"},
        "/api/v1/analytics/urls/{code}/totals",
        {},
    ),
    ("list_tags", {}, "/api/v1/tags", {}),
    ("list_tags", {"search": "lau"}, "/api/v1/tags", {"search": "lau"}),
    # Cheap extras: an array answer (the envelope), a preview, campaigns.
    ("list_redirect_rules", {"short_code": "{code}"}, "/api/v1/urls/{code}/rules", {}),
    ("get_url_preview", {"short_code": "{code}"}, "/api/v1/urls/{code}/preview", {}),
    ("list_campaigns", {}, "/api/v1/campaigns", {}),
    ("get_campaign", {"campaign_id": "{campaign_id}"}, "/api/v1/campaigns/{campaign_id}", {}),
    (
        "get_campaign_totals",
        {"campaign_id": "{campaign_id}", "tz": ZONE},
        "/api/v1/analytics/campaigns/{campaign_id}/totals",
        {"tz": ZONE},
    ),
]


def _fill(value, ids: dict):
    if isinstance(value, str):
        return value.format(**ids) if "{" in value else value
    if isinstance(value, list):
        return [_fill(v, ids) for v in value]
    if isinstance(value, dict):
        return {k: _fill(v, ids) for k, v in value.items()}
    return value


def test_every_read_tool_here_is_a_generated_one(tools):
    """The tools compared are the generated ones (the curated have no route to compare with)."""
    from mcp_server.server import MCP_TOOL_NAMES

    generated = set(MCP_TOOL_NAMES.values())
    names = {name for name, *_ in READS} | {"create_short_url", "update_url"}
    assert names <= generated
    assert names <= set(tools)


@pytest.mark.parametrize(
    ("name", "arguments", "path", "params"),
    READS,
    ids=[f"{name}-{i}" for i, (name, *_) in enumerate(READS)],
)
def test_a_read_tool_answers_what_its_route_answers(
    name, arguments, path, params, client, mcp_server, tools, seeded
):
    rest = _rest(client, "GET", _fill(path, seeded), params=_fill(params, seeded))
    mcp = _mcp(mcp_server, tools, name, _fill(arguments, seeded))

    assert mcp == rest
    assert rest  # not two empty answers agreeing


def test_neither_surface_shows_someone_elses_personal_link(client, mcp_server, tools, seeded):
    """The comparison above is over what the caller may see: the same scoping on both sides."""
    rest = _rest(client, "GET", "/api/v1/urls")
    codes = {link["short_code"] for link in rest["urls"]}
    assert codes == {"trip01", "trip02", "autumn1"}
    assert {
        link["short_code"] for link in _mcp(mcp_server, tools, "list_urls", {})["urls"]
    } == codes


# ---------------------------------------------------------------------------
# Writes: made through one surface, read back through both
# ---------------------------------------------------------------------------


def test_a_link_created_through_the_mcp_reads_the_same_through_both(
    client, mcp_server, tools, seeded
):
    created = _mcp(
        mcp_server,
        tools,
        "create_short_url",
        {"url": "https://example.com/new", "title": "New", "forward_parameters": False},
    )
    assert created["title"] == "New"
    assert created["page_og_title"] == "The page"  # the stubbed fetch, stored

    code = created["short_code"]
    assert _rest(client, "GET", f"/api/v1/urls/{code}") == created
    assert _mcp(mcp_server, tools, "get_url", {"short_code": code}) == created


def test_a_link_created_through_rest_reads_the_same_through_the_mcp(
    client, mcp_server, tools, seeded
):
    created = _rest(
        client,
        "POST",
        "/api/v1/urls",
        json={"url": "https://example.com/new", "title": "New", "forward_parameters": False},
    )
    assert _mcp(mcp_server, tools, "get_url", {"short_code": created["short_code"]}) == created


def test_the_same_create_through_both_differs_only_in_what_makes_a_link_new(
    client, mcp_server, tools, seeded
):
    """Same arguments, two links: apart from its identity and its times, the same link.

    `short_code`, `short_url` and `id` are drawn fresh per link; `created_at`, `updated_at` and
    `page_fetched_at` (and its deprecated copy `og_fetched_at`) are when each was made and
    fetched. Everything else (the defaults each
    surface fills in, the stored preview, the visibility) must agree.
    """
    arguments = {"url": "https://example.com/twice", "title": "Twice", "crawlable": True}
    via_rest = _rest(client, "POST", "/api/v1/urls", json=arguments)
    via_mcp = _mcp(mcp_server, tools, "create_short_url", arguments)

    new_each_time = {
        "id",
        "short_code",
        "short_url",
        "created_at",
        "updated_at",
        "page_fetched_at",
        "og_fetched_at",
    }
    assert set(via_mcp) == set(via_rest)
    assert new_each_time <= set(via_rest)
    assert via_mcp["short_code"] != via_rest["short_code"]

    def same_link(link: dict) -> dict:
        return {key: value for key, value in link.items() if key not in new_each_time}

    assert same_link(via_mcp) == same_link(via_rest)


def test_a_link_updated_through_the_mcp_reads_the_same_through_both(
    client, mcp_server, tools, seeded
):
    code = seeded["code"]
    updated = _mcp(
        mcp_server,
        tools,
        "update_url",
        {"short_code": code, "title": "Relaunch", "forward_parameters": False, "crawlable": True},
    )
    assert (updated["title"], updated["forward_parameters"], updated["crawlable"]) == (
        "Relaunch",
        False,
        True,
    )
    assert _rest(client, "GET", f"/api/v1/urls/{code}") == updated
    assert _mcp(mcp_server, tools, "get_url", {"short_code": code}) == updated


def test_the_same_update_through_rest_answers_what_the_mcp_did(client, mcp_server, tools, seeded):
    """An update is idempotent: the same change again through REST leaves the link as the MCP
    left it, and answers it whole, `updated_at` included (nothing changed, so nothing is written)."""
    code = seeded["code"]
    change = {"title": "Relaunch", "forward_parameters": False}
    via_mcp = _mcp(mcp_server, tools, "update_url", {"short_code": code, **change})
    via_rest = _rest(client, "PATCH", f"/api/v1/urls/{code}", json=change)

    assert via_rest == via_mcp
