"""
Phase 8.4 — the country of Shurly's own visits: an ISO 3166-1 alpha-2 code from DB-IP's IP
to Country Lite database, looked up in process. With ANONYMIZE_REMOTE_ADDR on, the lookup
gets the anonymized address, the one stored: data minimisation, at the rare cost of a
country range finer than a /24. A missing or unreadable database means no country, logged
once, and never a failed redirect.
"""

import json
import time

import pytest
from fastapi.testclient import TestClient
from mmdb_writer import MMDBWriter
from netaddr import IPSet

from main import app
from server.core.config import settings
from server.core.models import URL, URLType, Visitor
from server.utils import geo
from server.utils.domain import get_or_create_default_domain


def write_database(path, networks: dict[str, str], database_type: str = "DBIP-Country-Lite"):
    """A tiny country database, DB-IP's shape by default: network → ISO code."""
    writer = MMDBWriter(ip_version=6, ipv4_compatible=True, database_type=database_type)
    for network, code in networks.items():
        writer.insert_network(IPSet([network]), {"country": {"iso_code": code}})
    writer.to_db_file(str(path))
    return path


# The two halves of 203.0.113.0/25 in different countries: the full address and the
# anonymized one (203.0.113.0) land in different ones.
NETWORKS = {"203.0.113.0/26": "ES", "203.0.113.64/26": "PT", "2001:db8::/32": "FR"}


@pytest.fixture
def database(tmp_path, monkeypatch):
    path = write_database(tmp_path / "country.mmdb", NETWORKS)
    monkeypatch.setattr(settings, "geoip_database", str(path))
    geo.reset()
    yield path
    geo.reset()


@pytest.fixture
def link(db_session, test_user) -> URL:
    url = URL(
        short_code="geo1",
        original_url="https://example.com/",
        url_type=URLType.STANDARD,
        created_by=test_user.id,
        domain_id=get_or_create_default_domain(db_session).id,
    )
    db_session.add(url)
    db_session.commit()
    return url


def _via_the_alb(client, path: str, address: str, monkeypatch):
    """A visit whose client IP the ALB put in X-Forwarded-For."""
    monkeypatch.setattr(settings, "trusted_proxies", ["172.31.0.0/16"])
    alb = TestClient(app, client=("172.31.0.10", 50000))
    return alb.get(path, headers={"x-forwarded-for": address}, follow_redirects=False)


def _events(capsys, name: str) -> list[dict]:
    lines = capsys.readouterr().err.splitlines()
    return [e for e in (json.loads(x) for x in lines if x.startswith("{")) if e["event"] == name]


class TestLookup:
    @pytest.mark.usefixtures("database")
    @pytest.mark.parametrize(
        ("address", "country"),
        [
            ("203.0.113.7", "ES"),
            ("203.0.113.77", "PT"),
            ("2001:db8::1", "FR"),
            ("198.51.100.1", None),  # not in the database
            ("unknown", None),  # a visit Shlink imported, or no address at all
            ("", None),
            (None, None),
        ],
    )
    def test_an_address_to_its_country(self, address, country):
        assert geo.country_of(address) == country


class TestVisits:
    @pytest.mark.usefixtures("database")
    def test_the_anonymized_address_is_looked_up(self, client, db_session, link, monkeypatch):
        """203.0.113.77 is in PT; its /24, the stored 203.0.113.0, in ES."""
        assert _via_the_alb(client, "/geo1", "203.0.113.77", monkeypatch).status_code == 302

        visit = db_session.query(Visitor).one()
        assert (visit.ip, visit.country) == ("203.0.113.0", "ES")

    @pytest.mark.usefixtures("database")
    def test_without_anonymization_the_full_address(self, client, db_session, link, monkeypatch):
        monkeypatch.setattr(settings, "anonymize_remote_addr", False)

        _via_the_alb(client, "/geo1", "203.0.113.77", monkeypatch)

        visit = db_session.query(Visitor).one()
        assert (visit.ip, visit.country) == ("203.0.113.77", "PT")

    @pytest.mark.usefixtures("database")
    def test_the_pixel_and_ipv6(self, client, db_session, link, monkeypatch):
        _via_the_alb(client, "/geo1/track", "2001:db8::abcd", monkeypatch)

        visit = db_session.query(Visitor).one()
        assert (visit.is_pixel, visit.country) == (True, "FR")

    @pytest.mark.usefixtures("database")
    def test_an_address_the_database_lacks(self, client, db_session, link, monkeypatch):
        _via_the_alb(client, "/geo1", "198.51.100.9", monkeypatch)

        assert db_session.query(Visitor).one().country is None


class TestWithoutADatabase:
    @pytest.mark.parametrize("contents", [None, b"not a database"])
    def test_no_country_one_log_line_and_the_redirect_still_works(
        self, client, db_session, link, tmp_path, monkeypatch, capsys, contents
    ):
        path = tmp_path / "country.mmdb"
        if contents is not None:
            path.write_bytes(contents)
        monkeypatch.setattr(settings, "geoip_database", str(path))
        geo.reset()
        capsys.readouterr()

        responses = [_via_the_alb(client, "/geo1", "203.0.113.7", monkeypatch) for _ in range(2)]

        assert [r.status_code for r in responses] == [302, 302]
        assert [v.country for v in db_session.query(Visitor).all()] == [None, None]
        (event,) = _events(capsys, "geo.database_missing")
        assert event["path"] == str(path)
        geo.reset()

    def test_turned_off_without_a_word(self, client, db_session, link, monkeypatch, capsys):
        monkeypatch.setattr(settings, "geoip_database", "")
        geo.reset()
        capsys.readouterr()

        _via_the_alb(client, "/geo1", "203.0.113.7", monkeypatch)

        assert db_session.query(Visitor).one().country is None
        assert _events(capsys, "geo.database_missing") == []


class TestGeoLite2AndItsFallback:
    """GEOIP_DATABASE is MaxMind's GeoLite2 City; GEOIP_FALLBACK_DATABASE, DB-IP's, when it
    isn't there. What opened is logged, with its age, and a GeoLite2 copy past 25 days too:
    MaxMind's licence wants it replaced within 30 of an update."""

    @pytest.fixture
    def databases(self, tmp_path, monkeypatch):
        geolite = write_database(
            tmp_path / "GeoLite2-City.mmdb", {"203.0.113.0/24": "ES"}, "GeoLite2-City"
        )
        dbip = write_database(tmp_path / "dbip.mmdb", {"203.0.113.0/24": "PT"})
        monkeypatch.setattr(settings, "geoip_database", str(geolite))
        monkeypatch.setattr(settings, "geoip_fallback_database", str(dbip))
        geo.reset()
        yield geolite, dbip
        geo.reset()

    def test_geolite2_first(self, databases, capsys):
        assert geo.country_of("203.0.113.0") == "ES"
        (event,) = _events(capsys, "geo.database_opened")
        assert (event["path"], event["database_type"]) == (str(databases[0]), "GeoLite2-City")
        assert event["age_days"] < 1 and event["built"]
        assert "primary" not in event

    def test_dbip_when_geolite2_isnt_there(self, databases, monkeypatch, capsys):
        monkeypatch.setattr(settings, "geoip_database", str(databases[0]) + ".gone")
        geo.reset()

        assert geo.country_of("203.0.113.0") == "PT"
        (event,) = _events(capsys, "geo.database_opened")
        assert event["path"] == str(databases[1])
        # Why it's DB-IP: the task's log says which file didn't open.
        assert event["primary"] == str(databases[0]) + ".gone"
        assert event["primary_error"] == "FileNotFoundError"

    def test_neither(self, databases, monkeypatch, capsys):
        monkeypatch.setattr(settings, "geoip_database", "/nowhere/a.mmdb")
        monkeypatch.setattr(settings, "geoip_fallback_database", "/nowhere/b.mmdb")
        geo.reset()

        assert geo.country_of("203.0.113.0") is None
        (event,) = _events(capsys, "geo.database_missing")
        assert (event["path"], event["fallback"]) == ("/nowhere/a.mmdb", "/nowhere/b.mmdb")
        assert event["error"] == event["fallback_error"] == "FileNotFoundError"

    def test_a_geolite2_copy_past_25_days_is_logged(self, databases, monkeypatch, capsys):
        monkeypatch.setattr(geo, "_now", lambda: time.time() + 26 * 86400)
        geo.reset()

        geo.country_of("203.0.113.0")

        (event,) = _events(capsys, "geo.database_stale")
        assert event["path"] == str(databases[0]) and event["age_days"] > 25

    def test_dbip_is_never_stale(self, databases, monkeypatch, capsys):
        """DB-IP's licence has no such rule."""
        monkeypatch.setattr(settings, "geoip_database", str(databases[1]))
        monkeypatch.setattr(geo, "_now", lambda: time.time() + 90 * 86400)
        geo.reset()

        geo.country_of("203.0.113.0")

        assert _events(capsys, "geo.database_stale") == []
