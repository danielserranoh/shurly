"""
Phase 8.4 — an export that's whole, or none (R17). Production's Shlink listed 344 links with
343 distinct codes: its default order isn't stable across pages, so one link came twice and
another, very likely, not at all. The import then failed on the database's unique code.

So the list of short URLs is asked in code order, the export checks that its pages bring as
many links as Shlink counts, each once, and a link's visits are asked up to the moment the
export started, so new ones can't shift their pages. Anything that doesn't add up stops the
export before a snapshot is written. The review and the import refuse a snapshot that lists
a link twice (tests/test_phase84_shlink_review.py, tests/test_phase84_shlink_import.py).
"""

import httpx
import pytest

from server.tools.shlink import __main__ as cli
from server.tools.shlink.export import SnapshotError, export_snapshot, shlink_client
from tests.test_phase84_shlink_export import KEY, NOW, URL, YEAR, FakeShlink, short_url, visit

# go.griddo.io's export: the link that came twice.
TWICE = "co-upb-luis-ochoa"


def _links(count: int = 5) -> list[dict]:
    return [short_url(f"c{i}") for i in range(count)]


def _client(handle) -> httpx.Client:
    return shlink_client(URL, KEY, transport=httpx.MockTransport(handle))


def _export(fake_or_handle, **options) -> dict:
    handle = getattr(fake_or_handle, "handle", fake_or_handle)
    return export_snapshot(_client(handle), now=NOW, sleep=lambda _: None, **options)


def _codes(snapshot: dict) -> list[str]:
    return [entry["short_url"]["shortCode"] for entry in snapshot["links"]]


class TestTheListOfShortUrls:
    def test_the_fake_overlaps_without_an_order(self):
        """As production did: each page in another order, so one link twice, one never."""
        fake = FakeShlink(_links(), unstable=True)
        client = _client(fake.handle)

        codes = [
            link["shortCode"]
            for page in (1, 2, 3)
            for link in client.get(
                "/rest/v3/short-urls", params={"page": page, "itemsPerPage": 2}
            ).json()["shortUrls"]["data"]
        ]

        assert len(codes) == 5 and len(set(codes)) == 4

    def test_it_is_asked_in_code_order(self):
        fake = FakeShlink(_links(), unstable=True)

        _export(fake, page_size=2)

        listing = [r for r in fake.requests if r.url.path == "/rest/v3/short-urls"]
        assert len(listing) == 3
        assert {r.url.params["orderBy"] for r in listing} == {"shortCode-ASC"}

    def test_so_its_pages_bring_every_link_once(self):
        links = _links(7)
        fake = FakeShlink(list(reversed(links)), unstable=True)

        snapshot = _export(fake, page_size=2)

        assert _codes(snapshot) == [link["shortCode"] for link in links]

    def test_a_link_listed_twice_stops_it(self):
        """Even in order: two links can share a code on different domains, and tie."""
        link = short_url(TWICE)
        fake = FakeShlink([short_url("a"), link, link])

        with pytest.raises(SnapshotError, match=f"go.shlink.test/{TWICE}"):
            _export(fake, page_size=2)

    def test_the_same_code_on_two_domains_is_two_links(self):
        fake = FakeShlink([short_url(TWICE), short_url(TWICE, domain="s.shlink.test")])

        snapshot = _export(fake)

        assert _codes(snapshot) == [TWICE, TWICE]

    def test_fewer_links_than_shlink_counts_stops_it(self):
        fake = FakeShlink(_links(), miscount=1)

        with pytest.raises(SnapshotError, match="counts 6.*brought 5"):
            _export(fake, page_size=2)

    def test_a_count_that_changes_on_the_way_stops_it(self):
        """A link made, or deleted, mid-export: the pages no longer add up."""
        fake = FakeShlink(_links())

        def handle(request: httpx.Request) -> httpx.Response:
            if request.url.path == "/rest/v3/short-urls" and fake.listings == 1:
                fake.links = [*fake.links, short_url("c9")]
            return fake.handle(request)

        with pytest.raises(SnapshotError, match="Shlink counts"):
            _export(handle, page_size=2)

    def test_it_stops_before_asking_for_anyones_visits(self):
        fake = FakeShlink([short_url(TWICE), short_url(TWICE)])

        with pytest.raises(SnapshotError):
            _export(fake, visits=True)

        assert not [r for r in fake.requests if r.url.path.endswith("/visits")]


class TestALinksVisits:
    def test_asked_up_to_the_exports_start(self):
        fake = FakeShlink([short_url("abc")], visits={(None, "abc"): YEAR})

        _export(fake, visits=True, visits_page_size=5, clock=lambda: NOW)

        visits = [r for r in fake.requests if r.url.path.endswith("/visits")]
        assert len(visits) == 5
        assert {r.url.params["endDate"] for r in visits} == {"2026-09-28T10:15:00+00:00"}
        assert not any("startDate" in r.url.params for r in visits)

    def test_a_visit_during_the_export_doesnt_shift_its_pages(self):
        """Shlink lists the newest first: a new visit would push the page's last one onto
        the next page, which would bring it again."""
        newest_first = sorted(YEAR, key=lambda v: v["date"], reverse=True)
        fake = FakeShlink([short_url("abc")], visits={(None, "abc"): list(newest_first)})

        def handle(request: httpx.Request) -> httpx.Response:
            response = fake.handle(request)
            if request.url.path.endswith("/visits"):
                fake.visits[(None, "abc")].insert(0, visit("2026-09-28T10:15:01+00:00"))
            return response

        snapshot = _export(handle, visits=True, visits_page_size=5, clock=lambda: NOW)

        assert snapshot["links"][0]["visits"] == newest_first

    def test_fewer_visits_than_shlink_counts_stops_it(self):
        fake = FakeShlink([short_url("abc")], visits={(None, "abc"): YEAR})

        def handle(request: httpx.Request) -> httpx.Response:
            response = fake.handle(request)
            if request.url.path.endswith("/visits"):
                body = response.json()
                body["visits"]["pagination"]["totalItems"] += 1
                return httpx.Response(200, json=body)
            return response

        with pytest.raises(SnapshotError, match="visits.*counts 25.*brought 24"):
            _export(handle, visits=True, visits_page_size=10)

    def test_a_link_shlink_fails_on_is_still_recovered(self):
        """The check counts the pages that answer: a 5xx is still the recovery's."""
        fake = FakeShlink(
            [short_url("abc", visitsSummary={"total": len(YEAR) + 1})],
            visits={(None, "abc"): [visit("2025-03-04T10:00:07+00:00"), *YEAR]},
            broken={(None, "abc"): {0}},
        )

        snapshot = _export(fake, visits=True)

        (entry,) = snapshot["links"]
        assert entry["visits_error"]["status"] == 500
        assert len(entry["visits"]) == len(YEAR)
        assert snapshot["visits_failed"] == ["abc"]


class TestCommand:
    @pytest.fixture
    def fake(self, monkeypatch) -> FakeShlink:
        fake = FakeShlink([])
        real = httpx.Client

        class Routed(real):
            def __init__(self, **kwargs):
                super().__init__(transport=httpx.MockTransport(fake.handle), **kwargs)

        monkeypatch.setattr(httpx, "Client", Routed)
        monkeypatch.setenv("SHLINK_URL", URL)
        monkeypatch.setenv("SHLINK_API_KEY", KEY)
        return fake

    def test_a_repeated_link_writes_no_snapshot(self, fake, tmp_path, capsys):
        fake.links = [short_url(TWICE), short_url(TWICE)]

        assert cli.main(["export", "--out-dir", str(tmp_path)]) == 1

        error = capsys.readouterr().err
        assert f"go.shlink.test/{TWICE}" in error
        assert "No snapshot was written" in error
        assert KEY not in error
        assert not list(tmp_path.iterdir())

    def test_a_miscount_writes_no_snapshot(self, fake, tmp_path, capsys):
        fake.links, fake.miscount = _links(), 1

        assert cli.main(["export", "--out-dir", str(tmp_path)]) == 1

        assert "No snapshot was written" in capsys.readouterr().err
        assert not list(tmp_path.iterdir())
