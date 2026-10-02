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


# Shlink's answer when it fails: production's, on the links whose visits it can't serialize.
INTERNAL_ERROR = {
    "title": "Internal Server Error",
    "type": "https://shlink.io/api/error/internal-server-error",
    "status": 500,
    "detail": "An unknown error occurred.",
}


def _moment(value: str) -> datetime:
    """An ISO date as Shlink compares it, to the second; 3.10's fromisoformat reads no "Z"."""
    return datetime.fromisoformat(value.replace("Z", "+00:00")).replace(microsecond=0)


class FakeShlink:
    """
    Shlink's REST API, from its spec: paginated lists, `X-Api-Key` required. A link's
    visits take `startDate` and `endDate`, both included, to the second, and a page past
    the last one fails, as Shlink's paginator does.

    To fail as production does: `broken` names, per link, the visits it can't serialize
    (an answer holding one is a 500); `flaky`, how many times a link's visits answer 500
    first; `listing_fails`, that the list of short URLs itself does.

    The list of short URLs takes `orderBy` (`<field>-ASC|DESC`, as Shlink's spec says).
    Without it, the links come in insertion order, unless `unstable`: then each page of the
    list sees them in another order, so pages overlap; `ignores_order` keeps them unstable
    even with `orderBy`. `miscount` is added to the list's `totalItems`. `searchTerm`
    narrows the list to the links whose code, destination, title or a tag holds it, as
    Shlink's does. `links` may hold one link twice: production's Shlink does (R17).
    """

    def __init__(
        self,
        links,
        rules=None,
        visits=None,
        version="4.2.1",
        *,
        broken=None,
        flaky=None,
        listing_fails=False,
        unstable=False,
        ignores_order=False,
        miscount=0,
    ):
        self.links = links
        self.rules = rules or {}
        self.visits = visits or {}
        self.version = version
        self.broken = broken or {}
        self.flaky = dict(flaky or {})
        self.listing_fails = listing_fails
        self.unstable = unstable
        self.ignores_order = ignores_order
        self.miscount = miscount
        self.listings = 0
        self.requests: list[httpx.Request] = []

    def handle(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        if request.headers.get("x-api-key") != KEY:
            return httpx.Response(401, json={"title": "Invalid authorization", "status": 401})
        path = request.url.path
        if path == "/rest/health":
            return httpx.Response(200, json={"status": "pass", "version": self.version})
        if path == "/rest/v3/short-urls":
            if self.listing_fails:
                return self._error()
            links = self._ordered(
                request.url.params.get("orderBy"), request.url.params.get("searchTerm")
            )
            if links is None:
                return httpx.Response(400, json={"title": "Invalid data", "status": 400})
            self.listings += 1
            return self._page(request, "shortUrls", list(enumerate(links)), miscount=self.miscount)
        # The raw path: `url.path` is decoded, and a code may hold an escaped slash.
        raw_path = request.url.raw_path.decode("ascii").split("?")[0]
        found = re.fullmatch(r"/rest/v3/short-urls/([^/]+)/(redirect-rules|visits)", raw_path)
        if not found:
            return httpx.Response(404)
        key = (request.url.params.get("domain"), unquote(found[1]))
        if found[2] == "redirect-rules":
            return httpx.Response(200, json=self.rules[key])
        if self.flaky.get(key):
            self.flaky[key] -= 1
            return self._error()
        visits = list(enumerate(self.visits.get(key, [])))
        start, end = request.url.params.get("startDate"), request.url.params.get("endDate")
        if start:
            visits = [(i, v) for i, v in visits if _moment(v["date"]) >= _moment(start)]
        if end:
            visits = [(i, v) for i, v in visits if _moment(v["date"]) <= _moment(end)]
        return self._page(request, "visits", visits, self.broken.get(key, set()))

    ORDER_FIELDS = {
        "shortCode": lambda link: link["shortCode"],
        "dateCreated": lambda link: link["dateCreated"],
        "longUrl": lambda link: link["longUrl"],
        "title": lambda link: link.get("title") or "",
        "visits": lambda link: (link.get("visitsSummary") or {}).get("total", 0),
    }

    def _ordered(self, order: str | None, term: str | None = None) -> list | None:
        """The links holding `term`, in `order`; None for an order Shlink refuses."""
        links = self.links
        if term:
            term = term.lower()
            links = [
                link
                for link in links
                if any(
                    term in (text or "").lower()
                    for text in (link["shortCode"], link["longUrl"], link.get("title"))
                    + tuple(link.get("tags") or [])
                )
            ]
        if order is not None:
            field, _, direction = order.rpartition("-")
            if field not in self.ORDER_FIELDS or direction not in ("ASC", "DESC"):
                return None
        if order is None or self.ignores_order:
            if not self.unstable or not links:
                return list(links)
            turn = self.listings % len(links)  # another order for every page asked
            return links[turn:] + links[:turn]
        return sorted(links, key=self.ORDER_FIELDS[field], reverse=direction == "DESC")

    @staticmethod
    def _error() -> httpx.Response:
        return httpx.Response(
            500, json=INTERNAL_ERROR, headers={"content-type": "application/problem+json"}
        )

    @classmethod
    def _page(
        cls,
        request: httpx.Request,
        name: str,
        items: list,
        broken: set = frozenset(),
        miscount: int = 0,
    ) -> httpx.Response:
        """`items` as (index, item): an answer holding a `broken` index fails."""
        page = int(request.url.params.get("page", 1))
        per_page = int(request.url.params.get("itemsPerPage", 10))
        pages = max(1, -(-len(items) // per_page))
        if page > pages:
            return cls._error()  # Pagerfanta's OutOfRangeCurrentPageException
        chunk = items[(page - 1) * per_page : page * per_page]
        if any(index in broken for index, _ in chunk):
            return cls._error()
        pagination = {
            "currentPage": page,
            "pagesCount": pages,
            "itemsPerPage": per_page,
            "itemsInCurrentPage": len(chunk),
            "totalItems": len(items) + miscount,
        }
        data = [item for _, item in chunk]
        return httpx.Response(200, json={name: {"data": data, "pagination": pagination}})


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

        assert {
            entry["short_url"]["shortCode"]: entry.get("redirect_rules")
            for entry in snapshot["links"]
        } == {"plain": None, "ruled": rules, "other": rules}

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


def _export(fake: FakeShlink, **options) -> tuple[dict, list[float]]:
    """With visits, and the waits between retries recorded instead of slept."""
    waits: list[float] = []
    snapshot = export_snapshot(_client(fake), visits=True, now=NOW, sleep=waits.append, **options)
    return snapshot, waits


def _by_date(visits: list[dict]) -> list[str]:
    return sorted(v["date"] for v in visits)


def _visit_requests(fake: FakeShlink, code: str) -> list[httpx.Request]:
    return [r for r in fake.requests if r.url.path == f"/rest/v3/short-urls/{code}/visits"]


# A year of visits, one of them Shlink can't serialize, another in its very second.
YEAR = [visit(f"2025-{m:02}-{d:02}T10:00:00+00:00") for m in range(1, 13) for d in (3, 17)]
BAD_SECOND = "2025-03-04T10:00:07+00:00"
SAME_SECOND = [
    {**visit(BAD_SECOND), "userAgent": "broken"},
    {**visit("2025-03-04T11:00:07+01:00"), "userAgent": "fine"},  # the same second
]
GAP = {"start": BAD_SECOND, "end": BAD_SECOND}


class TestShlinkFailsOnALinksVisits:
    """Production's Shlink answers 500 to a few links' visits, whatever the parameters:
    most likely one visit it can't serialize. The export carries on, and recovers what it
    can by date range."""

    def test_it_doesnt_stop_the_export(self):
        links = [short_url("before"), short_url("23q4griddo"), short_url("after")]
        fake = FakeShlink(
            links,
            visits={
                (None, code): [visit("2025-01-01T00:00:00+00:00")] for code in ("before", "after")
            }
            | {(None, "23q4griddo"): SAME_SECOND},
            broken={(None, "23q4griddo"): {0}},
        )

        snapshot, _ = _export(fake)

        # In code order, as the list is asked for (R17).
        assert [entry["short_url"] for entry in snapshot["links"]] == [links[1], links[2], links[0]]
        failing, after, before = snapshot["links"]
        assert before["visits"] and after["visits"]
        assert "visits_error" not in before and "visits_gaps" not in after
        assert failing["visits_error"] == {"status": 500, "detail": "An unknown error occurred."}
        assert snapshot["visits_failed"] == ["23q4griddo"]

    def test_a_5xx_is_asked_again_before_it_counts(self):
        visits = [visit("2025-01-01T00:00:00+00:00")]
        fake = FakeShlink(
            [short_url("abc")], visits={(None, "abc"): visits}, flaky={(None, "abc"): 2}
        )

        snapshot, waits = _export(fake)

        (entry,) = snapshot["links"]
        assert entry["visits"] == visits and "visits_error" not in entry
        assert snapshot["visits_failed"] == []
        assert waits == [0.5, 1.0]  # a short backoff, longer each time
        assert len(_visit_requests(fake, "abc")) == 3

    def test_it_counts_after_the_retries(self):
        """Three asks of the whole list, then the date ranges begin."""
        fake = FakeShlink(
            [short_url("abc")], visits={(None, "abc"): YEAR}, flaky={(None, "abc"): 3}
        )

        snapshot, waits = _export(fake)

        first = _visit_requests(fake, "abc")[:4]
        assert ["startDate" in r.url.params for r in first] == [False, False, False, True]
        assert waits == [0.5, 1.0]
        # The ranges then answer, so nothing was lost: the 500s were passing.
        (entry,) = snapshot["links"]
        assert entry["visits_error"]["status"] == 500
        assert (_by_date(entry["visits"]), entry["visits_gaps"]) == (_by_date(YEAR), [])

    def test_date_ranges_recover_all_but_the_bad_second(self):
        visits = YEAR[:4] + SAME_SECOND + YEAR[4:]
        broken = visits.index(SAME_SECOND[0])
        fake = FakeShlink(
            [short_url("abc", visitsSummary={"total": len(visits)})],
            visits={(None, "abc"): visits},
            broken={(None, "abc"): {broken}},
        )

        snapshot, _ = _export(fake)

        (entry,) = snapshot["links"]
        # Every visit but the one Shlink can't serialize: its second's other one too.
        assert _by_date(entry["visits"]) == _by_date(visits[:broken] + visits[broken + 1 :])
        assert {"userAgent": "fine"}.items() <= next(
            v for v in entry["visits"] if v["date"] == SAME_SECOND[1]["date"]
        ).items()
        assert entry["visits_gaps"] == [GAP]

    def test_the_dates_shlink_is_asked_for(self):
        """ISO 8601 with the offset, which Shlink parses, the "+" escaped in the query."""
        fake = FakeShlink(
            [short_url("abc")], visits={(None, "abc"): SAME_SECOND}, broken={(None, "abc"): {0}}
        )

        _export(fake, clock=lambda: NOW)

        (first, *_) = [r for r in _visit_requests(fake, "abc") if "startDate" in r.url.params]
        assert (first.url.params["startDate"], first.url.params["endDate"]) == (
            "1970-01-01T00:00:00+00:00",
            "2026-09-28T10:15:00+00:00",
        )
        assert b"%2B00" in first.url.query and b"+" not in first.url.query
        # The narrowest range, one second, is then read one visit per page.
        singles = [
            r.url.params
            for r in _visit_requests(fake, "abc")
            if r.url.params.get("itemsPerPage") == "1"
        ]
        assert {(p["startDate"], p["endDate"]) for p in singles} == {(BAD_SECOND, BAD_SECOND)}
        assert [p["page"] for p in singles] == ["1"] * 3 + ["2"]  # page 1 retried, then 2

    def test_two_bad_visits_two_gaps_oldest_first(self):
        visits = [visit("2025-06-01T08:00:00+00:00"), *YEAR, visit("2024-02-29T23:59:59+00:00")]
        fake = FakeShlink(
            [short_url("abc")], visits={(None, "abc"): visits}, broken={(None, "abc"): {0, 25}}
        )

        snapshot, _ = _export(fake)

        (entry,) = snapshot["links"]
        assert _by_date(entry["visits"]) == _by_date(YEAR)
        assert entry["visits_gaps"] == [
            {"start": "2024-02-29T23:59:59+00:00", "end": "2024-02-29T23:59:59+00:00"},
            {"start": "2025-06-01T08:00:00+00:00", "end": "2025-06-01T08:00:00+00:00"},
        ]

    def test_newest_first_as_shlink_lists_them(self):
        newest_first = sorted(YEAR, key=lambda v: v["date"], reverse=True)
        fake = FakeShlink(
            [short_url("abc")],
            visits={(None, "abc"): [visit(BAD_SECOND), *newest_first]},
            broken={(None, "abc"): {0}},
        )

        snapshot, _ = _export(fake)

        assert snapshot["links"][0]["visits"] == newest_first

    def test_past_its_budget_whats_left_is_a_gap(self):
        """A link Shlink can't answer for at all mustn't take a request per second."""
        fake = FakeShlink(
            [short_url("abc")], visits={(None, "abc"): YEAR}, flaky={(None, "abc"): 10**6}
        )

        snapshot, _ = _export(fake, recovery_requests=10, clock=lambda: NOW)

        (entry,) = snapshot["links"]
        assert entry["visits"] == []
        gaps = entry["visits_gaps"]
        assert len(gaps) == 11  # the ten failed ranges' halves, newest first, until the budget
        assert gaps[0]["start"] == "1970-01-01T00:00:00+00:00"
        assert gaps[-1]["end"] == "2026-09-28T10:15:00+00:00"
        assert len(_visit_requests(fake, "abc")) == 3 + 10 * 3

    def test_a_count_no_date_reaches_is_a_gap_with_no_ends(self):
        """The whole list failed, every range answered, and Shlink counts more visits."""
        fake = FakeShlink(
            [short_url("abc", visitsSummary={"total": len(YEAR) + 1})],
            visits={(None, "abc"): YEAR},
            flaky={(None, "abc"): 3},
        )

        snapshot, _ = _export(fake)

        (entry,) = snapshot["links"]
        assert entry["visits_gaps"] == [{"start": None, "end": None}]
        assert _by_date(entry["visits"]) == _by_date(YEAR)

    def test_the_list_of_short_urls_failing_still_stops_it(self):
        fake = FakeShlink([short_url("abc")], listing_fails=True)

        with pytest.raises(httpx.HTTPStatusError):
            _export(fake)

        assert len(fake.requests) == 1 + 3  # health, then the list asked three times

    def test_a_4xx_on_visits_still_stops_it(self):
        """Not Shlink failing on a link: a refused key, a link gone."""
        fake = FakeShlink([short_url("gone")])

        def handle(request: httpx.Request) -> httpx.Response:
            if request.url.path.endswith("/visits"):
                return httpx.Response(404, json={"status": 404, "title": "Short URL not found"})
            return fake.handle(request)

        client = shlink_client(URL, KEY, transport=httpx.MockTransport(handle))
        with pytest.raises(httpx.HTTPStatusError):
            export_snapshot(client, visits=True, now=NOW, sleep=lambda _: None)

    def test_without_visits_no_visits_fields(self):
        snapshot = export_snapshot(_client(FakeShlink([short_url("abc")])), now=NOW)

        assert "visits_failed" not in snapshot


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

    def test_a_link_whose_visits_fail_is_summed_up(self, fake, monkeypatch, tmp_path, capsys):
        fake.links = [short_url("abc"), short_url("quiet"), short_url("23q4griddo")]
        fake.visits = {(None, "abc"): YEAR[:2], (None, "23q4griddo"): [visit(BAD_SECOND), *YEAR]}
        fake.broken = {(None, "23q4griddo"): {0}}
        monkeypatch.setenv("SHLINK_API_KEY", KEY)
        monkeypatch.setattr("time.sleep", lambda seconds: None)

        assert cli.main(["export", "--visits", "--out-dir", str(tmp_path)]) == 0

        (path,) = tmp_path.glob("*.snapshot.json")
        assert json.loads(path.read_text())["visits_failed"] == ["23q4griddo"]
        output = capsys.readouterr()
        assert output.out.splitlines()[1:] == [
            "3 links exported.",
            "Visits exported whole for 2 links, 1 of them with visits (2 visits).",
            "Visits failed for 1 link: 23q4griddo",
            "  23q4griddo: Shlink answered 500 (An unknown error occurred.). Recovered 24 visits "
            f"by date, lost 1 range: {BAD_SECOND}/{BAD_SECOND}",
        ]
        assert "23q4griddo: Shlink answered 500 to its visits" in output.err  # as it goes

    def test_the_list_failing_stops_it(self, fake, monkeypatch, tmp_path, capsys):
        fake.listing_fails = True
        monkeypatch.setenv("SHLINK_API_KEY", KEY)
        monkeypatch.setattr("time.sleep", lambda seconds: None)

        assert cli.main(["export", "--visits", "--out-dir", str(tmp_path)]) == 1

        assert "500 to /rest/v3/short-urls." in capsys.readouterr().err
        assert not list(tmp_path.iterdir())

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
