"""
Phase 6.3 — a request's client address and scheme come from the app alone, and only from a proxy in
TRUSTED_PROXIES (server/utils/network.py), never from uvicorn.

uvicorn ran with `--proxy-headers --forwarded-allow-ips "*"`: it trusted every peer, took the leftmost
X-Forwarded-For entry, which the client itself writes, and put it in place of the connection's
address before the app ran. On the path straight to the ALB (go.griddo.io) anyone could choose their
address. The per-IP rate limits keyed on it, and visits stored it, their country and city too (found
in production on 2026-09-29).

Now the image runs uvicorn with `--no-proxy-headers`, and the app reads X-Forwarded-Proto itself, from
a trusted proxy only (`ForwardedProtoMiddleware`), so a redirect built from the scheme stays https
behind the ALB. These tests run the real uvicorn with the dockerfile's CMD flags, not TestClient,
with the test playing the ALB from 127.0.0.1.
"""

import json
import re
import threading
import time
from pathlib import Path

import httpx
import pytest
import uvicorn
from uvicorn.main import main as uvicorn_cli

from main import create_app
from server.core import get_db
from server.core.config import settings
from server.core.models import OrphanVisit
from server.utils import rate_limit
from tests.conftest import TestingSessionLocal

ROOT = Path(__file__).parents[1]
FORGED, APPENDED = "198.51.100.201", "203.0.113.9"  # what the client wrote; what the ALB appended


def _cmd_options() -> dict:
    """The dockerfile's CMD, parsed by uvicorn's own command line."""
    dockerfile = (ROOT / "dockerfile").read_text()
    cmd = json.loads(re.search(r"^CMD (\[.*?\])", dockerfile, re.S | re.M)[1].replace("\\\n", ""))
    assert cmd[:2] == ["uvicorn", "main:app"], cmd
    return uvicorn_cli.make_context("uvicorn", cmd[1:]).params


def _session():
    db = TestingSessionLocal()
    try:
        yield db
    finally:
        db.close()


@pytest.fixture
def serve(db_session, monkeypatch):
    """The app behind the real uvicorn, with the CMD's proxy options, on a free local port."""
    servers = []

    def start(trusted_proxies: list[str]) -> str:
        monkeypatch.setattr(settings, "trusted_proxies", trusted_proxies)
        app = create_app()
        app.dependency_overrides[get_db] = _session
        options = _cmd_options()
        config = uvicorn.Config(
            app,
            host="127.0.0.1",
            port=0,
            proxy_headers=options["proxy_headers"],
            forwarded_allow_ips=options["forwarded_allow_ips"],
            access_log=options["access_log"],
            lifespan="off",
            log_level="warning",
        )
        server = uvicorn.Server(config)
        thread = threading.Thread(target=server.run, daemon=True)
        thread.start()
        for _ in range(200):
            if server.started:
                break
            time.sleep(0.02)
        servers.append((server, thread))
        port = server.servers[0].sockets[0].getsockname()[1]
        return f"http://127.0.0.1:{port}"

    yield start
    for server, thread in servers:
        server.should_exit = True
        thread.join(timeout=5)


def _orphan_ip(db_session, path: str) -> str:
    db_session.expire_all()
    (visit,) = db_session.query(OrphanVisit).filter(OrphanVisit.attempted_path == path).all()
    return visit.ip


class TestTheClientAddress:
    def test_a_forged_forwarded_for_isnt_the_client(self, serve, db_session):
        """Behind the ALB: the client's own X-Forwarded-For entry is ignored, and the address the
        ALB appended is the client's."""
        base = serve(["127.0.0.1/32"])

        httpx.get(f"{base}/zz-forged", headers={"x-forwarded-for": f"{FORGED}, {APPENDED}"})

        assert _orphan_ip(db_session, "/zz-forged") == "203.0.113.0"  # anonymized, the ALB's entry

    def test_from_a_peer_that_isnt_a_trusted_proxy_the_socket(self, serve, db_session):
        base = serve(["10.0.0.0/8"])

        httpx.get(f"{base}/zz-direct", headers={"x-forwarded-for": f"{FORGED}, {APPENDED}"})

        assert _orphan_ip(db_session, "/zz-direct") == "127.0.0.0"

    def test_the_rate_limit_counts_the_client_whatever_it_forges(self, serve, monkeypatch):
        """What production showed: a new forged address each time was never limited. The clock
        stands still mid-window: the limits count per minute, and 21 logins that straddled one
        started a new count (a flake in CI, where they take seconds)."""
        monkeypatch.setattr(rate_limit, "_now", lambda: 1_790_000_030.0)
        base = serve(["127.0.0.1/32"])

        statuses = [
            httpx.post(
                f"{base}/api/v1/auth/login",
                json={"email": f"nobody{n}@example.com", "password": "wrong-password"},
                headers={"x-forwarded-for": f"198.51.100.{n}, {APPENDED}"},
            ).status_code
            for n in range(settings.rate_limit_login_per_ip + 1)
        ]

        assert statuses[-1] == 429
        assert 429 not in statuses[:-1]


class TestTheScheme:
    @pytest.mark.parametrize(
        ("proto", "scheme"),
        [("https", "https"), ("http", "http"), ("http, https", "https"), ("gopher", "http")],
    )
    def test_from_the_trusted_proxy(self, serve, proto, scheme):
        """Starlette's trailing-slash redirect builds its URL from the scheme: behind the ALB, whose
        listener is https, it must stay https. Its rightmost value is the ALB's own."""
        base = serve(["127.0.0.1/32"])

        redirect = httpx.get(f"{base}/api/v1/health/", headers={"x-forwarded-proto": proto})

        assert redirect.status_code == 307
        assert redirect.headers["location"].startswith(f"{scheme}://")

    def test_from_anyone_else_ignored(self, serve):
        base = serve(["10.0.0.0/8"])

        redirect = httpx.get(f"{base}/api/v1/health/", headers={"x-forwarded-proto": "https"})

        assert redirect.headers["location"].startswith("http://")


def test_the_image_runs_uvicorn_without_its_proxy_headers():
    """uvicorn's --proxy-headers takes the client's address too, before the app sees the request.
    It's on by default, so it has to be switched off."""
    options = _cmd_options()

    assert options["proxy_headers"] is False
