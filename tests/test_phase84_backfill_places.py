"""
Phase 8.4 — `python -m server.tools.backfill_places`: the countries and cities of the visits
saved without them (before cities, or while an image had no geolocation database), looked up as
the redirect does, from the stored address.

- It fills only what's empty, and never overwrites: run twice, the second run fills nothing.
- A city only where the visit's country is empty or agrees: never Zaragoza in France.
- Skipped: a visit imported from Shlink, whose address is "unknown".
- A dry run looks everything up, reports, and writes nothing.
- Without a geolocation database it stops, and writes nothing.
- What it prints are counts, never an address.
"""

from datetime import datetime

import pytest

from server.core.config import settings
from server.core.models import URL, URLType, Visitor
from server.tools import backfill_places
from server.utils import geo
from server.utils.domain import get_or_create_default_domain
from tests.conftest import TestingSessionLocal
from tests.test_geolocation import CITIES, write_database


@pytest.fixture
def cities(tmp_path, monkeypatch):
    path = write_database(tmp_path / "GeoLite2-City.mmdb", CITIES, "GeoLite2-City")
    monkeypatch.setattr(settings, "geoip_database", str(path))
    monkeypatch.setattr(backfill_places, "session_factory", TestingSessionLocal)
    geo.reset()
    yield path
    geo.reset()


@pytest.fixture
def visits(db_session, test_user):
    """Visits as production has them: saved before cities, one before countries too, one
    imported from Shlink, one from an address the database doesn't know."""
    url = URL(
        short_code="old",
        original_url="https://example.com",
        url_type=URLType.STANDARD,
        created_by=test_user.id,
        domain_id=get_or_create_default_domain(db_session).id,
    )
    db_session.add(url)
    db_session.flush()
    seeded = {
        "nothing": ("203.0.113.0", None, None),  # Zaragoza, ES
        "country only": ("203.0.113.64", "PT", None),  # Porto, PT
        "another country": ("203.0.113.0", "FR", None),  # DB-IP said FR; GeoLite2 says ES
        "city unknown": ("2001:db8::", None, None),  # FR, no city in the database
        "not in it": ("198.51.100.0", None, None),
        "from Shlink": ("unknown", None, None),
        "complete": ("203.0.113.0", "ES", "Madrid"),  # whatever it says, left alone
    }
    ids = {}
    for label, (ip, country, city) in seeded.items():
        visit = Visitor(
            url_id=url.id,
            short_code="old",
            ip=ip,
            country=country,
            city=city,
            visited_at=datetime(2026, 9, 1, 9, 0),
        )
        db_session.add(visit)
        db_session.flush()
        ids[label] = visit.id
    db_session.commit()
    return ids


def _places(db_session, ids) -> dict[str, tuple[str | None, str | None]]:
    db_session.expire_all()
    return {
        label: (visit.country, visit.city)
        for label, visit in ((label, db_session.get(Visitor, id_)) for label, id_ in ids.items())
    }


FILLED = {
    "nothing": ("ES", "Zaragoza"),
    "country only": ("PT", "Porto"),
    "another country": ("FR", None),
    "city unknown": ("FR", None),
    "not in it": (None, None),
    "from Shlink": (None, None),
    "complete": ("ES", "Madrid"),
}


@pytest.mark.usefixtures("cities")
class TestBackfill:
    def test_fills_only_whats_empty(self, db_session, visits, capsys):
        assert backfill_places.main([]) == 0

        assert _places(db_session, visits) == FILLED
        output = capsys.readouterr().out
        # Five had an address and something empty; Shlink's and the complete one weren't read.
        assert output.startswith("5 visits without a country or a city")
        assert "2 countries" in output and "2 cities" in output
        assert "203.0.113" not in output and "2001:db8" not in output

    def test_an_update_never_overwrites(self, db_session, visits):
        """Each UPDATE fills only where it's still empty: a visit the redirect or a second run
        filled meanwhile keeps what it has."""
        with TestingSessionLocal() as db:
            filled = backfill_places._fill(db, Visitor.city, "Porto", [visits["complete"]])
            db.commit()

        assert filled == 0
        assert _places(db_session, visits)["complete"] == ("ES", "Madrid")

    def test_a_second_run_fills_nothing(self, db_session, visits, capsys):
        backfill_places.main([])
        capsys.readouterr()

        assert backfill_places.main([]) == 0

        assert _places(db_session, visits) == FILLED
        assert "0 countries" in capsys.readouterr().out

    def test_in_batches(self, db_session, visits):
        assert backfill_places.main(["--batch-size", "2"]) == 0

        assert _places(db_session, visits) == FILLED

    def test_a_dry_run_writes_nothing(self, db_session, visits, capsys):
        before = _places(db_session, visits)

        assert backfill_places.main(["--dry-run"]) == 0

        assert _places(db_session, visits) == before
        output = capsys.readouterr().out
        assert "2 countries" in output and "Dry run" in output

    def test_counts_what_it_skipped(self, visits, capsys):
        backfill_places.main([])

        output = capsys.readouterr().out
        assert "1 imported from Shlink" in output
        assert "GeoLite2-City" in output  # which database it looked them up in


def test_without_a_database_it_stops(db_session, visits, monkeypatch, capsys):
    monkeypatch.setattr(settings, "geoip_database", "/nowhere/GeoLite2-City.mmdb")
    monkeypatch.setattr(settings, "geoip_fallback_database", "")
    monkeypatch.setattr(backfill_places, "session_factory", TestingSessionLocal)
    geo.reset()

    assert backfill_places.main([]) == 1

    assert _places(db_session, visits)["nothing"] == (None, None)
    assert "No geolocation database" in capsys.readouterr().err
    geo.reset()
