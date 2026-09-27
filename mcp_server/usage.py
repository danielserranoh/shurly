"""
Phase 5.6.0 — usage log for MCP tool calls.

In the access log every MCP call is a `POST /mcp/`: the tool name travels
inside the JSON-RPC body, so nothing recorded which tools get used, how often,
or how they fail. `UsageLogMiddleware` writes one `mcp.tool_call` line per call
(see `server/utils/event_log.py`) for the dogfood's counts, error rates and
durations. Argument names only, never their values.

`forward_request_id` gives the API call a generated tool makes the same request
id as the MCP request, so one id links the MCP request, the tool call and the
API call it made.
"""

from __future__ import annotations

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


async def forward_request_id(request: httpx2.Request) -> None:
    """httpx2 request hook for the generated tools' calls into the API."""
    request_id = current_request_id()
    if request_id and "x-request-id" not in request.headers:
        request.headers["x-request-id"] = request_id
