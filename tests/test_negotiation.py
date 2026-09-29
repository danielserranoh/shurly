"""
`prefers_html`: whether a request to the public redirect path asks for a page, as a person's browser
does, or for the JSON everything else has always had. A page only when the Accept header names
text/html and prefers it to application/json; a wildcard alone, JSON, no header or a tie: JSON.
"""

import pytest

from server.utils.negotiation import prefers_html

CHROME = (
    "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,"
    "*/*;q=0.8,application/signed-exchange;v=b3;q=0.7"
)
FIREFOX = "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8"
SAFARI = "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8"


@pytest.mark.parametrize(
    "accept", [CHROME, FIREFOX, SAFARI, "text/html", "TEXT/HTML; charset=utf-8"]
)
def test_a_browser_gets_a_page(accept):
    assert prefers_html(accept) is True


@pytest.mark.parametrize(
    "accept",
    [
        None,  # no header
        "",
        "*/*",  # curl, fetch(), httpx, requests
        "application/json",
        "application/json, text/plain, */*",  # axios
        "text/html, application/json",  # a tie: JSON, as it always was
        "text/html;q=0",  # not acceptable
        "text/html;q=0.5, application/json",
        "text/html;q=0.8, */*",  # the wildcard is preferred
        "text/*",  # no page asked for by name
        "text/html;q=nonsense",  # a quality it can't read counts as none
    ],
)
def test_anything_else_gets_json(accept):
    assert prefers_html(accept) is False


def test_json_preferred_less_than_the_page():
    assert prefers_html("application/json;q=0.5, text/html") is True
