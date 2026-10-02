"""
Phase 8.4 — an export that's whole, or none (R17). Production's export listed 344 links with
343 distinct codes, and the import failed on the database's unique code. Shlink's default
order isn't stable across pages, but that wasn't it: Shlink holds two rows for
`co-upb-luis-ochoa`, a double submit on the default domain, whose NULL domain_id its unique
key doesn't catch.

So the list of short URLs is asked in code order, the export checks that its pages bring as
many links as Shlink counts, and a link's visits are asked up to the moment the export
started, so new ones can't shift their pages. A link listed twice is confirmed with Shlink
(`searchTerm`): identical copies it really holds collapse to one, recorded in the snapshot;
copies that differ, or copies Shlink doesn't hold (pages that moved), stop the export before
a snapshot is written. The review and the import refuse a snapshot that still lists a link
twice (tests/test_phase84_shlink_review.py, tests/test_phase84_shlink_import.py).
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


def _double_submit(**fields) -> list[dict]:
    """Production's: the same link twice, a moment apart, with no visits."""
    first = short_url(TWICE, visitsSummary={"total": 0, "nonBots": 0, "bots": 0})
    return [first, {**first, "dateCreated": "2026-07-27T16:36:07+02:00", **fields}]


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

    def test_an_overlap_is_caught_though_its_copies_are_identical(self):
        """Pages that move bring one link twice and miss another, and the count still adds
        up. The copies are one row, so identical: collapsing them would hide the missing
        link. Shlink, asked for that code, holds one, so the export stops."""
        fake = FakeShlink(_links(), unstable=True, ignores_order=True)

        with pytest.raises(SnapshotError, match="go.shlink.test/c1 2 times, but holds 1"):
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
        fake = FakeShlink(_double_submit(longUrl="https://example.com/other"))

        with pytest.raises(SnapshotError):
            _export(fake, visits=True)

        assert not [r for r in fake.requests if r.url.path.endswith("/visits")]


class TestALinkShlinkHoldsTwice:
    """Production's Shlink holds `co-upb-luis-ochoa` twice: a double submit on the default
    domain. Its unique key is (short_code, domain_id), and PostgreSQL doesn't compare NULLs."""

    def test_identical_copies_collapse_to_one(self):
        fake = FakeShlink([short_url("a"), *_double_submit(), short_url("z")])

        snapshot = _export(fake, page_size=2)

        assert _codes(snapshot) == ["a", TWICE, "z"]
        assert snapshot["links"][1]["short_url"] == _double_submit()[0]  # the first listed
        assert snapshot["duplicates_collapsed"] == [
            {"link": f"go.shlink.test/{TWICE}", "copies": 2, "visits": [0, 0]}
        ]

    def test_confirmed_with_shlink_by_its_code(self):
        fake = FakeShlink([short_url("a"), *_double_submit()])

        _export(fake)

        (search,) = [r for r in fake.requests if "searchTerm" in r.url.params]
        assert search.url.params["searchTerm"] == TWICE

    def test_its_visits_are_asked_once(self):
        """Shlink answers a link's visits by its domain and code, for one of its rows."""
        visits = [visit("2026-08-01T10:00:00+00:00")]
        fake = FakeShlink(_double_submit(), visits={(None, TWICE): visits})

        snapshot = _export(fake, visits=True)

        (entry,) = snapshot["links"]
        assert entry["visits"] == visits
        assert len([r for r in fake.requests if r.url.path.endswith("/visits")]) == 1

    def test_without_one_no_record_of_it(self):
        snapshot = _export(FakeShlink(_links()))

        assert "duplicates_collapsed" not in snapshot

    @pytest.mark.parametrize(
        ("fields", "named"),
        [
            ({"longUrl": "https://example.com/other"}, "longUrl"),
            ({"title": "Other", "tags": ["x"]}, "title, tags"),
            ({"meta": {"validSince": None, "validUntil": None, "maxVisits": 5}}, "meta"),
            ({"forwardQuery": False, "crawlable": True}, "forwardQuery, crawlable"),
        ],
    )
    def test_copies_that_differ_stop_it_naming_the_fields(self, fields, named):
        fake = FakeShlink(_double_submit(**fields))

        with pytest.raises(SnapshotError) as stopped:
            _export(fake)

        message = str(stopped.value)
        assert f"go.shlink.test/{TWICE}" in message and f"differ in {named}" in message
        assert "Exporting again won't help" in message and "decide which" in message

    def test_the_same_tags_in_another_order_are_identical(self):
        first, second = _double_submit()
        first["tags"], second["tags"] = ["a", "b"], ["b", "a"]

        snapshot = _export(FakeShlink([first, second]))

        assert _codes(snapshot) == [TWICE]


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

    def test_identical_copies_are_named_in_one_line(self, fake, tmp_path, capsys):
        fake.links = _double_submit()

        assert cli.main(["export", "--out-dir", str(tmp_path)]) == 0

        (path,) = tmp_path.glob("*.snapshot.json")
        notices = [line for line in capsys.readouterr().out.splitlines() if TWICE in line]
        assert notices == [
            f"Shlink holds identical copies of 1 link, exported once: go.shlink.test/{TWICE} "
            "(2 copies, 0 and 0 visits)."
        ]

    def test_copies_that_differ_write_no_snapshot(self, fake, tmp_path, capsys):
        fake.links = _double_submit(title="Other")

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
