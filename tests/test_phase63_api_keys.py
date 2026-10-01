"""
Phase 6.3 — API keys are stored as a SHA-256 hash and a short prefix, never as
themselves: a key is shown once, when it's made. /auth/me, and so the MCP's
get_current_user_info tool, which put it in an assistant's context, no longer
returns it.
"""

import asyncio
import hashlib
from contextlib import contextmanager

import pytest
from sqlalchemy import text

from server.core.auth import _looks_like_jwt, get_user_by_api_key


def _generate(client, auth_headers) -> str:
    response = client.post("/api/v1/auth/api-key/generate", headers=auth_headers)
    assert response.status_code == 200, response.text
    return response.json()["api_key"]


def _me(client, token: str):
    return client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {token}"})


class TestGenerate:
    def test_a_new_key_is_shown_once_and_kept_as_a_hash(
        self, client, db_session, test_user, auth_headers
    ):
        key = _generate(client, auth_headers)

        assert key.startswith("shurly_") and len(key) == len("shurly_") + 43
        db_session.refresh(test_user)
        assert test_user.api_key_hash == hashlib.sha256(key.encode()).hexdigest()
        assert test_user.api_key_prefix == key[:12]
        row = db_session.execute(text("SELECT * FROM users")).mappings().one()
        assert not [column for column, value in row.items() if key in str(value)]

    def test_the_key_signs_in(self, client, test_user, auth_headers):
        key = _generate(client, auth_headers)

        assert _me(client, key).json()["email"] == test_user.email

    def test_a_new_key_ends_the_old_one(self, client, auth_headers):
        old = _generate(client, auth_headers)
        new = _generate(client, auth_headers)

        assert _me(client, old).status_code == 401
        assert _me(client, new).status_code == 200

    def test_an_api_key_cannot_make_a_new_one(self, client, auth_headers):
        """A leaked key mustn't mint its own replacement, ending the owner's."""
        key = _generate(client, auth_headers)

        response = client.post(
            "/api/v1/auth/api-key/generate", headers={"Authorization": f"Bearer {key}"}
        )

        assert response.status_code == 403
        assert "API key" in response.json()["detail"]
        assert _me(client, key).status_code == 200

    def test_revoking_ends_it(self, client, db_session, test_user, auth_headers):
        key = _generate(client, auth_headers)

        assert client.delete("/api/v1/auth/api-key", headers=auth_headers).status_code == 200

        assert _me(client, key).status_code == 401
        db_session.refresh(test_user)
        assert (test_user.api_key_hash, test_user.api_key_prefix) == (None, None)


class TestNoLeak:
    def test_me_says_there_is_a_key_but_not_what_it_is(self, client, auth_headers):
        key = _generate(client, auth_headers)

        response = client.get("/api/v1/auth/me", headers=auth_headers)

        body = response.json()
        assert "api_key" not in body
        assert (body["has_api_key"], body["api_key_prefix"]) == (True, key[:12])
        assert key not in response.text

    def test_without_a_key_me_says_so(self, client, auth_headers):
        body = client.get("/api/v1/auth/me", headers=auth_headers).json()

        assert (body["has_api_key"], body["api_key_prefix"]) == (False, None)

    def test_the_mcp_tool_no_longer_hands_the_key_to_the_assistant(
        self, client, db_session, test_user, auth_headers, mcp_on_test_db
    ):
        """get_current_user_info is generated from /auth/me: the key reached the model."""
        key = _generate(client, auth_headers)

        with _bound_access_token(key):
            result = asyncio.run(mcp_on_test_db.call_tool("get_current_user_info", {}))

        assert result.structured_content["email"] == test_user.email
        assert "api_key" not in result.structured_content
        assert key not in str(result.structured_content) + str(result.content)


class TestLookup:
    def test_a_key_from_before_0007_still_works(self, client, db_session, test_user):
        """Keys made before the prefix: 0007 only hashed them."""
        legacy = "Zq3" * 14 + "x"  # 43 url-safe characters, no prefix
        test_user.set_api_key(legacy)
        db_session.commit()

        assert _me(client, legacy).status_code == 200
        assert get_user_by_api_key(db_session, legacy).id == test_user.id

    def test_a_jwt_shaped_token_with_the_prefix_is_read_as_a_jwt(
        self, client, db_session, test_user
    ):
        """The shape decides: two dots is a JWT, whatever it starts with."""
        token = "shurly_aaa.bbb.ccc"
        test_user.set_api_key(token)  # even if it were someone's key
        db_session.commit()

        assert _looks_like_jwt(token)
        assert _me(client, token).status_code == 401

    def test_real_keys_never_look_like_jwts(self, client, auth_headers):
        assert not _looks_like_jwt(_generate(client, auth_headers))


# --- The MCP, as test_phase54_mcp_auth.py runs it -----------------------------------


@contextmanager
def _bound_access_token(token: str):
    from fastmcp.server.auth import AccessToken
    from mcp.server.auth.middleware.auth_context import auth_context_var
    from mcp.server.auth.middleware.bearer_auth import AuthenticatedUser

    reset = auth_context_var.set(
        AuthenticatedUser(AccessToken(token=token, client_id="test-client", scopes=[]))
    )
    try:
        yield
    finally:
        auth_context_var.reset(reset)


@pytest.fixture
def mcp_on_test_db(db_session):
    pytest.importorskip("fastmcp")
    from main import app
    from mcp_server.server import build_mcp_for_app
    from server.core import get_db

    app.dependency_overrides[get_db] = lambda: db_session
    try:
        yield build_mcp_for_app(app)
    finally:
        app.dependency_overrides.pop(get_db, None)


def test_migration_0007_moves_every_key_to_its_hash(pg_engine):
    """smoke@griddo.io's key, made by the old code, keeps working after the backfill."""
    from alembic import command
    from sqlalchemy.orm import sessionmaker

    from server.core.migrations import alembic_config

    legacy = "Lg7" * 14 + "q"
    config = alembic_config()
    with pg_engine.begin() as conn:
        config.attributes["connection"] = conn
        command.upgrade(config, "0006")
        conn.execute(
            text(
                "INSERT INTO users (id, email, password_hash, api_key, api_key_scope, is_active,"
                " created_at) VALUES (gen_random_uuid(), 'smoke@griddo.io', 'x', :key,"
                " 'FULL_ACCESS', true, now())"
            ),
            {"key": legacy},
        )
        command.upgrade(config, "0007")

    with pg_engine.connect() as conn:
        row = conn.execute(text("SELECT api_key, api_key_hash, api_key_prefix FROM users")).one()
    assert row == (None, hashlib.sha256(legacy.encode()).hexdigest(), legacy[:12])
    with sessionmaker(bind=pg_engine)() as db:
        assert get_user_by_api_key(db, legacy).email == "smoke@griddo.io"


def test_the_model_no_longer_maps_the_plaintext_column():
    """0014 drops users.api_key while this release still serves: nothing may name it."""
    from server.core.models import User

    assert "api_key" not in User.__table__.columns


def test_this_release_works_once_0014_drops_the_plaintext_column(pg_engine, monkeypatch):
    """
    Rolling deploys: 0014 drops users.api_key at the next release's startup, while this
    release's task still serves. The ORM names every mapped column in its SELECTs and
    INSERTs, so this release must not map it. Signing in, an API key, /me, the MCP
    (which loads the user itself, in ShurlyTokenVerifier) and revoking, without it.
    """
    pytest.importorskip("fastmcp")
    import json

    from fastapi.testclient import TestClient
    from sqlalchemy.orm import sessionmaker

    from main import create_app
    from mcp_server.server import build_mcp_auth
    from server.core import get_db
    from server.core.auth import hash_password
    from server.core.migrations import run_migrations
    from server.core.models import User
    from server.utils import rate_limit

    run_migrations(pg_engine)
    with pg_engine.begin() as conn:
        conn.execute(text("ALTER TABLE users DROP COLUMN api_key"))  # what 0014 will do

    sessions = sessionmaker(bind=pg_engine)
    with sessions() as db:
        db.add(User(email="ana@griddo.io", password_hash=hash_password("right-password-1")))
        db.commit()

    def _db():
        with sessions() as db:
            yield db

    monkeypatch.setattr(rate_limit, "session_factory", sessions)
    app = create_app(mcp_auth=build_mcp_auth(session_factory=sessions))
    app.dependency_overrides[get_db] = _db
    with TestClient(app) as client:
        login = {"email": "ana@griddo.io", "password": "right-password-1"}
        jwt = {
            "authorization": f"Bearer {client.post('/api/v1/auth/login', json=login).json()['access_token']}"
        }
        key = client.post("/api/v1/auth/api-key/generate", headers=jwt).json()["api_key"]
        with_key = {"authorization": f"Bearer {key}"}

        assert client.get("/api/v1/auth/me", headers=with_key).json()["has_api_key"] is True
        call = {"name": "get_current_user_info", "arguments": {}}
        mcp = client.post(
            "/mcp/",
            json={"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": call},
            headers={**with_key, "accept": "application/json, text/event-stream"},
        )
        assert mcp.status_code == 200, mcp.text
        data = next(line[6:] for line in mcp.text.splitlines() if line.startswith("data: "))
        assert (
            json.loads(json.loads(data)["result"]["content"][0]["text"])["email"] == "ana@griddo.io"
        )
        assert client.delete("/api/v1/auth/api-key", headers=jwt).status_code == 200
