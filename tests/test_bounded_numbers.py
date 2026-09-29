"""
Phase 6.3 — every number a request carries has bounds, so an absurd one is a 422, never a 500.

`?days=1000000000` overflowed the date arithmetic; a `?skip=`, or a `?page=` times its size,
past 2^63 overflowed the query's OFFSET; a `max_visits` or a rule's `priority` past 2^31
overflowed its integer column. Each answered 500 (on PostgreSQL too), which 6.4's alerting
would page on.

The guard reads the OpenAPI document and the MCP's tools: every integer query or path
parameter, request-body field and tool argument has a maximum, and a minimum, which is 0 or
more unless NEGATIVES_ALLOWED says why not. So a new one can't bring the 500s back.
"""

import asyncio
from functools import partial

import pytest

from server.core.models import URL
from server.utils.domain import get_or_create_default_domain

HUGE = 10**20  # past int64: what overflowed

# Integers that may be negative, and why. Anything else starts at 0 or more.
NEGATIVES_ALLOWED = {
    "RedirectRuleCreate.priority": "lower runs first: a negative puts a rule ahead of the default 0",
    "RedirectRuleUpdate.priority": "the same",
    "create_redirect_rule.priority": "the same, as an MCP tool",
    "update_redirect_rule.priority": "the same, as an MCP tool",
    "add_redirect_rule.priority": "the same, as a curated MCP tool",
}


ALTERNATIVES = ("anyOf", "oneOf", "allOf")  # an optional field's integer is one of its `anyOf`


def _bounds(schema: dict) -> tuple | None:
    """(minimum, maximum) of an integer's schema; None if it isn't an integer's."""
    parts = [schema, *(part for key in ALTERNATIVES for part in schema.get(key, []))]
    if not any(part.get("type") == "integer" for part in parts):
        return None
    low = next((p[k] for p in parts for k in ("minimum", "exclusiveMinimum") if k in p), None)
    high = next((p[k] for p in parts for k in ("maximum", "exclusiveMaximum") if k in p), None)
    return low, high


def _integers(schema: dict, where: str, definitions: dict, seen=frozenset()) -> dict[str, tuple]:
    """Each integer in `schema`, by where it is: into its `$ref`s (`Model.field`), a list's
    items (`where[]`) and an object's properties (`where.field`)."""
    if "$ref" in schema:
        name = schema["$ref"].rsplit("/", 1)[-1]
        return (
            {} if name in seen else _integers(definitions[name], name, definitions, seen | {name})
        )
    if (bounds := _bounds(schema)) is not None:
        return {where: bounds}
    found: dict[str, tuple] = {}
    for part in (part for key in ALTERNATIVES for part in schema.get(key, [])):
        found |= _integers(part, where, definitions, seen)
    if isinstance(schema.get("items"), dict):
        found |= _integers(schema["items"], f"{where}[]", definitions, seen)
    for field, prop in schema.get("properties", {}).items():
        found |= _integers(prop, f"{where}.{field}", definitions, seen)
    return found


def _openapi_integers() -> dict[str, tuple]:
    """Every integer the API takes: `GET /path ?name` for a parameter, `Model.field` in a body."""
    from main import app

    spec = app.openapi()
    definitions = spec["components"]["schemas"]
    found: dict[str, tuple] = {}
    for path, item in spec["paths"].items():
        for method, operation in item.items():
            route = f"{method.upper()} {path}"
            for parameter in operation.get("parameters", []):
                where = f"{route} ?{parameter['name']}"
                found |= _integers(parameter.get("schema", {}), where, definitions)
            for media in operation.get("requestBody", {}).get("content", {}).values():
                found |= _integers(media.get("schema", {}), f"{route} body", definitions)
    return found


def _tool_integers() -> dict[str, tuple]:
    """Every integer an MCP tool takes, generated or curated: `tool.argument`."""
    pytest.importorskip("fastmcp")
    from mcp_server.server import _build_mcp_server

    found: dict[str, tuple] = {}
    for tool in asyncio.run(_build_mcp_server().list_tools()):
        found |= _integers(tool.parameters, tool.name, tool.parameters.get("$defs", {}))
    return found


def _unbounded(integers: dict[str, tuple]) -> list[str]:
    problems = []
    for where, (low, high) in sorted(integers.items()):
        if high is None:
            problems.append(f"{where}: no maximum")
        if low is None:
            problems.append(f"{where}: no minimum")
        elif low < 0 and where not in NEGATIVES_ALLOWED:
            problems.append(
                f"{where}: may be negative ({low}), with no reason in NEGATIVES_ALLOWED"
            )
    return problems


def test_every_integer_the_api_takes_is_bounded():
    integers = _openapi_integers()

    assert "GET /api/v1/urls ?skip" in integers and "URLCreate.max_visits" in integers  # not blind
    assert _unbounded(integers) == []


def test_every_integer_an_mcp_tool_takes_is_bounded():
    integers = _tool_integers()

    assert "list_orphan_visits_grouped.since_days" in integers  # a curated tool's, not blind
    assert _unbounded(integers) == []


def test_each_negative_has_its_reason_and_is_still_taken():
    """The allowlist names only what exists, so it can't outlive a field."""
    assert set(NEGATIVES_ALLOWED) <= set(_openapi_integers()) | set(_tool_integers())


@pytest.fixture
def link(db_session, test_user) -> URL:
    url = URL(
        short_code="bounds",
        original_url="https://example.com",
        created_by=test_user.id,
        domain_id=get_or_create_default_domain(db_session).id,
    )
    db_session.add(url)
    db_session.commit()
    return url


@pytest.mark.parametrize(
    "path",
    [
        f"/api/v1/analytics/urls/bounds/geo?days={HUGE}",
        "/api/v1/analytics/urls/bounds/geo?days=0",
        "/api/v1/analytics/urls/bounds/geo?days=-5",
        f"/api/v1/urls?skip={HUGE}",
        f"/api/v1/campaigns?skip={HUGE}",
        f"/api/v1/analytics/orphan-visits?skip={HUGE}",
        f"/api/v1/analytics/urls/bounds/visits?page={HUGE}",
        f"/api/v1/analytics/campaigns/00000000-0000-0000-0000-000000000000/recipients?page={HUGE}",
    ],
)
def test_an_absurd_number_is_a_422(client, auth_headers, link, path):
    assert client.get(path, headers=auth_headers).status_code == 422


@pytest.mark.parametrize(
    "method, path, body",
    [
        ("POST", "/api/v1/urls", {"url": "https://example.com", "max_visits": HUGE}),
        ("PATCH", "/api/v1/urls/bounds", {"max_visits": HUGE}),
        (
            "POST",
            "/api/v1/urls/bounds/rules",
            {
                "priority": HUGE,
                "conditions": [{"type": "device", "value": "ios"}],
                "target_url": "https://e.com",
            },
        ),
    ],
)
def test_an_absurd_number_in_a_body_is_a_422(client, auth_headers, link, method, path, body):
    assert client.request(method, path, json=body, headers=auth_headers).status_code == 422


def test_the_largest_still_works(client, auth_headers, link):
    """The bounds are far past anything real: the largest of each is taken."""
    assert client.get("/api/v1/urls?skip=1000000000", headers=auth_headers).status_code == 200
    response = client.patch(
        "/api/v1/urls/bounds", json={"max_visits": 2**31 - 1}, headers=auth_headers
    )
    assert (response.status_code, response.json()["max_visits"]) == (200, 2**31 - 1)


@pytest.mark.parametrize(
    "tool, name, value, others",
    [
        ("get_url_analytics_summary", "days", 91, {"short_code": "bounds"}),
        ("list_orphan_visits_grouped", "since_days", 0, {}),
        ("list_orphan_visits_grouped", "limit_groups", 201, {}),
        (
            "add_redirect_rule",
            "priority",
            HUGE,
            {"short_code": "bounds", "target_url": "https://e.com", "device": "ios"},
        ),
    ],
)
def test_a_curated_tool_turns_an_absurd_number_away(tool, name, value, others):
    """Before it runs: its arguments are checked against the bounds its schema advertises."""
    pytest.importorskip("fastmcp")
    from fastmcp.exceptions import ValidationError

    from mcp_server.server import _build_mcp_server

    with pytest.raises(ValidationError, match=name):
        asyncio.run(_build_mcp_server().call_tool(tool, {name: value, **others}))


# Each curated tool's own check of a number, called with nothing but it and what it needs
CURATED_CHECKS = {
    ("get_url_analytics_summary", "days"): {"short_code": "bounds"},
    ("list_orphan_visits_grouped", "since_days"): {},
    ("list_orphan_visits_grouped", "limit_groups"): {},
}


@pytest.mark.parametrize("tool, name", list(CURATED_CHECKS))
def test_a_curated_tool_advertises_the_range_it_checks(tool, name):
    """Its schema turns away what its function would, neither more nor less."""
    from mcp_server import curated

    low, high = _tool_integers()[f"{tool}.{name}"]
    check = partial(getattr(curated, tool), None, None, **CURATED_CHECKS[(tool, name)])
    for outside in (low - 1, high + 1):
        with pytest.raises(ValueError, match=name):
            check(**{name: outside})
    for inside in (low, high):
        try:
            check(**{name: inside})
        except ValueError as error:
            pytest.fail(f"{tool} refuses {name}={inside}, which its schema takes: {error}")
        except Exception:
            pass  # past its check, it wants a database: this one has none
