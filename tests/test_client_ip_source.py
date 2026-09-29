"""
Phase 6.3 — how the client IP was found, on each request's log line: `client_ip_source`, never
the address itself (`client_ip_and_source`, server/utils/network.py).

- cloudfront: CloudFront-Viewer-Address, on a request carrying the distribution's secret (4.10);
- xff: X-Forwarded-For, from a trusted proxy, the ALB;
- socket: the connection's peer, with no trusted proxy in front of it.

With the request's host next to it, CloudWatch can count them: in production shurly.griddo.io
reads cloudfront and s.griddo.io xff. xff on shurly.griddo.io means the viewer address isn't
used, and the rate limits count CloudFront's edges; socket, the health checks aside, means
TRUSTED_PROXIES doesn't name the ALB (DEPLOYMENT.md § Monitoring).
"""

import json

import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr

from main import app
from server.core.config import settings
from server.utils.network import client_ip, client_ip_and_source, request_host
from tests.test_phase63_cloudfront_client_ip import (
    ALB,
    EDGE,
    SECRET,
    VIEWER,
    _request,
    _through_cloudfront,
)


@pytest.fixture
def behind_the_alb(monkeypatch):
    monkeypatch.setattr(settings, "trusted_proxies", ["172.31.0.0/16"])
    monkeypatch.setattr(settings, "cloudfront_origin_secrets", [SecretStr(SECRET)])


@pytest.mark.usefixtures("behind_the_alb")
@pytest.mark.parametrize(
    ("headers", "peer", "found"),
    [
        (_through_cloudfront(f"{VIEWER}:46532"), ALB, (VIEWER, "cloudfront")),
        # Through CloudFront, but a viewer address it didn't write (AllViewer): the edge.
        (_through_cloudfront("6.6.6.6:1"), ALB, (EDGE, "xff")),
        ({"x-forwarded-for": "198.51.100.9"}, ALB, ("198.51.100.9", "xff")),
        ({"x-forwarded-for": "172.31.0.7, 172.31.0.8"}, ALB, ("172.31.0.7", "xff")),
        # A peer that isn't a trusted proxy: what it says is ignored.
        ({"x-forwarded-for": "198.51.100.9"}, "198.51.100.50", ("198.51.100.50", "socket")),
        ({}, ALB, (ALB, "socket")),  # the ALB's own health check
        ({"x-forwarded-for": " , "}, ALB, (ALB, "socket")),
        ({}, None, ("unknown", "socket")),
    ],
)
def test_each_source(headers, peer, found):
    request = _request(headers, peer=peer)

    assert client_ip_and_source(request) == found
    assert client_ip(request) == found[0]


def test_without_trusted_proxies_always_the_socket(monkeypatch):
    monkeypatch.setattr(settings, "trusted_proxies", [])

    request = _request({"x-forwarded-for": "198.51.100.9"}, peer=ALB)

    assert client_ip_and_source(request) == (ALB, "socket")


@pytest.mark.parametrize(
    ("host", "shown"),
    [
        ("Shurly.Griddo.io", "shurly.griddo.io"),
        ("s.griddo.io:443", "s.griddo.io"),
        ("[2001:DB8::1]:8000", "[2001:db8::1]"),
        ("", ""),
        ("x" * 300, "x" * 255),
    ],
)
def test_the_host_as_logged(host, shown):
    assert request_host(_request({"host": host} if host else {})) == shown


def _line(stderr: str) -> dict:
    (line,) = [
        record
        for record in (json.loads(x) for x in stderr.splitlines() if x.startswith("{"))
        if record["event"] == "http.request"
    ]
    return line


@pytest.mark.usefixtures("behind_the_alb")
class TestTheLogLine:
    def test_through_cloudfront(self, capsys):
        alb = TestClient(app, client=(ALB, 50000))
        capsys.readouterr()

        alb.get(
            "/api/v1/health",
            headers={**_through_cloudfront(f"{VIEWER}:46532"), "host": "shurly.griddo.io"},
        )

        line = _line(capsys.readouterr().err)
        assert (line["host"], line["client_ip_source"]) == ("shurly.griddo.io", "cloudfront")

    def test_straight_to_the_alb_and_never_the_address(self, capsys):
        alb = TestClient(app, client=(ALB, 50000))
        capsys.readouterr()

        alb.get("/api/v1/health", headers={"x-forwarded-for": VIEWER, "host": "s.griddo.io"})

        line = _line(capsys.readouterr().err)
        assert (line["host"], line["client_ip_source"]) == ("s.griddo.io", "xff")
        logged = json.dumps(line)
        assert VIEWER not in logged and "203.0.113.0" not in logged and ALB not in logged
