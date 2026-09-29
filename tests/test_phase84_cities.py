"""
Phase 8.4 — a visit's city in the breakdowns (ROADMAP 3.16.1, 3.17.1): `cities`, by city and
country, next to `countries`.

- A standard or custom link's breakdown lists every city, and "Unknown" (country null) for the
  visits without one.
- A campaign link's is null: its clicks are one named recipient's.
- A campaign's breakdown names a city only when its visits in the period came from at least 5 of
  the campaign's links, 5 recipients; the rest are summed into "Other cities" (country null).
  Otherwise a day on which one recipient clicked would name their city: the recipients list
  says who clicked when. Its countries are as they were.
- Never per visit: `/visits` and its CSV have no city.

"Now" is frozen at 2026-10-26 10:00 UTC (tests/test_phase316_link_analytics.py).
"""

import csv
import io

import pytest

from server.core.models import URL, URLType
from server.utils import local_days
from server.utils.domain import get_or_create_default_domain
from tests.test_phase316_link_analytics import NOW, _utc
from tests.test_phase316_link_analytics import _visit as _link_visit
from tests.test_phase317_campaign_analytics import _campaign, _recipient
from tests.test_phase317_campaign_analytics import _visit as _campaign_visit


@pytest.fixture(autouse=True)
def frozen_now(monkeypatch):
    monkeypatch.setattr(local_days, "_now", lambda: NOW)


def _cities(body: dict) -> list[tuple[str, str | None, int]]:
    return [(item["name"], item["country"], item["count"]) for item in body["cities"]]


def _link(db, owner, code: str, url_type=URLType.STANDARD) -> URL:
    url = URL(
        short_code=code,
        original_url="https://example.com",
        url_type=url_type,
        created_by=owner.id,
        domain_id=get_or_create_default_domain(db).id,
    )
    db.add(url)
    db.commit()
    return url


def _link_breakdown(client, headers, code: str, **params) -> dict:
    response = client.get(
        f"/api/v1/analytics/urls/{code}/breakdown", params=params, headers=headers
    )
    assert response.status_code == 200, response.text
    return response.json()


def _campaign_breakdown(client, headers, campaign, **params) -> dict:
    response = client.get(
        f"/api/v1/analytics/campaigns/{campaign.id}/breakdown", params=params, headers=headers
    )
    assert response.status_code == 200, response.text
    return response.json()


class TestALinksCities:
    @pytest.mark.parametrize("url_type", [URLType.STANDARD, URLType.CUSTOM])
    def test_every_city_by_count_with_its_country(
        self, client, auth_headers, db_session, test_user, url_type
    ):
        link = _link(db_session, test_user, "cities", url_type)
        for day, country, city in [
            (20, "ES", "Zaragoza"),
            (21, "ES", "Zaragoza"),
            (22, "ES", "Valencia"),
            (23, "VE", "Valencia"),  # another Valencia: another item
            (24, "FR", None),  # a country whose city the database doesn't know
            (25, None, None),  # nowhere at all
        ]:
            _link_visit(db_session, link, _utc(2026, 10, day, 9), country=country, city=city)

        body = _link_breakdown(client, auth_headers, "cities")

        assert _cities(body) == [
            ("Unknown", None, 2),
            ("Zaragoza", "ES", 2),
            ("Valencia", "ES", 1),
            ("Valencia", "VE", 1),
        ]
        assert sum(item["count"] for item in body["cities"]) == body["total"] == 6
        assert body["cities"][1]["share"] == round(2 / 6, 4)

    def test_counts_the_kind_asked_for(self, client, auth_headers, db_session, test_user):
        link = _link(db_session, test_user, "kinds")
        _link_visit(db_session, link, _utc(2026, 10, 20, 9), country="ES", city="Zaragoza")
        _link_visit(
            db_session, link, _utc(2026, 10, 20, 10), country="PT", city="Porto", is_pixel=True
        )
        _link_visit(
            db_session, link, _utc(2026, 10, 20, 11), country="US", city="Ashburn", is_bot=True
        )

        assert _cities(_link_breakdown(client, auth_headers, "kinds")) == [("Zaragoza", "ES", 1)]
        opens = _link_breakdown(client, auth_headers, "kinds", type="opens")
        assert _cities(opens) == [("Porto", "PT", 1)]
        bots = _link_breakdown(client, auth_headers, "kinds", type="bots")
        assert _cities(bots) == [("Ashburn", "US", 1)]

    def test_no_visits_no_cities(self, client, auth_headers, db_session, test_user):
        _link(db_session, test_user, "quiet")

        assert _link_breakdown(client, auth_headers, "quiet")["cities"] == []


class TestACampaignLink:
    def test_its_breakdown_has_no_cities(self, client, auth_headers, db_session, test_user):
        """Its clicks are one named recipient's: their city would locate them."""
        campaign = _campaign(db_session, test_user)
        ana = _recipient(db_session, campaign, "q4-ana", "Ana")
        _campaign_visit(db_session, ana, _utc(2026, 10, 20, 9), country="ES", city="Zaragoza")
        db_session.commit()

        body = _link_breakdown(client, auth_headers, "q4-ana")

        assert body["cities"] is None
        assert [item["name"] for item in body["countries"]] == ["ES"]  # countries stay


class TestNeverPerVisit:
    def test_the_visits_and_their_csv_have_no_city(
        self, client, auth_headers, db_session, test_user
    ):
        link = _link(db_session, test_user, "rows")
        _link_visit(db_session, link, _utc(2026, 10, 20, 9), country="ES", city="Zaragoza")

        visits = client.get("/api/v1/analytics/urls/rows/visits", headers=auth_headers).json()
        (row,) = visits["visits"]
        assert "city" not in row and row["country"] == "ES"

        exported = client.get("/api/v1/analytics/urls/rows/visits.csv", headers=auth_headers)
        rows = list(csv.reader(io.StringIO(exported.text)))
        assert not any("city" in column.lower() for column in rows[0])
        assert "Zaragoza" not in exported.text


@pytest.fixture
def campaign_of_ten(db_session, test_user):
    """Ten recipients, 01…10. Madrid: five of them, a click each. Zaragoza: one recipient who
    clicked ten times. Bilbao: four recipients. On 2026-10-24, only recipient 01 clicked."""
    campaign = _campaign(db_session, test_user)
    people = [_recipient(db_session, campaign, f"q4-{n:02}", f"Person {n}") for n in range(1, 11)]
    for person in people[:5]:
        _campaign_visit(db_session, person, _utc(2026, 10, 20, 9), country="ES", city="Madrid")
    for hour in range(10):
        _campaign_visit(
            db_session, people[5], _utc(2026, 10, 21, hour), country="ES", city="Zaragoza"
        )
    for person in people[6:10]:
        _campaign_visit(db_session, person, _utc(2026, 10, 22, 9), country="ES", city="Bilbao")
    _campaign_visit(db_session, people[0], _utc(2026, 10, 24, 12), country="ES", city="Madrid")
    db_session.commit()
    return campaign


class TestACampaignsCities:
    def test_a_city_is_named_from_five_recipients(self, client, auth_headers, campaign_of_ten):
        body = _campaign_breakdown(client, auth_headers, campaign_of_ten)

        # Madrid: 6 clicks from 5 recipients. Zaragoza's 10 are one recipient's and Bilbao's 4
        # are four's: "Other cities", whose total stays whole.
        assert _cities(body) == [("Other cities", None, 14), ("Madrid", "ES", 6)]
        assert body["total"] == 20 == sum(item["count"] for item in body["cities"])
        assert body["cities"][0]["share"] == 0.7

    def test_the_day_only_one_recipient_clicked_names_no_city(
        self, client, auth_headers, campaign_of_ten
    ):
        """The recipients list says who clicked on the 24th: only 01. Their city stays theirs."""
        body = _campaign_breakdown(
            client, auth_headers, campaign_of_ten, **{"from": "2026-10-24", "to": "2026-10-24"}
        )

        assert _cities(body) == [("Other cities", None, 1)]
        assert [(item["name"], item["count"]) for item in body["countries"]] == [("ES", 1)]

    def test_unknown_stays_unknown(self, client, auth_headers, db_session, test_user):
        campaign = _campaign(db_session, test_user)
        ana = _recipient(db_session, campaign, "q4-ana", "Ana")
        _campaign_visit(db_session, ana, _utc(2026, 10, 20, 9), country="ES")
        db_session.commit()

        assert _cities(_campaign_breakdown(client, auth_headers, campaign)) == [
            ("Unknown", None, 1)
        ]

    def test_opens_are_held_to_the_same_floor(self, client, auth_headers, db_session, test_user):
        campaign = _campaign(db_session, test_user)
        people = [_recipient(db_session, campaign, f"q4-{n}", f"Person {n}") for n in range(6)]
        for person in people[:5]:
            _campaign_visit(
                db_session,
                person,
                _utc(2026, 10, 20, 9),
                country="ES",
                city="Madrid",
                is_pixel=True,
            )
        _campaign_visit(
            db_session, people[5], _utc(2026, 10, 20, 9), country="PT", city="Porto", is_pixel=True
        )
        db_session.commit()

        body = _campaign_breakdown(client, auth_headers, campaign, type="opens")

        assert _cities(body) == [("Madrid", "ES", 5), ("Other cities", None, 1)]
