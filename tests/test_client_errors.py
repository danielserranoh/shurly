"""
Browser errors reach the logs (ROADMAP 5.6.1, 6.4): POST /api/v1/client-errors takes a report from the web app,
signed in or not, and logs one `client.error` line next to the API's own. Never the IP; never a query string or a
fragment; the account's id only when there's one. Limited per IP.
"""

import json

import pytest
from fastapi.testclient import TestClient

from main import app
from server.core.config import settings

ROUTE = "/api/v1/client-errors"
REPORT = {
    "kind": "error",
    "message": "TypeError: Cannot read properties of undefined (reading 'short_url')",
    "source": "/_astro/link.Ab12cd.js:3:1403",
    "page": "/dashboard/link/",
}


def _lines(capsys) -> list[dict]:
    """Every event line written so far, parsed."""
    return [
        json.loads(line) for line in capsys.readouterr().err.splitlines() if line.startswith("{")
    ]


def _reports(capsys) -> list[dict]:
    return [line for line in _lines(capsys) if line["event"] == "client.error"]


def test_an_anonymous_report_is_logged_without_an_account_or_an_address(client, capsys):
    response = client.post(ROUTE, json=REPORT)

    assert response.status_code == 204
    assert response.content == b""
    [line] = _reports(capsys)
    assert {k: line[k] for k in ("kind", "message", "source", "page")} == REPORT
    assert "user_id" not in line
    assert not {"ip", "client", "remote_addr", "user_agent"} & set(line)
    assert "testclient" not in json.dumps(line)  # the test client's address


def test_a_signed_in_report_names_the_account(client, auth_headers, test_user, capsys):
    assert client.post(ROUTE, json=REPORT, headers=auth_headers).status_code == 204

    [line] = _reports(capsys)
    assert line["user_id"] == str(test_user.id)


def test_a_token_that_does_not_check_out_is_just_anonymous(client, capsys):
    response = client.post(ROUTE, json=REPORT, headers={"Authorization": "Bearer not.a.token"})

    assert response.status_code == 204  # a report is never refused for its token
    [line] = _reports(capsys)
    assert "user_id" not in line


def test_the_page_is_its_path_and_urls_lose_their_query_and_fragment(client, capsys):
    report = {
        **REPORT,
        "message": "Failed to fetch https://shurly.griddo.io/api/v1/urls?q=ana%40acme.com#top, then retried",
        "source": "https://shurly.griddo.io/_astro/link.Ab12cd.js?v=2#x:3:1403",
        "page": "/dashboard/link/?code=abc123&domain=go.griddo.io#visits",
    }
    assert client.post(ROUTE, json=report).status_code == 204

    [line] = _reports(capsys)
    assert line["page"] == "/dashboard/link/"
    assert line["message"] == "Failed to fetch https://shurly.griddo.io/api/v1/urls, then retried"
    assert line["source"] == "https://shurly.griddo.io/_astro/link.Ab12cd.js"


def test_one_line_per_report_whatever_the_message_holds(client, capsys):
    """The event log is JSON: a newline in a message is escaped, so it can't forge a line."""
    forged = '{"event": "http.request", "status": 200, "path": "/forged"}'
    report = {**REPORT, "message": f"boom\n{forged}\r\n"}
    assert client.post(ROUTE, json=report).status_code == 204

    lines = _lines(capsys)
    assert [line["event"] for line in lines].count("client.error") == 1
    assert not any(line.get("path") == "/forged" for line in lines)
    [report_line] = [line for line in lines if line["event"] == "client.error"]
    assert report_line["message"].startswith("boom\n{")


@pytest.mark.parametrize(
    "change",
    [
        {"kind": "anything"},
        {"message": "x" * 501},
        {"source": "x" * 301},
        {"page": "/" + "x" * 300},
        {"page": "https://elsewhere.example/"},
        {"message": ""},
    ],
)
def test_a_report_out_of_bounds_is_refused(client, change, capsys):
    assert client.post(ROUTE, json={**REPORT, **change}).status_code == 422
    assert _reports(capsys) == []


def test_reports_are_limited_per_address(monkeypatch, capsys):
    monkeypatch.setattr(settings, "rate_limit_client_errors_per_ip", 3)
    first, second = (
        TestClient(app, client=("203.0.113.7", 50000)),
        TestClient(app, client=("203.0.113.8", 50000)),
    )

    assert [first.post(ROUTE, json=REPORT).status_code for _ in range(4)] == [204, 204, 204, 429]
    assert second.post(ROUTE, json=REPORT).status_code == 204  # another address, its own count
    assert len(_reports(capsys)) == 4


def test_a_nul_in_a_report_is_refused_at_its_field(client, capsys):
    """The web app never sends one (error-report.ts); a hand-made one meets the NUL guard (server/utils/nul.py)."""
    response = client.post(ROUTE, json={**REPORT, "message": "boom\u0000"})

    assert response.status_code == 422
    assert response.json()["detail"][0]["loc"] == ["body", "message"]
    assert _reports(capsys) == []
