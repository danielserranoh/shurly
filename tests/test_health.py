"""Phase 4.2 — health-check endpoints for ECS/ALB."""

from fastapi.testclient import TestClient


def test_liveness_returns_200_without_auth(client: TestClient):
    """The ALB liveness probe must be reachable without authentication."""
    r = client.get("/api/v1/health")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"


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


def test_liveness_reports_the_deployed_commit(client: TestClient, monkeypatch):
    """The deploy pipeline polls this to confirm the NEW image is serving.

    Probing only for a 200 is what let a release report success while the old
    image kept answering: the old one returns 200 too. The image bakes the
    commit in as GIT_SHA at build time, and the smoke test waits until this
    matches the commit it just deployed.
    """
    monkeypatch.setenv("GIT_SHA", "387434fe29c3567e6a18749792ea6273de5f9039")
    r = client.get("/api/v1/health")
    assert r.json()["commit"] == "387434fe29c3567e6a18749792ea6273de5f9039"


def test_liveness_commit_is_unknown_outside_a_built_image(client: TestClient, monkeypatch):
    """Local runs and tests have no GIT_SHA; say so rather than inventing one."""
    monkeypatch.delenv("GIT_SHA", raising=False)
    r = client.get("/api/v1/health")
    assert r.json()["commit"] == "unknown"
