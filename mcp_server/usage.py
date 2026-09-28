"""
Phase 5.6.0 — usage log for MCP tool calls.

In the access log every MCP call is a `POST /mcp/`: the tool name travels
inside the JSON-RPC body, so nothing recorded which tools get used, how often,
or how they fail. `UsageLogMiddleware` writes one `mcp.tool_call` line per call
(see `server/utils/event_log.py`) for the dogfood's counts, error rates and
durations. Argument names only, never their values.

`ApiErrorLogFilter` holds fastmcp's own line for a failed call to that rule.
When a generated tool's API call fails, fastmcp raises
`ValueError("HTTP error 422: … - <response body>")` and logs it with its
traceback. A 422 body echoes each invalid field's value, or the whole request
body when a field is missing, so a campaign's CSV rows could reach the log.

`forward_request_id` gives the API call a generated tool makes the same request
id as the MCP request, so one id links the MCP request, the tool call and the
API call it made.
"""

from __future__ import annotations

import logging
import re
import time
from typing import TYPE_CHECKING

from fastmcp.server.dependencies import get_access_token, get_http_request
from fastmcp.server.middleware import Middleware

from server.utils.event_log import log_event

if TYPE_CHECKING:
    import httpx2

# How fastmcp's OpenAPI tools report an API error: "HTTP error 404: Not Found - …".
_HTTP_STATUS = re.compile(r"HTTP error (\d{3})")

# Where `FastMCP.call_tool` logs a failed call: "Error calling tool 'create_short_url'".
# If a fastmcp release moves it, tests/test_phase560_usage_log.py fails.
_FASTMCP_TOOL_LOGGER = "fastmcp.server.server"


def current_request_id() -> str | None:
    """The id `RequestIdMiddleware` gave the MCP HTTP request; None without one (stdio)."""
    try:
        request = get_http_request()
    except RuntimeError:
        return None
    return getattr(request.state, "request_id", None)


class UsageLogMiddleware(Middleware):
    """Writes one `mcp.tool_call` line per tool call, whether it succeeds or fails."""

    async def on_call_tool(self, context, call_next):
        started = time.perf_counter()
        # Stays as is only if the call never returns or raises an Exception:
        # CancelledError is a BaseException and must not count as a success.
        outcome, error_type, http_status = "error", "cancelled", None
        try:
            result = await call_next(context)
            outcome, error_type = ("error", "tool_error") if result.is_error else ("ok", None)
            return result
        except Exception as exc:
            # fastmcp wraps every tool failure in a ToolError; the cause says more.
            error_type = type(exc.__cause__ or exc).__name__
            match = _HTTP_STATUS.search(str(exc))
            http_status = int(match.group(1)) if match else None
            raise
        finally:
            access = get_access_token()
            log_event(
                "mcp.tool_call",
                request_id=current_request_id(),
                tool=context.message.name,
                args=sorted(context.message.arguments or {}),
                user_id=access.claims.get("user_id") if access else None,
                outcome=outcome,
                error_type=error_type,
                http_status=http_status,
                duration_ms=round((time.perf_counter() - started) * 1000, 1),
            )


class ApiErrorLogFilter(logging.Filter):
    """
    Drops the response body and the traceback from fastmcp's line for a failed API call.

    The line keeps the tool and the status: `Error calling tool 'create_short_url':
    HTTP error 422 (response body not logged)`. The traceback would print the body
    again, and it only walks fastmcp's HTTP client: the API answered. The caller
    still gets the whole error. Any other exception keeps its traceback, one raised
    inside the API included: it reaches the tool as itself, not as an HTTP error.
    """

    def filter(self, record: logging.LogRecord) -> bool:
        error = record.exc_info[1] if record.exc_info else None
        match = _HTTP_STATUS.match(str(error)) if isinstance(error, ValueError) else None
        if match:
            status = match.group(1)
            record.msg = f"{record.getMessage()}: HTTP error {status} (response body not logged)"
            record.args = ()
            record.exc_info = None
            record.exc_text = None
        return True


_api_error_log_filter = ApiErrorLogFilter()


def install_api_error_log_filter() -> None:
    """Idempotent: `addFilter` keeps one copy of a filter however often it's added."""
    logging.getLogger(_FASTMCP_TOOL_LOGGER).addFilter(_api_error_log_filter)


async def forward_request_id(request: httpx2.Request) -> None:
    """httpx2 request hook for the generated tools' calls into the API."""
    request_id = current_request_id()
    if request_id and "x-request-id" not in request.headers:
        request.headers["x-request-id"] = request_id
