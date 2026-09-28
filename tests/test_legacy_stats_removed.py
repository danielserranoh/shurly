"""
The legacy `/api/v1/stats/*` routes are gone. Mounted without authentication since Phase 1.4,
they queried columns that don't exist (`urls.short_url`, `visits.created_at`), so no call to
them ever succeeded. `/api/v1/analytics/*` serves these numbers.
"""

import pytest


@pytest.mark.parametrize(
    "path",
    [
        "/api/v1/stats/day/abc123",
        "/api/v1/stats/week/abc123",
        "/api/v1/stats/world/abc123",
        "/api/v1/stats/main",
        "/api/v1/stats/next/abc123",
    ],
)
def test_the_routes_are_gone(client, path):
    assert client.get(path).status_code == 404


def test_not_in_the_api_docs(client):
    paths = client.get("/openapi.json").json()["paths"]

    assert not [path for path in paths if path.startswith("/api/v1/stats")]
