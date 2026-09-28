"""
Phase 6.3 — the client IP behind CloudFront.

Through CloudFront (shurly.griddo.io, 4.10) the ALB's peer is a CloudFront edge, so
X-Forwarded-For's rightmost untrusted address is the edge's. CloudFront sends the
viewer's address in CloudFront-Viewer-Address, which is believed only on a request
carrying the distribution's secret origin header: the ALB is shared and reachable
directly, and anyone can send the viewer header, but not the secret. `client_ip` is
the one place that decides: the rate limits count it, and visits store it.
"""

import json

import pytest
from pydantic import SecretStr, ValidationError
from starlette.requests import Request

from server.core.config import Settings, settings
from server.core.models import URL, OrphanVisit, URLType, Visitor
from server.utils.domain import get_or_create_default_domain
from server.utils.network import came_through_cloudfront, client_ip, cloudfront_viewer

SECRET = "cf-origin-0123456789abcdef0123456789abcdef"
PREVIOUS = "cf-origin-fedcba9876543210fedcba9876543210"  # still accepted while it rotates
ALB = "172.31.0.10"
EDGE = "130.176.0.1"  # a CloudFront edge, as the ALB sees it
VIEWER = "203.0.113.7"


@pytest.fixture
def behind_cloudfront(monkeypatch):
    secrets = [SecretStr(SECRET), SecretStr(PREVIOUS)]
    monkeypatch.setattr(settings, "cloudfront_origin_secrets", secrets)
    monkeypatch.setattr(settings, "trusted_proxies", ["172.31.0.0/16"])


def _request(headers: dict[str, str], peer: str | None = ALB) -> Request:
    return Request(
        {
            "type": "http",
            "method": "GET",
            "path": "/",
            "headers": [(k.lower().encode(), v.encode()) for k, v in headers.items()],
            "client": (peer, 443) if peer else None,
        }
    )


def _through_cloudfront(
    viewer: str | None, appended: str = VIEWER, secret: str | None = SECRET
) -> dict[str, str]:
    """
    What reaches the app through CloudFront and the ALB: `viewer` is the
    CloudFront-Viewer-Address, and X-Forwarded-For is what the viewer sent, then the
    address CloudFront appended (`appended`), then the edge the ALB appended.
    """
    headers = {"x-forwarded-for": f"198.51.100.200, {appended}, {EDGE}"}
    if secret is not None:
        headers["x-origin-verify"] = secret
    if viewer is not None:
        headers["cloudfront-viewer-address"] = viewer
    return headers


@pytest.mark.usefixtures("behind_cloudfront")
class TestClientIp:
    def test_the_viewer_address_is_the_client(self):
        assert client_ip(_request(_through_cloudfront(f"{VIEWER}:46532"))) == VIEWER

    def test_either_secret_works_while_it_rotates(self):
        headers = _through_cloudfront(f"{VIEWER}:46532", secret=PREVIOUS)

        assert client_ip(_request(headers)) == VIEWER

    @pytest.mark.parametrize(
        ("viewer", "appended", "ip"),
        [
            (
                "2001:db8:85a3::8a2e:370:7334:46532",
                "2001:db8:85a3::8a2e:370:7334",
                "2001:db8:85a3::8a2e:370:7334",
            ),
            # The same address written two ways still matches.
            ("2001:0db8:0000:0000:0000:0000:0000:0001:443", "2001:db8::1", "2001:db8::1"),
            ("[2001:db8::1]:443", "2001:0db8::0001", "2001:db8::1"),
        ],
    )
    def test_ipv6_the_port_follows_the_last_colon(self, viewer, appended, ip):
        assert client_ip(_request(_through_cloudfront(viewer, appended))) == ip

    def test_a_viewer_address_other_than_the_one_cloudfront_appended_falls_back(self):
        """Under an origin request policy that doesn't add CloudFront's headers
        (AllViewer), the viewer's own `CloudFront-Viewer-Address` reaches the app next
        to a genuine secret. It can't match the address CloudFront appended."""
        headers = _through_cloudfront("6.6.6.6:1234")

        assert client_ip(_request(headers)) == EDGE

    @pytest.mark.parametrize("forwarded_for", [EDGE, None])
    def test_without_the_address_cloudfront_appended_it_falls_back(self, forwarded_for):
        """The ALB no longer appends ("append" isn't its X-Forwarded-For mode), or
        nothing reached it: nothing to check the viewer address against."""
        headers = _through_cloudfront(f"{VIEWER}:46532")
        del headers["x-forwarded-for"]
        if forwarded_for:
            headers["x-forwarded-for"] = forwarded_for

        assert client_ip(_request(headers)) == (forwarded_for or ALB)

    @pytest.mark.parametrize("secret", [None, "", "wrong-0123456789abcdef0123456789abcdef"])
    def test_without_the_secret_the_viewer_address_is_ignored(self, secret):
        """Straight to the ALB with a forged pair that passes the cross-check: the
        viewer header, and the same address sent in X-Forwarded-For."""
        headers = _through_cloudfront("6.6.6.6:1234", appended="6.6.6.6", secret=secret)

        assert client_ip(_request(headers)) == EDGE

    @pytest.mark.parametrize(
        "viewer", [None, "", "garbage", "203.0.113.7", "203.0.113.7:port", "999.1.1.1:80"]
    )
    def test_with_the_secret_a_missing_or_malformed_viewer_address_falls_back(self, viewer):
        """To X-Forwarded-For's answer: never "unknown", never the forged value."""
        assert client_ip(_request(_through_cloudfront(viewer))) == EDGE

    def test_a_request_straight_to_the_alb_is_unchanged(self):
        assert client_ip(_request({"x-forwarded-for": "203.0.113.9"})) == "203.0.113.9"


def test_off_by_default_the_viewer_address_is_ignored(monkeypatch):
    monkeypatch.setattr(settings, "trusted_proxies", ["172.31.0.0/16"])
    assert settings.cloudfront_origin_secrets == []

    for secret in (None, "", SECRET):
        headers = _through_cloudfront("6.6.6.6:1234", appended="6.6.6.6", secret=secret)
        assert client_ip(_request(headers)) == EDGE


def test_one_forwarded_address_is_never_the_one_cloudfront_appended():
    """Even when it's the viewer's: without the edge the ALB appends after it, nothing
    says which entry CloudFront wrote."""
    assert cloudfront_viewer(f"{VIEWER}:46532", VIEWER) is None
    assert cloudfront_viewer(f"{VIEWER}:46532", f"{VIEWER}, {EDGE}") == VIEWER


def test_no_header_never_proves_it_even_against_an_empty_secret():
    """The settings refuse an empty secret; this doesn't lean on that."""
    assert not came_through_cloudfront(None, [SecretStr("")])
    assert not came_through_cloudfront("", [SecretStr("")])


class TestSettings:
    def test_two_secrets_from_the_environment(self):
        parsed = Settings(cloudfront_origin_secrets=json.dumps([SECRET, PREVIOUS]))

        assert [s.get_secret_value() for s in parsed.cloudfront_origin_secrets] == [
            SECRET,
            PREVIOUS,
        ]

    def test_the_secrets_never_show_in_the_settings(self):
        """A traceback that prints the settings mustn't print the secrets."""
        parsed = Settings(cloudfront_origin_secrets=[SECRET, PREVIOUS])

        assert SECRET not in repr(parsed) and PREVIOUS not in str(parsed)

    @pytest.mark.parametrize("weak", ["", "changeme", "x" * 31])
    def test_a_short_secret_is_refused(self, weak):
        """Anyone who guesses it chooses the address they're counted and logged under."""
        with pytest.raises(ValidationError, match="32 characters"):
            Settings(cloudfront_origin_secrets=[SECRET, weak])


@pytest.mark.usefixtures("behind_cloudfront")
class TestVisits:
    @pytest.fixture
    def link(self, db_session, test_user):
        url = URL(
            short_code="cfvisit",
            original_url="https://example.com",
            url_type=URLType.STANDARD,
            created_by=test_user.id,
            domain_id=get_or_create_default_domain(db_session).id,
        )
        db_session.add(url)
        db_session.commit()
        return url

    @pytest.mark.parametrize(
        ("anonymize", "stored"), [(True, "203.0.113.0"), (False, "203.0.113.77")]
    )
    def test_the_visit_stores_the_viewer_anonymized_after_resolution(
        self, client, db_session, link, monkeypatch, anonymize, stored
    ):
        """Resolved first, then truncated: truncating the edge's address would store the
        wrong network."""
        monkeypatch.setattr(settings, "anonymize_remote_addr", anonymize)

        headers = _through_cloudfront("203.0.113.77:5555", "203.0.113.77")
        response = client.get("/cfvisit", headers=headers, follow_redirects=False)

        assert response.status_code == 302
        assert db_session.query(Visitor).one().ip == stored

    @pytest.mark.parametrize(
        ("anonymize", "stored"), [(True, "203.0.113.0"), (False, "203.0.113.77")]
    )
    @pytest.mark.parametrize("path", ["/", "/no-such-code"])
    def test_orphan_visits_store_the_client_ip_the_same_way(
        self, client, db_session, monkeypatch, path, anonymize, stored
    ):
        """They stored the socket's address: the ALB's, or unanonymized for the bare URL."""
        monkeypatch.setattr(settings, "anonymize_remote_addr", anonymize)

        response = client.get(
            path, headers=_through_cloudfront("203.0.113.77:5555", "203.0.113.77")
        )

        assert response.status_code == 404
        assert db_session.query(OrphanVisit).one().ip == stored
