"""
Phase 6.3 — the CORS policy, pinned.

The frontend calls the API from its own origin with a bearer token in the
Authorization header, never cookies. So only the listed origins get CORS
headers, credentials aren't allowed, methods and request headers are the ones
the API uses, and the frontend can read Retry-After and X-Request-Id.
"""

from pathlib import Path

from server.core.config import Settings

FRONTEND = "http://localhost:4232"  # in the default CORS_ORIGINS
PRODUCTION_TEMPLATE = Path(__file__).resolve().parents[1] / ".env.production.example"


def _preflight(client, origin: str, method: str = "POST", headers: str = "content-type"):
    return client.options(
        "/api/v1/auth/google/exchange",
        headers={
            "origin": origin,
            "access-control-request-method": method,
            "access-control-request-headers": headers,
        },
    )


def test_the_frontend_may_call_the_api(client):
    response = _preflight(client, FRONTEND, headers="authorization, content-type")

    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == FRONTEND
    assert "POST" in response.headers["access-control-allow-methods"]
    allowed = response.headers["access-control-allow-headers"].lower()
    assert "authorization" in allowed and "content-type" in allowed


def test_no_credentials(client):
    """Nothing the frontend does needs cookies across origins."""
    assert "access-control-allow-credentials" not in _preflight(client, FRONTEND).headers
    simple = client.get("/api/v1/health", headers={"origin": FRONTEND})
    assert "access-control-allow-credentials" not in simple.headers


def test_another_origin_gets_nothing(client):
    preflight = _preflight(client, "https://evil.test")
    simple = client.get("/api/v1/health", headers={"origin": "https://evil.test"})

    assert preflight.status_code == 400
    assert "access-control-allow-origin" not in preflight.headers
    assert "access-control-allow-origin" not in simple.headers


def test_only_the_methods_and_headers_the_api_uses(client):
    allowed = _preflight(client, FRONTEND).headers["access-control-allow-methods"]

    # Not "*", which Starlette turns into every method, HEAD and OPTIONS included.
    assert {m.strip() for m in allowed.split(",")} == {"GET", "POST", "PUT", "PATCH", "DELETE"}
    assert _preflight(client, FRONTEND, headers="x-anything").status_code == 400


def test_the_frontend_can_read_retry_after_and_the_request_id(client):
    response = client.get("/api/v1/health", headers={"origin": FRONTEND})

    exposed = response.headers["access-control-expose-headers"].lower()
    assert "retry-after" in exposed and "x-request-id" in exposed


def test_production_lists_no_other_origin(monkeypatch):
    """In production the frontend is served from the API's host (4.10), so the template lists
    no origin (DEPLOYMENT.md § CORS). Loading it also checks the value is valid JSON: a mangled
    one stops the task at startup (docs/AWS_ECS_DEPLOYMENT.md, lesson 8)."""
    monkeypatch.delenv("CORS_ORIGINS", raising=False)

    assert Settings(_env_file=PRODUCTION_TEMPLATE).cors_origins == []
