"""Phase 4.2 — health-check endpoints for ECS/ALB."""

from fastapi.testclient import TestClient


def test_liveness_returns_200_without_auth(client: TestClient):
    """The ALB liveness probe must be reachable without authentication."""
    r = client.get("/api/v1/health")
    assert r.status_code == 200
    assert r.json() == {"status": "ok"}


def test_liveness_does_not_require_database(client: TestClient):
    # Sanity: the body confirms we're not just bouncing off middleware. The
    # liveness handler is a pure dict return — the moment anyone makes it touch
    # the DB this test (and the ALB) will start coupling.
    r = client.get("/api/v1/health")
    assert "db" not in r.json()


def test_readiness_round_trips_to_db(client: TestClient):
    r = client.get("/api/v1/health/db")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok"
    assert body["db"] == "ok"
