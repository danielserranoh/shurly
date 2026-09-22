"""
Phase 5.4 — MCP authentication.

Covers two surfaces:

1. **FastAPI** — `get_current_user` now accepts both JWTs (existing) and
   API keys via the same `Authorization: Bearer` header. Tests confirm both
   paths resolve the same user, that an unknown API key is rejected, and
   that an inactive user with a valid key is rejected.

2. **MCP** — the `ShurlyTokenVerifier` and `resolve_current_user` helpers
   used by the curated-tool wrappers. Direct unit tests; the wrappers
   themselves get integration coverage via Phase 5.3 tests already. Plus
   the bearer forwarding: a generated tool called with a bound access token
   must reach FastAPI as the same user, and without one it must get a 401.
"""

from __future__ import annotations

import asyncio
import secrets
from contextlib import contextmanager

import pytest
from fastapi.testclient import TestClient

pytest.importorskip("fastmcp")

from server.core.auth import _looks_like_jwt, get_user_by_api_key  # noqa: E402
from server.core.models import ApiKeyScope  # noqa: E402

# ---------------------------------------------------------------------------
# Token shape detection
# ---------------------------------------------------------------------------


def test_looks_like_jwt_true_for_three_part_token():
    assert _looks_like_jwt("a.b.c") is True


def test_looks_like_jwt_false_for_url_safe_secret():
    # secrets.token_urlsafe never produces dots; fall-through path → API key.
    assert _looks_like_jwt(secrets.token_urlsafe(32)) is False


# ---------------------------------------------------------------------------
# get_user_by_api_key
# ---------------------------------------------------------------------------


def test_get_user_by_api_key_returns_user(db_session, test_user):
    test_user.api_key = "abc123"
    test_user.api_key_scope = ApiKeyScope.FULL_ACCESS
    db_session.commit()
    found = get_user_by_api_key(db_session, "abc123")
    assert found is not None
    assert found.id == test_user.id


def test_get_user_by_api_key_returns_none_for_unknown(db_session):
    assert get_user_by_api_key(db_session, "no-such-key") is None


def test_get_user_by_api_key_skips_inactive(db_session, test_user):
    test_user.api_key = "inactive-key"
    test_user.is_active = False
    db_session.commit()
    assert get_user_by_api_key(db_session, "inactive-key") is None


def test_get_user_by_api_key_empty_token_returns_none(db_session):
    assert get_user_by_api_key(db_session, "") is None


# ---------------------------------------------------------------------------
# FastAPI: API key authenticates protected routes
# ---------------------------------------------------------------------------


def test_api_key_authenticates_me_endpoint(client: TestClient, db_session, test_user):
    test_user.api_key = "valid-api-key-xyz"
    db_session.commit()
    resp = client.get("/api/v1/auth/me", headers={"Authorization": "Bearer valid-api-key-xyz"})
    assert resp.status_code == 200
    assert resp.json()["email"] == test_user.email


def test_invalid_api_key_returns_401(client: TestClient):
    resp = client.get("/api/v1/auth/me", headers={"Authorization": "Bearer bogus-key"})
    assert resp.status_code == 401


def test_inactive_user_api_key_rejected(client: TestClient, db_session, test_user):
    test_user.api_key = "inactive-but-valid"
    test_user.is_active = False
    db_session.commit()
    resp = client.get(
        "/api/v1/auth/me", headers={"Authorization": "Bearer inactive-but-valid"}
    )
    # Inactive users with API keys fail the key lookup itself (404-ish path),
    # which surfaces as 401. JWTs for inactive users still hit the explicit
    # 403 branch — covered by the existing JWT auth tests.
    assert resp.status_code == 401


def test_jwt_still_works_after_api_key_path_added(client: TestClient, auth_headers):
    resp = client.get("/api/v1/auth/me", headers=auth_headers)
    assert resp.status_code == 200


# ---------------------------------------------------------------------------
# MCP: ShurlyTokenVerifier
# ---------------------------------------------------------------------------


@pytest.fixture
def verifier_factory(db_session):
    """Builds a ShurlyTokenVerifier wired to the in-memory test DB session.
    Avoids hitting the real RDS SessionLocal."""
    from mcp_server.auth import ShurlyTokenVerifier

    @contextmanager
    def _factory():
        # Yield the same fixture session so writes in the test (e.g.
        # `test_user.api_key = ...`) are visible to the verifier query.
        yield db_session

    return ShurlyTokenVerifier(session_factory=_factory)


def test_token_verifier_accepts_valid_api_key(db_session, test_user, verifier_factory):
    test_user.api_key = "mcp-key-1"
    db_session.commit()

    token = asyncio.run(verifier_factory.verify_token("mcp-key-1"))
    assert token is not None
    assert token.client_id == str(test_user.id)
    assert token.claims["sub"] == test_user.email
    assert token.claims["user_id"] == str(test_user.id)


def test_token_verifier_rejects_unknown_key(verifier_factory):
    assert asyncio.run(verifier_factory.verify_token("nope-key")) is None


def test_token_verifier_rejects_inactive_user(db_session, test_user, verifier_factory):
    test_user.api_key = "soon-disabled"
    test_user.is_active = False
    db_session.commit()

    assert asyncio.run(verifier_factory.verify_token("soon-disabled")) is None


# ---------------------------------------------------------------------------
# MCP: resolve_current_user (no token bound → PermissionError)
# ---------------------------------------------------------------------------


def test_resolve_current_user_without_token_raises(db_session):
    from mcp_server.auth import resolve_current_user

    with pytest.raises(PermissionError, match="no bound access token"):
        resolve_current_user(db_session)


# ---------------------------------------------------------------------------
# MCP: generated tools forward the bearer to FastAPI
# ---------------------------------------------------------------------------


@contextmanager
def _bound_access_token(token: str):
    """Bind `token` to the current context the way the MCP SDK's auth
    middleware does for each authenticated HTTP request."""
    from fastmcp.server.auth import AccessToken
    from mcp.server.auth.middleware.auth_context import auth_context_var
    from mcp.server.auth.middleware.bearer_auth import AuthenticatedUser

    reset_token = auth_context_var.set(
        AuthenticatedUser(AccessToken(token=token, client_id="test-client", scopes=[]))
    )
    try:
        yield
    finally:
        auth_context_var.reset(reset_token)


@pytest.fixture
def mcp_on_test_db(db_session):
    """MCP server whose generated tools call a FastAPI app bound to the test DB."""
    from main import app
    from mcp_server.server import build_mcp_for_app
    from server.core import get_db

    app.dependency_overrides[get_db] = lambda: db_session
    try:
        yield build_mcp_for_app(app)
    finally:
        app.dependency_overrides.pop(get_db, None)


def test_generated_tool_forwards_bearer_to_fastapi(db_session, test_user, mcp_on_test_db):
    test_user.api_key = "forwarded-key"
    db_session.commit()

    with _bound_access_token("forwarded-key"):
        result = asyncio.run(mcp_on_test_db.call_tool("get_current_user_info", {}))

    assert result.structured_content["email"] == test_user.email


def test_generated_tool_without_bound_token_is_rejected(mcp_on_test_db):
    from fastmcp.exceptions import ToolError

    with pytest.raises(ToolError, match="401"):
        asyncio.run(mcp_on_test_db.call_tool("get_current_user_info", {}))
