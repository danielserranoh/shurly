"""
Phase 5.6.0 — usage log: one JSON line per HTTP request and per MCP tool call.

The dogfood (5.6) needs per-tool counts, error rates and durations. In the
access log every MCP call is a `POST /mcp/`: the tool name travels inside the
JSON-RPC body, so the MCP layer logs each call itself. The HTTP request line
carries the request id, so a tool call can be followed through the API call it
makes (3.9.6).

Lines go to stderr: under the stdio transport, stdout is the JSON-RPC channel.

fastmcp also logs each failed call itself, with a traceback. For a failed API
call that line leaves out the response body, which can echo the arguments.
"""

from __future__ import annotations

import asyncio
import importlib
import json
import logging
from contextlib import contextmanager

import pytest
from fastapi.testclient import TestClient


def _events(stderr: str, event: str) -> list[dict]:
    """The JSON event lines of one kind in captured stderr, in order."""
    found = []
    for line in stderr.splitlines():
        try:
            record = json.loads(line)
        except ValueError:
            continue
        if isinstance(record, dict) and record.get("event") == event:
            found.append(record)
    return found


class TestHttpRequestLine:
    def test_each_request_logs_one_json_line(self, client: TestClient, capsys):
        capsys.readouterr()
        response = client.get("/api/v1/health", headers={"x-request-id": "rid-http-1"})

        [line] = _events(capsys.readouterr().err, "http.request")
        assert line["request_id"] == "rid-http-1" == response.headers["x-request-id"]
        assert line["method"] == "GET"
        assert line["path"] == "/api/v1/health"
        assert line["status"] == 200
        assert line["duration_ms"] >= 0
        assert line["ts"].endswith("+00:00")

    def test_generated_request_id_matches_the_response_header(self, client: TestClient, capsys):
        capsys.readouterr()
        response = client.get("/api/v1/health")

        [line] = _events(capsys.readouterr().err, "http.request")
        assert line["request_id"] == response.headers["x-request-id"]

    def test_status_is_the_one_sent_to_the_client(self, client: TestClient, capsys):
        capsys.readouterr()
        response = client.get("/api/v1/urls")  # no credentials

        [line] = _events(capsys.readouterr().err, "http.request")
        assert response.status_code >= 400
        assert line["status"] == response.status_code

    def test_query_string_stays_out_of_the_log(self, client: TestClient, capsys):
        capsys.readouterr()
        client.get("/api/v1/health?token=do-not-log-me")

        stderr = capsys.readouterr().err
        [line] = _events(stderr, "http.request")
        assert line["path"] == "/api/v1/health"
        assert "do-not-log-me" not in stderr


# ---------------------------------------------------------------------------
# MCP tool calls
# ---------------------------------------------------------------------------


@contextmanager
def _signed_in_as(user):
    """Bind an AccessToken for `user` the way `ShurlyTokenVerifier` does."""
    from fastmcp.server.auth import AccessToken
    from mcp.server.auth.middleware.auth_context import auth_context_var
    from mcp.server.auth.middleware.bearer_auth import AuthenticatedUser

    access = AccessToken(
        token=user.api_key,
        client_id=str(user.id),
        scopes=[],
        claims={"sub": user.email, "user_id": str(user.id)},
    )
    reset_token = auth_context_var.set(AuthenticatedUser(access))
    try:
        yield
    finally:
        auth_context_var.reset(reset_token)


@pytest.fixture
def mcp_on_test_db(db_session):
    """MCP server whose generated tools call a FastAPI app bound to the test DB."""
    pytest.importorskip("fastmcp")
    from main import app
    from mcp_server.server import build_mcp_for_app
    from server.core import get_db

    app.dependency_overrides[get_db] = lambda: db_session
    try:
        yield build_mcp_for_app(app)
    finally:
        app.dependency_overrides.pop(get_db, None)


@pytest.fixture
def signed_in_user(db_session, test_user):
    test_user.api_key = "usage-log-key"
    db_session.commit()
    return test_user


class TestMcpToolCallLine:
    def test_successful_call_logs_ok_with_user_and_argument_names(
        self, mcp_on_test_db, signed_in_user, capsys
    ):
        capsys.readouterr()
        with _signed_in_as(signed_in_user):
            asyncio.run(mcp_on_test_db.call_tool("list_urls", {"q": "report", "skip": 0}))

        [line] = _events(capsys.readouterr().err, "mcp.tool_call")
        assert line["tool"] == "list_urls"
        assert line["outcome"] == "ok"
        assert line["error_type"] is None
        assert line["http_status"] is None
        assert line["user_id"] == str(signed_in_user.id)
        assert line["args"] == ["q", "skip"]
        assert line["duration_ms"] >= 0
        # A direct call has no HTTP request around it (as under stdio).
        assert line["request_id"] is None

    def test_failed_call_logs_the_error_and_its_http_status(self, mcp_on_test_db, capsys):
        from fastmcp.exceptions import ToolError

        capsys.readouterr()
        with pytest.raises(ToolError, match="401"):  # the caller still gets the error
            asyncio.run(mcp_on_test_db.call_tool("get_current_user_info", {}))

        [line] = _events(capsys.readouterr().err, "mcp.tool_call")
        assert line["tool"] == "get_current_user_info"
        assert line["outcome"] == "error"
        # The underlying cause, not fastmcp's ToolError wrapper around it.
        assert line["error_type"] == "ValueError"
        assert line["http_status"] == 401
        assert line["user_id"] is None

    def test_argument_values_never_reach_the_log(self, mcp_on_test_db, signed_in_user, capsys):
        from fastmcp.exceptions import ToolError

        capsys.readouterr()
        with _signed_in_as(signed_in_user), pytest.raises(ToolError):
            asyncio.run(
                mcp_on_test_db.call_tool(
                    "update_url",
                    {"short_code": "missing1", "title": "Jane Doe, Acme Corp"},
                )
            )

        stderr = capsys.readouterr().err
        [line] = _events(stderr, "mcp.tool_call")
        assert line["args"] == ["short_code", "title"]
        assert line["http_status"] == 404
        for event in ("mcp.tool_call", "http.request"):
            for record in _events(stderr, event):
                assert "Jane Doe" not in json.dumps(record)

    def test_cancelled_call_is_not_counted_as_ok(self, capsys):
        """CancelledError isn't an Exception; it must not fall through as a success."""
        pytest.importorskip("fastmcp")
        from types import SimpleNamespace

        from mcp_server.usage import UsageLogMiddleware

        async def cancelled(_context):
            raise asyncio.CancelledError

        context = SimpleNamespace(message=SimpleNamespace(name="list_urls", arguments={}))
        capsys.readouterr()
        with pytest.raises(asyncio.CancelledError):
            asyncio.run(UsageLogMiddleware().on_call_tool(context, cancelled))

        [line] = _events(capsys.readouterr().err, "mcp.tool_call")
        assert line["outcome"] == "error"
        assert line["error_type"] == "cancelled"


MCP_HEADERS = {
    "Accept": "application/json, text/event-stream",
    "Content-Type": "application/json",
}


def test_tool_call_over_http_shares_one_request_id(monkeypatch, capsys):
    """The MCP POST, the tool call and the API call it makes all carry one id."""
    pytest.importorskip("fastmcp")
    monkeypatch.setenv("MCP_DISABLE_AUTH", "1")
    monkeypatch.delenv("MCP_DISABLE_MOUNT", raising=False)
    import main as m

    importlib.reload(m)
    body = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "tools/call",
        "params": {"name": "get_current_user_info", "arguments": {}},
    }
    with TestClient(m.app) as http:
        capsys.readouterr()
        response = http.post("/mcp/", json=body, headers={**MCP_HEADERS, "x-request-id": "rid-mcp"})

    stderr = capsys.readouterr().err
    assert response.status_code == 200
    [call] = _events(stderr, "mcp.tool_call")
    assert call["tool"] == "get_current_user_info"
    assert call["request_id"] == "rid-mcp"
    requests = {line["path"]: line for line in _events(stderr, "http.request")}
    assert requests["/mcp/"]["request_id"] == "rid-mcp"
    # The generated tool's own call into the API is forwarded the same id.
    assert requests["/api/v1/auth/me"]["request_id"] == "rid-mcp"


# ---------------------------------------------------------------------------
# fastmcp's own line for a failed call
# ---------------------------------------------------------------------------

# Personal data in a tool call. No spaces, so Rich can't wrap it across two lines.
EMAIL = "jane.doe@acme.example"


class _Records(logging.Handler):
    """Keeps every record; `text()` renders them as a plain handler would, tracebacks included."""

    def __init__(self):
        super().__init__()
        self.records: list[logging.LogRecord] = []
        self.setFormatter(logging.Formatter("%(levelname)s %(name)s: %(message)s"))

    def emit(self, record):
        self.records.append(record)

    def text(self) -> str:
        return "\n".join(self.format(record) for record in self.records)

    def tool_errors(self) -> list[logging.LogRecord]:
        return [r for r in self.records if r.getMessage().startswith("Error calling tool")]


@pytest.fixture
def fastmcp_log():
    """Every record logged under `fastmcp`, whichever handlers end up printing it."""
    handler = _Records()
    logger = logging.getLogger("fastmcp")
    logger.addHandler(handler)
    try:
        yield handler
    finally:
        logger.removeHandler(handler)


class TestFastmcpErrorLine:
    """
    fastmcp logs each failed call itself: "Error calling tool …", with a traceback.
    When a generated tool's API call fails, the exception carries the response body,
    and a 422 body echoes the invalid values (the whole request body when a field
    is missing). The line keeps the tool and the status, not the body.
    """

    def test_invalid_value_stays_out_of_the_log(
        self, mcp_on_test_db, signed_in_user, fastmcp_log, capsys
    ):
        from fastmcp.exceptions import ToolError

        capsys.readouterr()
        with _signed_in_as(signed_in_user), pytest.raises(ToolError, match="422") as raised:
            asyncio.run(mcp_on_test_db.call_tool("create_short_url", {"url": EMAIL}))

        # The caller still gets the API's answer, value included, to correct the call.
        assert EMAIL in str(raised.value)
        assert EMAIL not in capsys.readouterr().err
        assert EMAIL not in fastmcp_log.text()
        assert fastmcp_log.tool_errors()  # the failure itself is still logged

    def test_campaign_rows_stay_out_of_the_log(
        self, mcp_on_test_db, signed_in_user, fastmcp_log, capsys
    ):
        """The worst case: with `name` missing, the 422 echoes the whole body, CSV included."""
        from fastmcp.exceptions import ToolError

        arguments = {
            "original_url": "https://acme.example/offer",
            "csv_data": f"name,company,email\nJane Doe,Acme,{EMAIL}\n",
        }
        capsys.readouterr()
        with _signed_in_as(signed_in_user), pytest.raises(ToolError, match="422") as raised:
            asyncio.run(mcp_on_test_db.call_tool("create_campaign", arguments))

        assert EMAIL in str(raised.value)
        assert EMAIL not in capsys.readouterr().err
        assert EMAIL not in fastmcp_log.text()
        assert fastmcp_log.tool_errors()

    def test_line_keeps_the_tool_and_the_status(self, mcp_on_test_db, signed_in_user, fastmcp_log):
        from fastmcp.exceptions import ToolError

        with _signed_in_as(signed_in_user), pytest.raises(ToolError):
            asyncio.run(mcp_on_test_db.call_tool("create_short_url", {"url": EMAIL}))

        [record] = fastmcp_log.tool_errors()
        assert record.levelno == logging.ERROR
        assert record.getMessage() == (
            "Error calling tool 'create_short_url': HTTP error 422 (response body not logged)"
        )
        # The traceback would print the body again, and it only walks fastmcp's HTTP client.
        assert record.exc_info is None

    def test_exception_inside_the_api_keeps_its_traceback(
        self, mcp_on_test_db, signed_in_user, fastmcp_log, capsys
    ):
        """A real server error reaches the tool as itself, not as an HTTP error."""
        from fastmcp.exceptions import ToolError

        from main import app
        from server.core import get_db

        def unreachable_database():
            raise RuntimeError("database unreachable")

        app.dependency_overrides[get_db] = unreachable_database  # the fixture pops it
        capsys.readouterr()
        with _signed_in_as(signed_in_user), pytest.raises(ToolError):
            asyncio.run(mcp_on_test_db.call_tool("list_urls", {}))

        [record] = fastmcp_log.tool_errors()
        assert record.getMessage() == "Error calling tool 'list_urls'"
        assert record.exc_info[0] is RuntimeError
        # Single words: Rich wraps its output to the console's width.
        stderr = capsys.readouterr().err
        assert "Traceback" in stderr
        assert "RuntimeError" in stderr

    def test_other_value_error_keeps_its_traceback(self, mcp_on_test_db, fastmcp_log):
        """Only fastmcp's "HTTP error" counts as an API error, not every ValueError."""
        from fastmcp.exceptions import ToolError

        @mcp_on_test_db.tool
        def summary(days: int) -> dict:
            raise ValueError("days must be between 1 and 90")  # as a curated tool does

        with pytest.raises(ToolError):
            asyncio.run(mcp_on_test_db.call_tool("summary", {"days": 365}))

        [record] = fastmcp_log.tool_errors()
        assert record.exc_info[0] is ValueError
