"""Phase 3.9.6 — small architectural improvements ("free wins")."""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from server.core.models import URL, ApiKeyScope, User
from server.core.models.url import URLType


@pytest.mark.integration
class TestRequestIdMiddleware:
    """Phase 3.9.6 — X-Request-Id is generated and echoed."""

    def test_response_has_generated_request_id(self, client: TestClient):
        r = client.get("/robots.txt")
        assert r.status_code == 200
        assert "x-request-id" in r.headers
        assert len(r.headers["x-request-id"]) >= 16

    def test_client_supplied_id_is_echoed(self, client: TestClient):
        rid = "00000000-1111-2222-3333-444444444444"
        r = client.get("/robots.txt", headers={"X-Request-Id": rid})
        assert r.headers["x-request-id"] == rid


@pytest.mark.integration
class TestShortUrlMode:
    """Phase 3.9.6 — `loose` mode normalizes generated codes to lowercase."""

    def test_generated_codes_lowercase_in_loose_mode(
        self, client: TestClient, auth_headers: dict, monkeypatch: pytest.MonkeyPatch
    ):
        from server.app import urls as urls_module
        from server.utils.opengraph import OpenGraphMetadata

        async def _empty_og(*_a, **_kw):
            return OpenGraphMetadata()

        monkeypatch.setattr(urls_module, "fetch_opengraph_metadata", _empty_og)

        # Create several URLs to give the random generator a chance to surface uppercase
        codes = []
        for _ in range(20):
            r = client.post(
                "/api/v1/urls",
                json={"url": "https://example.com"},
                headers=auth_headers,
            )
            assert r.status_code == 201
            codes.append(r.json()["short_code"])

        for code in codes:
            assert code == code.lower(), f"{code!r} contains uppercase in loose mode"

    def test_custom_slug_lowercased(
        self, client: TestClient, auth_headers: dict, monkeypatch: pytest.MonkeyPatch
    ):
        from server.app import urls as urls_module
        from server.utils.opengraph import OpenGraphMetadata

        async def _empty_og(*_a, **_kw):
            return OpenGraphMetadata()

        monkeypatch.setattr(urls_module, "fetch_opengraph_metadata", _empty_og)

        r = client.post(
            "/api/v1/urls/custom",
            json={"url": "https://example.com", "custom_code": "MyLink"},
            headers=auth_headers,
        )
        assert r.status_code == 201
        assert r.json()["short_code"] == "mylink"


@pytest.mark.integration
class TestShortCodeCollisionRetry:
    """Phase 3.9.6 — UNIQUE collisions trigger re-roll, not a 500."""

    def test_first_n_candidates_taken_then_succeeds(
        self,
        client: TestClient,
        auth_headers: dict,
        db_session: Session,
        test_user: User,
        monkeypatch: pytest.MonkeyPatch,
    ):
        from server.app import urls as urls_module
        from server.utils.opengraph import OpenGraphMetadata

        async def _empty_og(*_a, **_kw):
            return OpenGraphMetadata()

        monkeypatch.setattr(urls_module, "fetch_opengraph_metadata", _empty_og)

        # Pre-seed two URLs whose codes will be returned by our patched generator
        # first. They must live on the default domain so the per-domain UNIQUE
        # check (Phase 3.10.1) sees them as collisions.
        from server.utils.domain import get_or_create_default_domain

        domain = get_or_create_default_domain(db_session)
        for taken in ["aaaaaa", "bbbbbb"]:
            db_session.add(
                URL(
                    short_code=taken,
                    domain_id=domain.id,
                    original_url="https://x",
                    url_type=URLType.STANDARD,
                    created_by=test_user.id,
                )
            )
        db_session.commit()

        sequence = iter(["aaaaaa", "bbbbbb", "cccccc"])
        monkeypatch.setattr(
            urls_module,
            "generate_short_code",
            lambda length=6: next(sequence),
        )

        r = client.post(
            "/api/v1/urls",
            json={"url": "https://example.com"},
            headers=auth_headers,
        )
        assert r.status_code == 201
        assert r.json()["short_code"] == "cccccc"

    def test_exhausted_attempts_returns_500(
        self,
        client: TestClient,
        auth_headers: dict,
        db_session: Session,
        test_user: User,
        monkeypatch: pytest.MonkeyPatch,
    ):
        from server.app import urls as urls_module
        from server.utils.opengraph import OpenGraphMetadata

        async def _empty_og(*_a, **_kw):
            return OpenGraphMetadata()

        monkeypatch.setattr(urls_module, "fetch_opengraph_metadata", _empty_og)

        from server.utils.domain import get_or_create_default_domain

        domain = get_or_create_default_domain(db_session)
        db_session.add(
            URL(
                short_code="zzzzzz",
                domain_id=domain.id,
                original_url="https://x",
                url_type=URLType.STANDARD,
                created_by=test_user.id,
            )
        )
        db_session.commit()

        monkeypatch.setattr(urls_module, "generate_short_code", lambda length=6: "zzzzzz")
        r = client.post(
            "/api/v1/urls",
            json={"url": "https://example.com"},
            headers=auth_headers,
        )
        assert r.status_code == 500
        assert "unique" in r.json()["detail"].lower()


class TestOGCharsetFallback:
    """Phase 3.9.6 — OG fetcher decodes via meta charset and never crashes."""

    def test_decode_response_with_meta_charset(self):
        import httpx

        from server.utils.opengraph import _decode_response_body

        body = (
            "<html><head><meta charset='ISO-8859-1'>"
            "<title>caf\xe9</title></head></html>"
        ).encode("latin-1")
        # Simulate a server that DID NOT set Content-Type charset
        response = httpx.Response(200, content=body, headers={"Content-Type": "text/html"})
        text = _decode_response_body(response)
        assert text is not None
        assert "café" in text

    def test_decode_falls_back_to_replacement(self):
        import httpx

        from server.utils.opengraph import _decode_response_body

        # Bytes that aren't valid utf-8 and have no meta-charset hint
        body = b"\xff\xfe\xfd not html really"
        response = httpx.Response(200, content=body, headers={"Content-Type": "text/html"})
        text = _decode_response_body(response)
        # Must not raise; fallback uses errors='replace'
        assert text is not None


@pytest.mark.integration
class TestApiKeyScope:
    """Phase 3.9.6 — API key scope data model (single scope at launch)."""

    def test_generated_key_has_full_access_scope(
        self, client: TestClient, auth_headers: dict, db_session: Session, test_user: User
    ):
        r = client.post("/api/v1/auth/api-key/generate", headers=auth_headers)
        assert r.status_code == 200
        assert r.json()["scope"] == ApiKeyScope.FULL_ACCESS.value

        db_session.refresh(test_user)
        assert test_user.api_key is not None
        assert test_user.api_key_scope == ApiKeyScope.FULL_ACCESS

    def test_scope_enum_exposes_reserved_values(self):
        # Reserved-but-unused; presence of the enum members protects against
        # destructive migrations when we enforce scopes post-launch.
        assert {s.value for s in ApiKeyScope} >= {
            "full_access",
            "read_only",
            "create_only",
            "domain_specific",
        }
