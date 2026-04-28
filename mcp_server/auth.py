"""
Phase 5.4 — MCP authentication.

The MCP server is a public-facing surface (Phase 5.5 will deploy it next to
the API on `s.griddo.io/mcp`). Without auth, every tool is anonymous, which
is wrong for any non-trivial use. We piggyback on the existing `User.api_key`
column rather than introducing OAuth: API keys already exist, are revocable
via `DELETE /api/v1/auth/api-key`, and don't require an extra UI flow.

Two integration points:

1. **`ShurlyTokenVerifier`** — fastmcp's `TokenVerifier` subclass. Validates
   the inbound `Authorization: Bearer <token>` against `User.api_key`. Both
   JWT and API-key tokens are accepted (matches the FastAPI behavior). The
   resolved user id is stored in the AccessToken so curated tools can pick
   it up with `get_access_token()` without re-querying the DB.

2. **`forward_bearer_auth`** — an httpx auth callable. The auto-generated
   tools call FastAPI via `httpx.AsyncClient(transport=ASGITransport(app))`.
   That call needs the same Bearer header so FastAPI's `get_current_user`
   resolves the same user. This auth callable reads the token from the
   current MCP request scope and copies it to the outbound request.
"""

from __future__ import annotations

from typing import Any

import httpx
from fastmcp.server.auth import AccessToken, TokenVerifier
from fastmcp.server.dependencies import get_access_token

from server.core import SessionLocal as _DefaultSessionLocal
from server.core.auth import _looks_like_jwt, decode_access_token, get_user_by_api_key
from server.core.models import User


class ShurlyTokenVerifier(TokenVerifier):
    """
    Verifies a bearer token against `User.api_key` (or a JWT for completeness).

    Returns an `AccessToken` whose `client_id` is the user's UUID and whose
    `claims` include the email + scope. Returning `None` produces a 401 at
    the MCP layer.

    The session factory is injected so tests can swap the production
    `SessionLocal` (which talks to RDS) for the in-memory one used by
    pytest. Defaults to the production factory.
    """

    def __init__(self, session_factory=_DefaultSessionLocal, **kwargs):
        super().__init__(**kwargs)
        self._session_factory = session_factory

    async def verify_token(self, token: str) -> AccessToken | None:
        with self._session_factory() as db:
            user = _resolve_user_from_token(db, token)
            if user is None:
                return None
            return AccessToken(
                token=token,
                client_id=str(user.id),
                scopes=[user.api_key_scope.value] if user.api_key_scope else [],
                claims={
                    "sub": user.email,
                    "user_id": str(user.id),
                    "scope": user.api_key_scope.value if user.api_key_scope else None,
                },
            )


def _resolve_user_from_token(db, token: str) -> User | None:
    """Token-shape dispatch matches `server.core.auth.get_current_user`."""
    if not token:
        return None
    if _looks_like_jwt(token):
        try:
            payload = decode_access_token(token)
        except Exception:  # HTTPException from decode → invalid JWT
            return None
        email = payload.get("sub")
        if not email:
            return None
        user = db.query(User).filter(User.email == email).first()
        if user is None or not user.is_active:
            return None
        return user
    return get_user_by_api_key(db, token)


def resolve_current_user(db) -> User:
    """
    Resolve the authenticated MCP caller to a `User` row.

    Designed for the curated-tool wrappers in `mcp_server/server.py`. Reads
    the AccessToken populated by `ShurlyTokenVerifier`, looks up the user by
    id, and raises `PermissionError` if no token is in the context (which
    means the request was unauthenticated — fastmcp would normally reject
    earlier, but we guard explicitly so unit tests with an empty context
    fail loudly instead of crashing).
    """
    access = get_access_token()
    if access is None:
        raise PermissionError(
            "MCP request has no bound access token; auth is required for "
            "curated tools."
        )
    user_id = access.claims.get("user_id") if access.claims else None
    if user_id is None:
        raise PermissionError("Access token missing user_id claim.")
    user = db.query(User).filter(User.id == user_id).first()
    if user is None or not user.is_active:
        raise PermissionError("User no longer exists or is inactive.")
    return user


def forward_bearer_auth(request: httpx.Request) -> httpx.Request:
    """
    httpx auth hook — copies the inbound MCP bearer onto the outbound
    FastAPI call so `get_current_user` validates against the same token.

    Wired via `httpx_client_kwargs={"auth": forward_bearer_auth}` on
    `FastMCP.from_fastapi(...)`. Without this, the auto-generated tools hit
    FastAPI anonymously and every protected route returns 401.
    """
    access = get_access_token()
    if access is not None and access.token:
        request.headers["Authorization"] = f"Bearer {access.token}"
    return request


# httpx accepts either a callable or an Auth subclass. Newer httpx versions
# expect Auth subclasses for proper request lifecycle integration.
class _ForwardBearer(httpx.Auth):
    def auth_flow(self, request: httpx.Request) -> Any:
        access = get_access_token()
        if access is not None and access.token:
            request.headers["Authorization"] = f"Bearer {access.token}"
        yield request


forward_bearer = _ForwardBearer()
