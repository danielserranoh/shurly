"""
Phase 8.4 — scripts/fetch_geoip.py, which the image build runs: DB-IP's IP to Country Lite,
this month's or last month's, installed only once it opens and knows that 8.8.8.8 is in
the US. It never fails: without a database, visits have no country.
"""

import gzip
import importlib.util
import io
from datetime import date
from pathlib import Path
from urllib.error import HTTPError

from tests.test_geolocation import write_database

_spec = importlib.util.spec_from_file_location(
    "fetch_geoip", Path(__file__).parents[1] / "scripts" / "fetch_geoip.py"
)
fetch_geoip = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(fetch_geoip)

TODAY = date(2026, 9, 28)
SEPTEMBER = "https://download.db-ip.com/free/dbip-country-lite-2026-09.mmdb.gz"
AUGUST = "https://download.db-ip.com/free/dbip-country-lite-2026-08.mmdb.gz"


class FakeDBIP:
    """download.db-ip.com: the months it has, gzipped; a 404 for the others."""

    def __init__(self, files: dict[str, bytes]):
        self.files = files
        self.asked: list[str] = []

    def __call__(self, url, timeout=None):
        self.asked.append(url)
        if url not in self.files:
            raise HTTPError(url, 404, "Not Found", {}, None)
        return io.BytesIO(gzip.compress(self.files[url]))


def database(tmp_path, networks) -> bytes:
    return write_database(tmp_path / f"{len(networks)}.mmdb", networks).read_bytes()


def good(tmp_path) -> bytes:
    return database(tmp_path, {"8.8.8.0/24": "US", "203.0.113.0/24": "ES"})


def test_this_months_file(tmp_path):
    dbip = FakeDBIP({SEPTEMBER: good(tmp_path)})

    installed = fetch_geoip.fetch(tmp_path / "data", TODAY, opener=dbip)

    assert installed == tmp_path / "data" / "dbip-country-lite.mmdb"
    assert dbip.asked == [SEPTEMBER]


def test_last_months_while_this_months_isnt_out(tmp_path):
    dbip = FakeDBIP({AUGUST: good(tmp_path)})

    assert fetch_geoip.fetch(tmp_path / "data", TODAY, opener=dbip) is not None
    assert dbip.asked == [SEPTEMBER, AUGUST]


def test_january_falls_back_to_december():
    assert fetch_geoip.months(date(2027, 1, 3)) == ["2027-01", "2026-12"]


def test_a_file_that_doesnt_know_8_8_8_8_isnt_installed(tmp_path, capsys):
    wrong = database(tmp_path, {"8.8.8.0/24": "DE"})  # a wrong country, not just a missing one
    dbip = FakeDBIP({SEPTEMBER: wrong, AUGUST: b"not a database"})

    assert fetch_geoip.fetch(tmp_path / "data", TODAY, opener=dbip) is None

    assert not (tmp_path / "data" / "dbip-country-lite.mmdb").exists()
    output = capsys.readouterr().out
    assert "8.8.8.8" in output and "doesn't open" in output


def test_never_a_failure_and_a_file_already_there_stays(tmp_path, monkeypatch, capsys):
    installed = tmp_path / "data" / "dbip-country-lite.mmdb"
    installed.parent.mkdir()
    installed.write_bytes(b"last month's")
    monkeypatch.setattr(fetch_geoip, "urlopen", FakeDBIP({}))

    assert fetch_geoip.main([str(tmp_path / "data")]) == 0

    assert installed.read_bytes() == b"last month's"
    assert "visits will have no country" in capsys.readouterr().out
