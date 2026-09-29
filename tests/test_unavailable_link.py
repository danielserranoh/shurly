"""
A short link that doesn't lead anywhere (ROADMAP 3.9.2, Shlink parity): no such code, not live yet,
expired, or its visit limit used up.

- A person's browser gets a page (`server/templates/link_unavailable.html`) with the same status the
  JSON has: 404, or 410. Not live yet looks exactly like no such code, so a scheduled link isn't
  revealed. The page shows nothing from the request, not even the code, and comes with a strict CSP
  that allows its one style block by hash.
- Everything else gets the JSON it always had.
- INVALID_SHORT_URL_REDIRECT, Shlink's "invalid short URL" redirect, sends everyone there instead:
  a 302 that isn't cached. An unknown code is still logged as an orphan visit first.
"""

import base64
import hashlib
import re
from datetime import datetime, timedelta, timezone

import pytest
from pydantic import ValidationError

from server.core.config import Settings, settings
from server.core.models import URL, OrphanVisit, Visitor
from server.utils.domain import get_or_create_default_domain

BROWSER = "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8"
ELSEWHERE = "https://griddo.io/link-not-found"
NOW = datetime.now(timezone.utc)

# The four ways a link can't be followed: its code, status, heading and JSON detail.
CASES = {
    "unknown": ("nosuch1", 404, "This link doesn’t lead anywhere", "Short URL 'nosuch1' not found"),
    "not_yet": ("later01", 404, "This link doesn’t lead anywhere", "Short URL 'later01' not found"),
    "expired": ("gone001", 410, "This link has expired", "This short URL has expired"),
    "used_up": (
        "used001",
        410,
        "This link has reached its limit",
        "This short URL has reached its visit limit",
    ),
}


@pytest.fixture
def links(db_session, test_user) -> None:
    domain = get_or_create_default_domain(db_session)

    def link(code: str, **fields) -> URL:
        url = URL(
            short_code=code,
            original_url="https://example.com/destination",
            created_by=test_user.id,
            domain_id=domain.id,
            **fields,
        )
        db_session.add(url)
        return url

    link("later01", valid_since=NOW + timedelta(days=3))
    link("gone001", valid_until=NOW - timedelta(days=1))
    used = link("used001", max_visits=1)
    db_session.flush()
    db_session.add(Visitor(url_id=used.id, short_code="used001", ip="203.0.113.0"))
    db_session.commit()


def _vary_of(headers) -> list[str]:
    return [value.strip() for value in headers.get("vary", "").split(",")]


def _vary(response) -> list[str]:
    return _vary_of(response.headers)


def _get(client, code: str, accept: str | None):
    headers = {"accept": accept} if accept is not None else {}
    return client.get(f"/{code}", headers=headers, follow_redirects=False)


@pytest.mark.parametrize("case", list(CASES))
def test_a_browser_gets_a_page_with_the_same_status(client, links, case):
    code, status, heading, _ = CASES[case]

    response = _get(client, code, BROWSER)

    assert response.status_code == status
    assert response.headers["content-type"].startswith("text/html")
    assert f"<h1>{heading}</h1>" in response.text
    assert code not in response.text  # nothing from the request: not even the code


def test_not_live_yet_looks_exactly_like_no_such_link(client, links):
    """3.9.2's 404 for a scheduled link, so it isn't revealed: the page doesn't either."""
    assert _get(client, "later01", BROWSER).text == _get(client, "nosuch1", BROWSER).text


@pytest.mark.parametrize("case", list(CASES))
@pytest.mark.parametrize("accept", ["application/json", "*/*", None])
def test_anything_else_gets_the_json_it_always_had(client, links, case, accept):
    code, status, _, detail = CASES[case]

    response = _get(client, code, accept)

    assert (response.status_code, response.json()) == (status, {"detail": detail})
    assert "Accept" in _vary(response)


@pytest.mark.parametrize("case", list(CASES))
def test_the_page_comes_with_a_strict_csp_that_allows_its_style_by_hash(client, links, case):
    response = _get(client, CASES[case][0], BROWSER)

    style = re.search(r"<style>(.*?)</style>", response.text, re.S).group(1)
    digest = base64.b64encode(hashlib.sha256(style.encode()).digest()).decode()
    assert response.headers["content-security-policy"] == (
        f"default-src 'none'; style-src 'sha256-{digest}'; img-src data:; base-uri 'none'; "
        "form-action 'none'; frame-ancestors 'none'"
    )
    assert "<script" not in response.text and "style=" not in response.text
    assert not re.search(r"(?:src|href)=\"https?:", response.text)  # asks for nothing else


def test_the_page_isnt_cached_indexed_or_sniffed(client, links):
    headers = _get(client, "gone001", BROWSER).headers

    assert headers["cache-control"] == "no-store" and "Accept" in _vary_of(headers)
    assert (headers["x-robots-tag"], headers["x-content-type-options"]) == ("noindex", "nosniff")
    assert headers["referrer-policy"] == "no-referrer"


@pytest.mark.parametrize("accept", [BROWSER, "application/json"])
def test_an_unknown_code_is_still_an_orphan_visit(client, db_session, links, accept):
    _get(client, "nosuch1", accept)
    _get(client, "later01", accept)  # a link, not an orphan

    assert [o.attempted_path for o in db_session.query(OrphanVisit)] == ["/nosuch1"]


# ---------------------------------------------------------------------------
# INVALID_SHORT_URL_REDIRECT
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("case", list(CASES))
@pytest.mark.parametrize("accept", [BROWSER, "application/json"])
def test_the_setting_sends_everyone_elsewhere(client, links, monkeypatch, case, accept):
    monkeypatch.setattr(settings, "invalid_short_url_redirect", ELSEWHERE)

    response = _get(client, CASES[case][0], accept)

    assert (response.status_code, response.headers["location"]) == (302, ELSEWHERE)
    assert response.headers["cache-control"] == "private, max-age=0"


def test_the_setting_still_logs_the_orphan_first(client, db_session, links, monkeypatch):
    monkeypatch.setattr(settings, "invalid_short_url_redirect", ELSEWHERE)

    _get(client, "nosuch1", BROWSER)

    assert [o.attempted_path for o in db_session.query(OrphanVisit)] == ["/nosuch1"]


def test_a_link_that_works_isnt_affected(client, db_session, test_user, monkeypatch):
    monkeypatch.setattr(settings, "invalid_short_url_redirect", ELSEWHERE)
    db_session.add(
        URL(
            short_code="works01",
            original_url="https://example.com/fine",
            created_by=test_user.id,
            domain_id=get_or_create_default_domain(db_session).id,
        )
    )
    db_session.commit()

    response = _get(client, "works01", BROWSER)

    assert (response.status_code, response.headers["location"]) == (302, "https://example.com/fine")


@pytest.mark.parametrize("value", ["", "https://griddo.io/404", "http://example.com"])
def test_the_setting_takes_an_absolute_http_url_or_nothing(value):
    assert Settings(invalid_short_url_redirect=value).invalid_short_url_redirect == value


@pytest.mark.parametrize(
    "value",
    ["/not-found", "griddo.io/404", "ftp://griddo.io/404", "javascript:alert(1)", "https://"],
)
def test_anything_else_stops_the_app_starting(value):
    with pytest.raises(ValidationError, match="invalid_short_url_redirect"):
        Settings(invalid_short_url_redirect=value)
