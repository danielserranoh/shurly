"""
A NUL character (U+0000) in a request is a 4xx, never a 500 (ROADMAP 6.3, the class of #132).

PostgreSQL can't hold NUL in text: psycopg2 refuses it ("A string literal cannot contain NUL
(0x00) characters"), and each such request answered 500, the public short-link host's included.
SQLite takes it, so the suite never saw it; the PostgreSQL test below runs the requests that did.

- `server/utils/nul.py`'s middleware, before any route: a 400 for NUL in the path or the query
  (plain, even on the short-link host: no link has one); a 422 in FastAPI's shape for NUL in a
  JSON body, where it is. It parses a JSON body only when its bytes hold `\\x00` or `\\u0000`.
- A safety net for what the middleware doesn't see: psycopg2's NUL error is a 422, any other
  ValueError the 500 it was.
- uvicorn's parsers (httptools and h11) refuse NUL in a header themselves, with a 400: nothing
  of the app's to check there.
"""

import json
import re

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from server.core.models import URL
from server.utils import nul
from server.utils.domain import get_or_create_default_domain
from tests.test_analytics_postgres import pg_client, pg_session  # noqa: F401 — fixtures

BROWSER = "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8"
MESSAGE = "A request can't contain a NUL character (U+0000)"
RULE = {"conditions": [{"type": "device", "value": "ios"}], "target_url": "https://e.com"}


@pytest.fixture
def link(db_session, test_user) -> URL:
    url = URL(
        short_code="abc123",
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
        "/%00",
        "/abc%00def",
        "/abc%00def/track",
        "/api/v1/urls/abc%00",
        "/api/v1/urls?q=%00",
        "/api/v1/urls?q=a%00b",
        "/api/v1/analytics/campaigns/00000000-0000-0000-0000-000000000000/recipients?q=a%00b",
        "/?utm_source=%00",
    ],
)
def test_a_nul_in_the_path_or_query_is_a_400(client, auth_headers, link, path):
    response = client.get(path, headers=auth_headers, follow_redirects=False)

    assert (response.status_code, response.json()) == (400, {"detail": MESSAGE})


def test_even_a_browser_on_the_short_link_host_gets_a_plain_400(client):
    """No link has a NUL in it, so no one was given this one: not the unavailable-link page."""
    response = client.get("/abc%00def", headers={"accept": BROWSER})

    assert (response.status_code, response.json()) == (400, {"detail": MESSAGE})


@pytest.mark.parametrize(
    "method, path, body, where",
    [
        ("POST", "/api/v1/urls", {"url": "https://e.com/x", "title": "a\x00b"}, ["title"]),
        ("POST", "/api/v1/urls", {"url": "https://example.com/\x00"}, ["url"]),
        ("PATCH", "/api/v1/urls/abc123", {"title": "a\x00b"}, ["title"]),
        (
            "POST",
            "/api/v1/urls/abc123/rules",
            {**RULE, "conditions": [{"type": "device", "value": "i\x00os"}]},
            ["conditions", 0, "value"],
        ),
        (
            "POST",
            "/api/v1/campaigns",
            {"name": "N", "original_url": "https://e.com", "csv_data": "name\nA\x00na"},
            ["csv_data"],
        ),
        ("PATCH", "/api/v1/urls/abc123", {"ti\x00tle": "x"}, ["ti\x00tle"]),
    ],
)
def test_a_nul_in_a_json_body_is_a_422_where_it_is(
    client, auth_headers, link, method, path, body, where
):
    response = client.request(method, path, json=body, headers=auth_headers)

    assert response.status_code == 422
    (error,) = response.json()["detail"]
    assert (error["type"], error["loc"], error["msg"]) == (
        "string_nul",
        ["body", *where],
        "Text can't contain a NUL character (U+0000)",
    )


def test_an_escaped_backslash_u0000_is_six_plain_characters(client, auth_headers):
    body = '{"url": "https://example.com/x", "title": "\\\\u0000"}'  # the title \u0000, no NUL

    response = client.post(
        "/api/v1/urls",
        content=body,
        headers={**auth_headers, "content-type": "application/json"},
    )

    assert (response.status_code, response.json()["title"]) == (201, "\\u0000")


def test_a_json_body_without_either_isnt_parsed_twice(client, auth_headers, monkeypatch):
    def parse(*_args, **_kwargs):
        raise AssertionError("the middleware parsed a body with no NUL in it")

    monkeypatch.setattr(nul, "_nul_in", parse)  # the parse: only for a body that may hold one

    response = client.post(
        "/api/v1/urls", json={"url": "https://example.com/plain"}, headers=auth_headers
    )

    assert response.status_code == 201


def test_a_body_that_isnt_json_is_left_to_its_route(client, auth_headers):
    response = client.post(
        "/api/v1/urls",
        content=b'{"url": "https://e.com/x", "title": "a\\u0000b"}',  # JSON, but not said to be
        headers={**auth_headers, "content-type": "text/plain"},
    )

    assert response.status_code == 422
    assert "NUL" not in response.text  # FastAPI's own answer, not the middleware's


def test_an_mcp_call_with_a_nul_is_a_422_before_the_mcp_sees_it(client):
    """The curated tools write to the database themselves, not through the API: over HTTP
    their arguments come in the JSON-RPC body, which the middleware reads first."""
    call = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "tools/call",
        "params": {"name": "add_redirect_rule", "arguments": {"device": "i\x00os"}},
    }

    response = client.post(
        "/mcp", content=json.dumps(call), headers={"content-type": "application/json"}
    )

    assert response.status_code == 422
    assert response.json()["detail"][0]["loc"] == ["body", "params", "arguments", "device"]


# ---------------------------------------------------------------------------
# The safety net
# ---------------------------------------------------------------------------


def test_the_safety_net_turns_psycopgs_nul_error_into_a_422():
    app = FastAPI()
    app.add_exception_handler(ValueError, nul.nul_value_error)

    @app.get("/nul")
    def refused():
        raise ValueError("A string literal cannot contain NUL (0x00) characters.")

    @app.get("/other")
    def other():
        raise ValueError("something else")

    client = TestClient(app, raise_server_exceptions=False)

    assert (client.get("/nul").status_code, client.get("/nul").json()) == (
        422,
        {"detail": "Text can't contain a NUL character (U+0000)"},
    )
    assert client.get("/other").status_code == 500  # any other ValueError, as it was


def test_the_app_has_the_safety_net():
    from main import app

    assert app.exception_handlers[ValueError] is nul.nul_value_error


# ---------------------------------------------------------------------------
# On PostgreSQL, which refuses NUL
# ---------------------------------------------------------------------------


def test_psycopgs_error_is_the_one_the_safety_net_knows(pg_session):  # noqa: F811
    from sqlalchemy import text

    with pytest.raises(ValueError, match=re.escape(nul.PSYCOPG_NUL)):
        pg_session.execute(text("SELECT :v"), {"v": "a\x00b"})


def test_no_request_with_a_nul_is_a_500_on_postgresql(pg_client, pg_session):  # noqa: F811
    from server.core.auth import create_access_token, hash_password
    from server.core.models import User

    user = User(email="nul@griddo.io", password_hash=hash_password("x"), is_active=True)
    pg_session.add(user)
    pg_session.commit()
    headers = {"Authorization": f"Bearer {create_access_token(data={'sub': user.email})}"}
    requests = [
        ("GET", "/%00", None),
        ("GET", "/abc%00def", None),
        ("GET", "/abc%00def/track", None),
        ("GET", "/api/v1/urls?q=%00", None),
        ("GET", "/api/v1/urls/abc%00", None),
        ("POST", "/api/v1/urls", {"url": "https://example.com/x", "title": "a\x00b"}),
        ("POST", "/api/v1/urls", {"url": "https://example.com/\x00"}),
    ]

    statuses = {
        (method, path): pg_client.request(method, path, json=body, headers=headers).status_code
        for method, path, body in requests
    }

    assert set(statuses.values()) <= {400, 422}, statuses
