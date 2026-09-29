"""
Phase 8.4 — the review sheet: one row per Shlink link, with what a person needs to
decide `keep`, `archive` or `drop`, and `keep` filled in. Optionally the status of
each destination, fetched through the link previews' SSRF guard.
"""

import asyncio
import csv
import json
import socket
import time

import httpx
import pytest

from server.core.config import settings
from server.tools.shlink import __main__ as cli
from server.tools.shlink.review import COLUMNS, check_destinations, review_rows
from tests.test_opengraph_ssrf import PUBLIC_IP, FakeDNS, FakeWeb
from tests.test_phase84_shlink_export import NOW, short_url, visit


def snapshot(*links: dict) -> dict:
    return {
        "format": "shurly.shlink-snapshot/1",
        "shlink": {"url": "https://go.shlink.test"},
        "links": list(links),
    }


def row_of(rows: list[dict], code: str) -> dict:
    (row,) = [row for row in rows if row["code"] == code]
    return row


class TestRows:
    def test_one_row_per_link_to_keep_by_default(self):
        link = short_url(
            "abc",
            "https://example.com/offer",
            title="The offer",
            tags=["q4", "email"],
            visitsSummary={"total": 7, "nonBots": 5, "bots": 2},
        )

        (row,) = review_rows(snapshot({"short_url": link}), now=NOW)

        assert list(row) == COLUMNS
        expected = {
            "code": "abc",
            "domain": "go.shlink.test",
            "destination": "https://example.com/offer",
            "title": "The offer",
            "tags": "q4, email",
            "created": "2024-01-02T10:00:00+01:00",
            "visits": 7,
            "non_bot_visits": 5,
            "decision": "keep",
        }
        assert {column: row[column] for column in expected} == expected

    def test_the_domain_of_a_default_domain_link_is_its_host(self):
        rows = review_rows(
            snapshot(
                {"short_url": short_url("a")}, {"short_url": short_url("b", domain="s.shlink.test")}
            ),
            now=NOW,
        )

        assert [row["domain"] for row in rows] == ["go.shlink.test", "s.shlink.test"]

    def test_duplicates_point_at_the_oldest(self):
        same = "https://example.com/same"
        rows = review_rows(
            snapshot(
                {"short_url": short_url("new", same, dateCreated="2025-01-01T00:00:00+00:00")},
                {"short_url": short_url("old", same, dateCreated="2024-01-01T00:00:00+00:00")},
                {"short_url": short_url("elsewhere", same, domain="s.shlink.test")},
            ),
            now=NOW,
        )

        assert [row["duplicate_of"] for row in rows] == ["old", "", ""]

    def test_codes_that_differ_only_in_case_are_flagged(self):
        """They matter if go.griddo.io runs Shlink's `loose` mode (8.2)."""
        rows = review_rows(
            snapshot(
                {"short_url": short_url("AbC")},
                {"short_url": short_url("abc")},
                {"short_url": short_url("ABC", domain="s.shlink.test")},
            ),
            now=NOW,
        )

        assert [row["case_collision"] for row in rows] == ["abc", "AbC", ""]

    def test_expired_and_capped(self):
        rows = review_rows(
            snapshot(
                {
                    "short_url": short_url(
                        "past",
                        meta={
                            "validSince": None,
                            "validUntil": "2025-01-01T00:00:00Z",  # 3.10 can't parse Z itself
                            "maxVisits": None,
                        },
                    )
                },
                {
                    "short_url": short_url(
                        "future",
                        meta={
                            "validSince": None,
                            "validUntil": "2027-01-01T00:00:00+00:00",
                            "maxVisits": None,
                        },
                    )
                },
                {
                    "short_url": short_url(
                        "full", meta={"validSince": None, "validUntil": None, "maxVisits": 3}
                    )
                },
                {
                    "short_url": short_url(
                        "room", meta={"validSince": None, "validUntil": None, "maxVisits": 4}
                    )
                },
            ),
            now=NOW,
        )

        assert [(row["expired"], row["capped"]) for row in rows] == [
            ("yes", ""),
            ("", ""),
            ("", "yes"),
            ("", ""),
        ]

    def test_capped_in_shurly_counts_the_clicks_an_import_brings(self):
        """Shlink's cap counts every visit, Shurly's only clicks: a capped link can reopen."""
        cap = {"validSince": None, "validUntil": None, "maxVisits": 2}
        bot = {**visit("2025-03-01T10:00:00+00:00"), "potentialBot": True}
        pixel = {**visit("2025-03-02T10:00:00+00:00"), "redirectUrl": None}
        click = visit("2025-03-03T10:00:00+00:00")
        rows = review_rows(
            snapshot(
                {"short_url": short_url("reopens", meta=cap), "visits": [bot, pixel, click]},
                {"short_url": short_url("stays", meta=cap), "visits": [click, bot, click]},
                {"short_url": short_url("unexported", meta=cap)},  # no visits to import
            ),
            now=NOW,
        )

        assert [(row["capped"], row["capped_in_shurly"]) for row in rows] == [
            ("yes", ""),
            ("yes", "yes"),
            ("yes", ""),
        ]

    def test_the_last_visit_when_visits_were_exported(self):
        rows = review_rows(
            snapshot(
                {
                    "short_url": short_url("seen"),
                    "visits": [
                        visit("2025-03-01T10:00:00+00:00"),
                        visit("2025-05-02T08:00:00+02:00"),
                    ],
                },
                {"short_url": short_url("unexported")},
            ),
            now=NOW,
        )

        assert [row["last_visit"] for row in rows] == ["2025-05-02T08:00:00+02:00", ""]

    def test_rules_shurly_cannot_follow_are_flagged(self):
        rules = {
            "defaultLongUrl": "https://example.com/",
            "redirectRules": [
                {
                    "priority": 1,
                    "longUrl": "https://example.com/a",
                    "conditions": [
                        {"type": "device", "matchKey": None, "matchValue": "ios"},
                        {"type": "ip-address", "matchKey": None, "matchValue": "10.0.0.0/8"},
                    ],
                },
                {
                    "priority": 2,
                    "longUrl": "https://example.com/b",
                    "conditions": [
                        {"type": "geolocation-country-code", "matchKey": None, "matchValue": "ES"},
                    ],
                },
            ],
        }
        rows = review_rows(
            snapshot(
                {"short_url": short_url("ruled", hasRedirectRules=True), "redirect_rules": rules},
                {"short_url": short_url("plain")},
            ),
            now=NOW,
        )

        assert [(row["redirect_rules"], row["rules_to_check"]) for row in rows] == [
            (2, "geolocation-country-code, ip-address"),
            (0, ""),
        ]


class TestCommand:
    def test_writes_the_sheet_next_to_the_snapshot(self, tmp_path):
        path = tmp_path / "shlink-go.shlink.test-20260928T101500Z.snapshot.json"
        link = short_url("abc", title='=HYPERLINK("https://evil.test")')
        path.write_text(json.dumps(snapshot({"short_url": link})))

        assert cli.main(["review", str(path)]) == 0

        sheet = tmp_path / "shlink-go.shlink.test-20260928T101500Z.review.csv"
        with sheet.open(newline="") as f:
            (header, row) = list(csv.reader(f))
        assert header == COLUMNS
        assert dict(zip(header, row, strict=True))["title"] == '\'=HYPERLINK("https://evil.test")'

    def test_never_over_a_sheet_that_may_hold_decisions(self, tmp_path, capsys):
        path = tmp_path / "x.snapshot.json"
        path.write_text(json.dumps(snapshot({"short_url": short_url("abc")})))
        sheet = tmp_path / "x.review.csv"
        sheet.write_text("code,decision\nabc,drop\n")

        assert cli.main(["review", str(path)]) == 1

        assert sheet.read_text() == "code,decision\nabc,drop\n"
        assert "--out" in capsys.readouterr().err


# --- Destinations, through the link previews' SSRF guard -----------------------------


@pytest.fixture(autouse=True)
def guard_on(monkeypatch):
    monkeypatch.setattr(settings, "og_fetch_allow_private", False)


@pytest.fixture
def dns(monkeypatch) -> FakeDNS:
    fake = FakeDNS()
    monkeypatch.setattr(socket, "getaddrinfo", fake.getaddrinfo)
    return fake


@pytest.fixture
def web(monkeypatch) -> FakeWeb:
    fake = FakeWeb()
    real = httpx.AsyncClient

    class Routed(real):
        def __init__(self, **kwargs):
            super().__init__(transport=httpx.MockTransport(fake.handle), **kwargs)

    monkeypatch.setattr(httpx, "AsyncClient", Routed)
    return fake


def statuses(*urls: str, **options) -> dict[str, str]:
    return asyncio.run(check_destinations(urls, **options))


class TestDestinations:
    def test_the_status_of_each(self, dns, web):
        dns.records |= {"ok.test": [PUBLIC_IP], "gone.test": [PUBLIC_IP]}
        web.routes["ok.test/"] = lambda request: httpx.Response(200)
        web.routes["gone.test/"] = lambda request: httpx.Response(404)

        assert statuses("https://ok.test/", "https://gone.test/") == {
            "https://ok.test/": "200",
            "https://gone.test/": "404",
        }

    def test_head_first_then_get_if_head_is_refused(self, dns, web):
        """A HEAD doesn't download a PDF; some servers only answer GET."""
        dns.records["ok.test"] = [PUBLIC_IP]
        web.routes["ok.test/"] = lambda r: httpx.Response(405 if r.method == "HEAD" else 200)

        assert statuses("https://ok.test/") == {"https://ok.test/": "200"}
        assert [r.method for r in web.requests] == ["HEAD", "GET"]

    def test_redirects_are_followed_and_each_hop_checked(self, dns, web):
        dns.records |= {
            "old.test": [PUBLIC_IP],
            "new.test": [PUBLIC_IP],
            "inside.test": ["10.0.0.5"],
        }
        web.routes["old.test/"] = lambda r: httpx.Response(
            301, headers={"Location": "https://new.test/"}
        )
        web.routes["new.test/"] = lambda r: httpx.Response(200)
        web.routes["old.test/in"] = lambda r: httpx.Response(
            302, headers={"Location": "https://inside.test/"}
        )

        result = statuses("https://old.test/", "https://old.test/in")

        assert result["https://old.test/"] == "200"
        assert result["https://old.test/in"].startswith("refused")

    @pytest.mark.parametrize(
        "url",
        ["https://inside.test/", "http://127.0.0.1/", "ftp://files.test/a", "mailto:a@griddo.io"],
    )
    def test_refused_without_a_request(self, dns, web, url):
        dns.records["inside.test"] = ["10.0.0.5"]

        assert statuses(url)[url].startswith("refused")
        assert web.requests == []

    def test_a_timeout_and_an_unknown_host(self, dns, web):
        dns.records["slow.test"] = [PUBLIC_IP]

        def slow(request):
            raise httpx.ReadTimeout("slow", request=request)

        web.routes["slow.test/"] = slow

        result = statuses("https://slow.test/", "https://nowhere.test/")

        assert result == {
            "https://slow.test/": "timeout",
            "https://nowhere.test/": "error: gaierror",
        }

    def test_a_slow_dns_lookup_is_a_timeout(self, dns, web, monkeypatch):
        """The lookup runs under asyncio.wait_for, which raises asyncio.TimeoutError: not the
        builtin TimeoutError before Python 3.11."""

        def slow_lookup(host, port, *args, **kwargs):
            time.sleep(0.3)
            return dns.getaddrinfo(host, port, *args, **kwargs)

        monkeypatch.setattr(socket, "getaddrinfo", slow_lookup)
        dns.records["slow.test"] = [PUBLIC_IP]

        assert statuses("https://slow.test/", timeout=0.05) == {"https://slow.test/": "timeout"}
        assert web.requests == []

    def test_each_destination_once(self, dns, web):
        dns.records["ok.test"] = [PUBLIC_IP]
        web.routes["ok.test/"] = lambda request: httpx.Response(200)

        statuses("https://ok.test/", "https://ok.test/")

        assert len(web.requests) == 1

    def test_at_most_so_many_at_once(self, dns, monkeypatch):
        in_flight = peak = 0

        async def slow(request):
            nonlocal in_flight, peak
            in_flight += 1
            peak = max(peak, in_flight)
            await asyncio.sleep(0.02)
            in_flight -= 1
            return httpx.Response(200)

        real = httpx.AsyncClient

        class Routed(real):
            def __init__(self, **kwargs):
                super().__init__(transport=httpx.MockTransport(slow), **kwargs)

        monkeypatch.setattr(httpx, "AsyncClient", Routed)
        dns.records |= {f"s{i}.test": [PUBLIC_IP] for i in range(10)}

        statuses(*(f"https://s{i}.test/" for i in range(10)), concurrency=3)

        assert peak == 3
