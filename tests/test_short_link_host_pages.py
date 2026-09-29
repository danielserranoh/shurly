"""
What the short-link host answers besides a redirect (ROADMAP 3.9.2 follow-ups):

- `/favicon.ico`: browsers ask every host for its icon. Here there's none: a 204 cached for a
  week, and never an orphan visit (it would be one in "Typos & broken links" otherwise).
- `/robots.txt` stays as it was.
- A social crawler's preview page comes with a strict CSP, as the unavailable-link page does: its
  one style block by hash, and nothing else. It loads no image (the OG image is a meta tag the
  crawler fetches itself), and its meta refresh and link aren't loads a CSP governs.
"""

import base64
import hashlib
import re

import pytest

from server.core.models import URL, OrphanVisit
from server.utils.domain import get_or_create_default_domain

CRAWLER = "facebookexternalhit/1.1 (+http://www.facebook.com/externalhit_uatext.php)"


def test_the_favicon_is_no_content_cached_a_week(client):
    response = client.get("/favicon.ico")

    assert (response.status_code, response.content) == (204, b"")
    assert response.headers["cache-control"] == "public, max-age=604800"


def test_the_favicon_is_no_orphan_visit(client, db_session):
    client.get("/favicon.ico")

    assert db_session.query(OrphanVisit).count() == 0


def test_robots_txt_is_as_it_was(client):
    response = client.get("/robots.txt")

    assert (response.status_code, response.text) == (200, "User-agent: *\nDisallow: /\n")
    assert response.headers["content-type"].startswith("text/plain")


@pytest.fixture
def preview(client, db_session, test_user):
    db_session.add(
        URL(
            short_code="prev01",
            original_url="https://example.com/article",
            title="An article",
            og_image_url="https://images.example.com/cover.png",
            created_by=test_user.id,
            domain_id=get_or_create_default_domain(db_session).id,
        )
    )
    db_session.commit()
    response = client.get("/prev01", headers={"user-agent": CRAWLER}, follow_redirects=False)
    assert response.status_code == 200
    return response


def test_the_preview_comes_with_a_strict_csp_that_allows_its_style_by_hash(preview):
    style = re.search(r"<style>(.*?)</style>", preview.text, re.S).group(1)
    digest = base64.b64encode(hashlib.sha256(style.encode()).digest()).decode()

    assert preview.headers["content-security-policy"] == (
        f"default-src 'none'; style-src 'sha256-{digest}'; base-uri 'none'; "
        "form-action 'none'; frame-ancestors 'none'"
    )


def test_the_preview_loads_nothing_its_csp_would_block(preview):
    """No style attribute (a hash doesn't cover one), no script, and no image: the OG image
    is a meta tag the crawler fetches, not a load of the page's."""
    assert "style=" not in preview.text
    assert "<script" not in preview.text and "<img" not in preview.text
    assert 'property="og:image" content="https://images.example.com/cover.png"' in preview.text


def test_the_preview_still_refreshes_and_caches_as_it_did(preview):
    assert 'http-equiv="refresh" content="2;url=https://example.com/article"' in preview.text
    assert preview.headers["cache-control"] == "public, max-age=300"
