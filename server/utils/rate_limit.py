"""
Phase 6.3 — rate limits on what anyone can call.

- The password login runs a bcrypt check per attempt (~165 ms of CPU) on the tasks
  that also serve redirects: limited per client IP, and failed attempts per account
  (in the login endpoint, which knows the outcome).
- Google's and the MCP's sign-in endpoints write a row per request: per client IP.
  /mcp/register and /mcp/token have their own, generous count: claude.ai calls them
  from Anthropic's addresses, shared by everybody.
Redirects, anything signed in and CORS preflights are never limited.

Fixed windows, counted in the database (`rate_limits`) so both tasks share the
counts and a deploy keeps them. Keys are HMACs of the limit and the IP or address:
no IP or email is stored or logged. If the database can't count, the request goes
through and `rate_limit.store_failed` is logged: a limit protects, it mustn't
become an outage.

The client IP is `resolve_client_ip`'s: with TRUSTED_PROXIES naming the ALB, the
address the ALB saw. Unset, every request seems to come from the ALB, and a per-IP
limit becomes one limit for everybody.
"""

import hashlib
import hmac
import time
from dataclasses import dataclass

from sqlalchemy import case, delete
from sqlalchemy.dialects import postgresql, sqlite
from starlette.concurrency import run_in_threadpool
from starlette.requests import Request
from starlette.responses import JSONResponse, PlainTextResponse, RedirectResponse, Response

from server.core import SessionLocal
from server.core.config import settings
from server.core.models import RateLimit
from server.utils.event_log import log_event
from server.utils.network import resolve_client_ip

# Tests point this at their database.
session_factory = SessionLocal

# Seconds a row may sit idle before it's deleted: longer than any window.
_KEEP = 60 * 60


@dataclass(frozen=True)
class Limit:
    name: str
    window: int  # seconds
    setting: str  # the Settings field: how many per window; 0 turns the limit off

    @property
    def per_window(self) -> int:
        return getattr(settings, self.setting)


LOGIN_PER_IP = Limit("login_ip", 60, "rate_limit_login_per_ip")
LOGIN_FAILURES_PER_ACCOUNT = Limit(
    "login_account", 15 * 60, "rate_limit_login_failures_per_account"
)
SIGN_IN_PER_IP = Limit("sign_in_ip", 60, "rate_limit_sign_in_per_ip")
MCP_CLIENTS_PER_IP = Limit("mcp_clients_ip", 60, "rate_limit_mcp_clients_per_ip")


@dataclass(frozen=True)
class Verdict:
    allowed: bool
    retry_after: int = 0  # seconds until the window ends


_ALLOWED = Verdict(True)


def _now() -> float:
    return time.time()


def _key(limit: Limit, subject: str) -> str:
    message = f"{limit.name}:{subject}".encode()
    return hmac.new(settings.jwt_secret_key.encode(), message, hashlib.sha256).hexdigest()


def _window(limit: Limit) -> tuple[int, int]:
    """The current window's start, and the seconds left in it."""
    now = int(_now())
    start = now - now % limit.window
    return start, start + limit.window - now


def hit(limit: Limit, subject: str) -> Verdict:
    """Count one for `subject`, and say whether it's still within the limit."""
    if limit.per_window <= 0:
        return _ALLOWED
    start, left = _window(limit)
    try:
        count = _increment(_key(limit, subject), start)
    except Exception as exc:  # noqa: BLE001 — whatever the database does, let the request through
        log_event("rate_limit.store_failed", limit=limit.name, error=type(exc).__name__)
        return _ALLOWED
    return Verdict(count <= limit.per_window, left)


def check(limit: Limit, subject: str) -> Verdict:
    """Whether `subject` is still within the limit, without counting."""
    if limit.per_window <= 0:
        return _ALLOWED
    start, left = _window(limit)
    try:
        with session_factory() as db:
            row = db.get(RateLimit, _key(limit, subject))
            count = row.count if row is not None and row.window_start == start else 0
    except Exception as exc:  # noqa: BLE001
        log_event("rate_limit.store_failed", limit=limit.name, error=type(exc).__name__)
        return _ALLOWED
    return Verdict(count < limit.per_window, left)


def _increment(key: str, window_start: int) -> int:
    """One more in this window (or 1 in a new one), in one statement: two tasks
    counting the same key can't lose a count."""
    with session_factory() as db:
        db.execute(delete(RateLimit).where(RateLimit.window_start < window_start - _KEEP))
        dialect = db.get_bind().dialect.name
        insert = (postgresql.insert if dialect == "postgresql" else sqlite.insert)(RateLimit)
        statement = insert.values(key=key, window_start=window_start, count=1)
        statement = statement.on_conflict_do_update(
            index_elements=[RateLimit.key],
            set_={
                "count": case(
                    (
                        RateLimit.window_start == statement.excluded.window_start,
                        RateLimit.count + 1,
                    ),
                    else_=1,
                ),
                "window_start": statement.excluded.window_start,
            },
        ).returning(RateLimit.count)
        count = db.execute(statement).scalar_one()
        db.commit()
        return count


def client_ip(request: Request) -> str:
    return resolve_client_ip(
        request.client.host if request.client else None,
        request.headers.get("x-forwarded-for"),
        settings.trusted_proxies,
    )


# How a refusal is shown: JSON for API calls; for Google's sign-in, which the browser
# navigates to, the frontend's login page; plain text for the MCP's sign-in pages.
_JSON, _FRONTEND, _TEXT = "json", "frontend", "text"

# Method and path → the limit, and how a refusal is shown. OPTIONS never matches.
_ROUTES: dict[tuple[str, str], tuple[Limit, str]] = {
    ("POST", "/api/v1/auth/login"): (LOGIN_PER_IP, _JSON),
    ("POST", "/api/v1/auth/register"): (SIGN_IN_PER_IP, _JSON),
    ("GET", "/api/v1/auth/google/start"): (SIGN_IN_PER_IP, _FRONTEND),
    ("GET", "/api/v1/auth/google/callback"): (SIGN_IN_PER_IP, _FRONTEND),
    ("POST", "/api/v1/auth/google/exchange"): (SIGN_IN_PER_IP, _JSON),
    ("GET", "/mcp/authorize"): (SIGN_IN_PER_IP, _TEXT),
    ("POST", "/mcp/authorize"): (SIGN_IN_PER_IP, _TEXT),
    ("GET", "/mcp/consent"): (SIGN_IN_PER_IP, _TEXT),
    ("POST", "/mcp/consent"): (SIGN_IN_PER_IP, _TEXT),
    ("GET", "/mcp/auth/callback"): (SIGN_IN_PER_IP, _TEXT),
    ("POST", "/mcp/register"): (MCP_CLIENTS_PER_IP, _JSON),
    ("POST", "/mcp/token"): (MCP_CLIENTS_PER_IP, _JSON),
}


def refusal(shown_as: str, retry_after: int) -> Response:
    headers = {"Retry-After": str(retry_after), "Cache-Control": "no-store"}
    if shown_as == _FRONTEND and settings.frontend_url:
        # Only ever FRONTEND_URL, as the sign-in's own redirects.
        url = f"{settings.frontend_url.rstrip('/')}/login/#error=rate_limited"
        return RedirectResponse(url, status_code=302, headers={"Cache-Control": "no-store"})
    message = f"Too many attempts. Try again in {retry_after} seconds."
    if shown_as == _TEXT:
        return PlainTextResponse(message, status_code=429, headers=headers)
    return JSONResponse({"detail": message}, status_code=429, headers=headers)


class RateLimitMiddleware:
    """The per-IP limits, by method and path, before the request reaches its route
    (the MCP's sign-in lives in the mounted fastmcp app, beyond FastAPI's routing)."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        route = (
            _ROUTES.get((scope.get("method"), scope.get("path")))
            if scope["type"] == "http"
            else None
        )
        if route is None:
            await self.app(scope, receive, send)
            return
        limit, shown_as = route
        verdict = await run_in_threadpool(hit, limit, client_ip(Request(scope)))
        if verdict.allowed:
            await self.app(scope, receive, send)
            return
        log_event("http.rate_limited", path=scope["path"], limit=limit.name)
        await refusal(shown_as, verdict.retry_after)(scope, receive, send)
