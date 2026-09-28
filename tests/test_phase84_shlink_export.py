"""
Phase 8.4 — exporting Shlink: every short URL, its redirect rules and (optionally)
its visits, from Shlink's REST API into one raw JSON snapshot. Read-only: the
snapshot is what the review and the import work from, and Shlink stays untouched.

A fake Shlink stands in for the real one, answering as Shlink's API spec says.
"""

import json
import re
import stat
from datetime import datetime, timezone
from urllib.parse import unquote

import httpx
import pytest

from server.tools.shlink import __main__ as cli
from server.tools.shlink.export import export_snapshot, shlink_client, write_snapshot

KEY = "shlink-key-0123456789abcdef"
URL = "https://go.shlink.test"
NOW = datetime(2026, 9, 28, 10, 15, 0, tzinfo=timezone.utc)


def short_url(code: str, long_url: str = "https://example.com/", **fields) -> dict:
    """A short URL as Shlink's API returns it (ShortUrl.json)."""
    domain = fields.pop("domain", None)
    return {
        "shortCode": code,
        "shortUrl": f"https://{domain or 'go.shlink.test'}/{code}",
        "longUrl": long_url,
        "dateCreated": "2024-01-02T10:00:00+01:00",
        "visitsSummary": {"total": 3, "nonBots": 2, "bots": 1},
        "tags": [],
        "meta": {"validSince": None, "validUntil": None, "maxVisits": None},
        "domain": domain,
        "title": None,
        "crawlable": False,
        "forwardQuery": True,
        "hasRedirectRules": False,
        **fields,
    }


def visit(date: str) -> dict:
    return {
        "referer": "https://t.co",
        "date": date,
        "userAgent": "Mozilla/5.0",
        "visitLocation": {"countryCode": "ES", "countryName": "Spain"},
        "potentialBot": False,
        "visitedUrl": "https://go.shlink.test/abc",
        "redirectUrl": "https://example.com/",
    }


class FakeShlink:
    """Shlink's REST API, from its spec: paginated lists, `X-Api-Key` required."""

    def __init__(self, links, rules=None, visits=None, version="4.2.1"):
        self.links = links
        self.rules = rules or {}
        self.visits = visits or {}
        self.version = version
        self.requests: list[httpx.Request] = []

    def handle(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        if request.headers.get("x-api-key") != KEY:
            return httpx.Response(401, json={"title": "Invalid authorization", "status": 401})
        path = request.url.path
        if path == "/rest/health":
            return httpx.Response(200, json={"status": "pass", "version": self.version})
        if path == "/rest/v3/short-urls":
            return self._page(request, "shortUrls", self.links)
        # The raw path: `url.path` is decoded, and a code may hold an escaped slash.
        raw_path = request.url.raw_path.decode("ascii").split("?")[0]
        found = re.fullmatch(r"/rest/v3/short-urls/([^/]+)/(redirect-rules|visits)", raw_path)
        if not found:
            return httpx.Response(404)
        key = (request.url.params.get("domain"), unquote(found[1]))
        if found[2] == "redirect-rules":
            return httpx.Response(200, json=self.rules[key])
        return self._page(request, "visits", self.visits.get(key, []))

    @staticmethod
    def _page(request: httpx.Request, name: str, items: list) -> httpx.Response:
        page = int(request.url.params.get("page", 1))
        per_page = int(request.url.params.get("itemsPerPage", 10))
        chunk = items[(page - 1) * per_page : page * per_page]
        pagination = {
            "currentPage": page,
            "pagesCount": max(1, -(-len(items) // per_page)),
            "itemsPerPage": per_page,
            "itemsInCurrentPage": len(chunk),
            "totalItems": len(items),
        }
        return httpx.Response(200, json={name: {"data": chunk, "pagination": pagination}})


def _client(fake: FakeShlink, key: str = KEY) -> httpx.Client:
    return shlink_client(URL, key, transport=httpx.MockTransport(fake.handle))


class TestSnapshot:
    def test_every_page_of_short_urls_untouched(self):
        links = [short_url(f"c{i}") for i in range(5)]

        snapshot = export_snapshot(_client(FakeShlink(links)), page_size=2, now=NOW)

        assert [entry["short_url"] for entry in snapshot["links"]] == links

    def test_what_and_when(self):
        snapshot = export_snapshot(_client(FakeShlink([])), now=NOW)

        assert snapshot["format"] == "shurly.shlink-snapshot/1"
        assert snapshot["exported_at"] == "2026-09-28T10:15:00+00:00"
        assert snapshot["shlink"] == {"url": URL, "version": "4.2.1"}

    def test_redirect_rules_of_the_links_that_have_them(self):
        rules = {"defaultLongUrl": "https://example.com/", "redirectRules": [{"priority": 1}]}
        links = [
            short_url("plain"),
            short_url("ruled", hasRedirectRules=True),
            short_url("other", domain="s.shlink.test", hasRedirectRules=True),
        ]
        fake = FakeShlink(links, rules={(None, "ruled"): rules, ("s.shlink.test", "other"): rules})

        snapshot = export_snapshot(_client(fake), now=NOW)

        assert [entry.get("redirect_rules") for entry in snapshot["links"]] == [None, rules, rules]

    def test_visits_only_when_asked_every_page(self):
        visits = [visit(f"2025-0{m}-01T00:00:00+00:00") for m in range(1, 6)]
        links = [short_url("abc"), short_url("xyz", domain="s.shlink.test")]
        fake = FakeShlink(
            links, visits={(None, "abc"): visits, ("s.shlink.test", "xyz"): visits[:1]}
        )

        without = export_snapshot(_client(fake), now=NOW)
        with_visits = export_snapshot(_client(fake), visits=True, visits_page_size=2, now=NOW)

        assert "visits" not in without["links"][0]
        assert [entry["visits"] for entry in with_visits["links"]] == [visits, visits[:1]]

    def test_a_code_is_escaped_in_the_path(self):
        fake = FakeShlink([short_url("a b/c", hasRedirectRules=True)], rules={(None, "a b/c"): {}})

        export_snapshot(_client(fake), now=NOW)

        assert fake.requests[-1].url.raw_path.startswith(b"/rest/v3/short-urls/a%20b%2Fc/")

    def test_every_request_carries_the_key(self):
        fake = FakeShlink([short_url("abc", hasRedirectRules=True)], rules={(None, "abc"): {}})

        export_snapshot(_client(fake), visits=True, now=NOW)

        assert fake.requests and all(r.headers["x-api-key"] == KEY for r in fake.requests)


class TestFile:
    def test_named_with_the_host_and_the_time(self, tmp_path):
        path = write_snapshot({"shlink": {"url": URL}}, tmp_path, now=NOW)

        assert path.name == "shlink-go.shlink.test-20260928T101500Z.snapshot.json"
        assert json.loads(path.read_text()) == {"shlink": {"url": URL}}

    def test_only_its_owner_can_read_it(self, tmp_path):
        """It holds every link, and with --visits people's visits."""
        path = write_snapshot({"shlink": {"url": URL}}, tmp_path, now=NOW)

        assert stat.S_IMODE(path.stat().st_mode) == 0o600

    def test_never_overwrites_one(self, tmp_path):
        write_snapshot({"shlink": {"url": URL}}, tmp_path, now=NOW)

        with pytest.raises(FileExistsError):
            write_snapshot({"shlink": {"url": URL}}, tmp_path, now=NOW)


class TestCommand:
    @pytest.fixture
    def fake(self, monkeypatch) -> FakeShlink:
        fake = FakeShlink([short_url("abc", hasRedirectRules=True)], rules={(None, "abc"): {}})
        real = httpx.Client

        class Routed(real):
            def __init__(self, **kwargs):
                super().__init__(transport=httpx.MockTransport(fake.handle), **kwargs)

        monkeypatch.setattr(httpx, "Client", Routed)
        monkeypatch.setenv("SHLINK_URL", URL)
        return fake

    def test_writes_the_snapshot_and_never_prints_the_key(
        self, fake, monkeypatch, tmp_path, capsys
    ):
        monkeypatch.setenv("SHLINK_API_KEY", KEY)

        assert cli.main(["export", "--visits", "--out-dir", str(tmp_path)]) == 0

        (path,) = tmp_path.glob("*.snapshot.json")
        output = capsys.readouterr()
        assert str(path) in output.out
        assert KEY not in path.read_text() + output.out + output.err

    def test_a_refused_key_says_so_without_printing_it(self, fake, monkeypatch, tmp_path, capsys):
        monkeypatch.setenv("SHLINK_API_KEY", "wrong-" + KEY)

        assert cli.main(["export", "--out-dir", str(tmp_path)]) == 1

        output = capsys.readouterr()
        assert "401" in output.err and "SHLINK_API_KEY" in output.err
        assert KEY not in output.out + output.err
        assert not list(tmp_path.iterdir())

    @pytest.mark.parametrize("missing", ["SHLINK_URL", "SHLINK_API_KEY"])
    def test_needs_the_address_and_the_key(self, fake, monkeypatch, tmp_path, capsys, missing):
        monkeypatch.setenv("SHLINK_API_KEY", KEY)
        monkeypatch.delenv(missing)

        assert cli.main(["export", "--out-dir", str(tmp_path)]) == 2
        assert missing in capsys.readouterr().err
