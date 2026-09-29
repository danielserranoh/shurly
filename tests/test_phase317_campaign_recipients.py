"""
Phase 3.17 — a campaign's recipients (ROADMAP 3.17.1): all time, for following up with people,
who clicked and who hasn't. Filtered (Clicked, Opened, neither), searched over `user_data`'s
values and the code, sorted and paged in SQL, with the counts each filter would give for the
search. Its CSV takes the same filter, search and sort. Scoped exactly like `/users`, since it
shows the same names and emails.

"Now" is frozen at 2026-10-26 10:00 UTC.
"""

import csv
import io

import pytest

from server.core.models import URL, Organization, OrganizationMember, OrgRole, User
from server.utils import local_days
from server.utils.url import link_short_url
from tests.test_phase316_link_analytics import CURL, NOW, _utc
from tests.test_phase317_campaign_analytics import _campaign, _get, _recipient, _visit

ROUTES = ("recipients", "recipients.csv")


@pytest.fixture(autouse=True)
def frozen_now(monkeypatch):
    monkeypatch.setattr(local_days, "_now", lambda: NOW)


@pytest.fixture
def people(db_session, test_user) -> dict[str, URL]:
    """
    Ana clicked twice and opened once; Luis opened twice; Pedro clicked once; Marta did
    neither, though a bot visited her link. Clicked and Opened overlap on Ana.
    """
    campaign = _campaign(db_session, test_user)
    rows = {
        "ana": {"name": "Ana Muñoz", "email": "ana@example.com"},
        "luis": {"name": "Luis", "email": "luis@example.com"},
        "marta": {"name": "Marta", "email": "marta@example.com"},
        "pedro": {"name": '=HYPERLINK("https://x.test")', "email": "pedro_g@example.com"},
    }
    links = {}
    for key, row in rows.items():
        links[key] = _recipient(db_session, campaign, f"q4-{key}", row["name"])
        links[key].user_data = row
    _visit(db_session, links["ana"], _utc(2026, 10, 20, 9))
    _visit(db_session, links["ana"], _utc(2026, 10, 25, 21, 30, 5, 123456))
    _visit(db_session, links["ana"], _utc(2026, 10, 24, 8), is_pixel=True)
    _visit(db_session, links["luis"], _utc(2026, 10, 22, 8), is_pixel=True)
    _visit(db_session, links["luis"], _utc(2026, 10, 23, 8), is_pixel=True)
    _visit(db_session, links["pedro"], _utc(2026, 10, 26, 9))
    _visit(db_session, links["marta"], _utc(2026, 10, 26, 9), is_bot=True, user_agent=CURL)
    _visit(db_session, links["marta"], _utc(2026, 10, 26, 9), is_pixel=True, is_bot=True)
    db_session.commit()
    links["campaign"] = campaign
    return links


def _list(client, auth_headers, people, **params):
    return _get(client, auth_headers, people["campaign"], "recipients", **params)


def _codes(body) -> list[str]:
    return [r["short_code"] for r in body["recipients"]]


class TestRecipients:
    def test_every_recipient_all_time(self, client, auth_headers, people):
        body = _list(client, auth_headers, people, tz="Europe/Madrid").json()

        assert (body["campaign_name"], body["timezone"], body["filter"], body["q"]) == (
            "Q4 webinar",
            "Europe/Madrid",
            "all",
            "",
        )
        assert (body["sort"], body["order"], body["total"], body["page"], body["page_size"]) == (
            "clicks",
            "desc",
            4,
            1,
            50,
        )
        # Most clicks first; ties by the latest click (Pedro's is the newest), then the code.
        assert _codes(body) == ["q4-ana", "q4-pedro", "q4-luis", "q4-marta"]
        ana = body["recipients"][0]
        assert ana == {
            "short_code": "q4-ana",
            "short_url": link_short_url(people["ana"]),
            "domain": people["ana"].domain.hostname,
            "user_data": {"name": "Ana Muñoz", "email": "ana@example.com"},
            "clicks": 2,
            "opens": 1,
            "first_click_at": "2026-10-20T11:00:00+02:00",
            "last_click_at": "2026-10-25T22:30:05+01:00",  # to the second, after DST ended
            "last_open_at": "2026-10-24T10:00:00+02:00",
        }
        marta = body["recipients"][3]  # a bot's visits aren't hers
        assert (marta["clicks"], marta["opens"], marta["last_click_at"]) == (0, 0, None)

    def test_the_counts_each_filter_gives(self, client, auth_headers, people):
        """Clicked and Opened overlap on Ana: the counts aren't a partition of all."""
        body = _list(client, auth_headers, people).json()

        assert body["counts"] == {"all": 4, "clicked": 2, "opened": 2, "none": 1}

    @pytest.mark.parametrize(
        "which, codes",
        [
            ("clicked", ["q4-ana", "q4-pedro"]),
            ("opened", ["q4-ana", "q4-luis"]),
            ("none", ["q4-marta"]),
        ],
    )
    def test_a_filter_leaves_the_counts(self, client, auth_headers, people, which, codes):
        body = _list(client, auth_headers, people, filter=which).json()

        assert (_codes(body), body["total"], body["filter"]) == (codes, len(codes), which)
        assert body["counts"] == {"all": 4, "clicked": 2, "opened": 2, "none": 1}

    @pytest.mark.parametrize(
        "q, codes",
        [
            ("muñoz", ["q4-ana"]),  # a value, ignoring case
            ("LUIS@EXAMPLE", ["q4-luis"]),
            ("q4-ma", ["q4-marta"]),  # the code
            ("email", []),  # a key, not a value
            ("_", ["q4-pedro"]),  # a character, not LIKE's any-one-character
            ("%", []),
        ],
    )
    def test_a_search(self, client, auth_headers, people, q, codes):
        body = _list(client, auth_headers, people, q=q).json()

        assert (_codes(body), body["q"]) == (codes, q)

    def test_the_counts_follow_the_search(self, client, auth_headers, people):
        body = _list(client, auth_headers, people, q="a", filter="none").json()

        # Every row has an "a" (every email does), so all four, whatever the filter.
        assert body["counts"] == {"all": 4, "clicked": 2, "opened": 2, "none": 1}
        narrowed = _list(client, auth_headers, people, q="ana@").json()
        assert narrowed["counts"] == {"all": 1, "clicked": 1, "opened": 1, "none": 0}

    @pytest.mark.parametrize(
        "sort, order, codes",
        [
            ("opens", "desc", ["q4-luis", "q4-ana", "q4-pedro", "q4-marta"]),
            ("clicks", "asc", ["q4-luis", "q4-marta", "q4-pedro", "q4-ana"]),
            ("last_click", "desc", ["q4-pedro", "q4-ana", "q4-luis", "q4-marta"]),
            ("last_click", "asc", ["q4-ana", "q4-pedro", "q4-luis", "q4-marta"]),
            ("code", "asc", ["q4-ana", "q4-luis", "q4-marta", "q4-pedro"]),
            ("code", "desc", ["q4-pedro", "q4-marta", "q4-luis", "q4-ana"]),
        ],
    )
    def test_sorted(self, client, auth_headers, people, sort, order, codes):
        body = _list(client, auth_headers, people, sort=sort, order=order).json()

        assert _codes(body) == codes

    def test_a_page_at_a_time(self, client, auth_headers, people):
        second = _list(client, auth_headers, people, page=2, page_size=3).json()

        assert (second["total"], second["pages"], _codes(second)) == (4, 2, ["q4-marta"])

    @pytest.mark.parametrize(
        "params",
        [
            {"filter": "some"},
            {"sort": "name"},
            {"order": "sideways"},
            {"page": 0},
            {"page_size": 0},
            {"page_size": 201},
            {"tz": "Mars/Olympus_Mons"},
        ],
    )
    def test_what_it_refuses(self, client, auth_headers, people, params):
        assert _list(client, auth_headers, people, **params).status_code == 422


class TestCsv:
    def test_the_same_filter_search_and_sort(self, client, auth_headers, people):
        response = _get(
            client,
            auth_headers,
            people["campaign"],
            "recipients.csv",
            filter="clicked",
            q="example",
        )

        assert response.status_code == 200
        assert response.headers["content-type"].startswith("text/csv")
        rows = list(csv.DictReader(io.StringIO(response.text)))
        assert list(rows[0]) == [
            "name",
            "email",
            "short_code",
            "short_url",
            "clicks",
            "opens",
            "first_click_at",
            "last_click_at",
            "last_open_at",
        ]
        assert [(r["short_code"], r["clicks"], r["opens"]) for r in rows] == [
            ("q4-ana", "2", "1"),
            ("q4-pedro", "1", "0"),
        ]

    def test_every_cell_is_spreadsheet_safe(self, client, auth_headers, people):
        """`user_data` comes from people's CSVs: a name that starts like a formula stays text."""
        response = _get(client, auth_headers, people["campaign"], "recipients.csv", q="pedro")

        (row,) = list(csv.DictReader(io.StringIO(response.text)))
        assert row["name"] == '\'=HYPERLINK("https://x.test")'


class TestScope:
    """Names and emails: exactly whom `/users` shows them to."""

    @pytest.mark.parametrize("role, expected", [(OrgRole.MEMBER, 200), (None, 404)])
    def test_as_users_decides(self, client, db_session, test_user, role, expected):
        from server.core.auth import create_access_token

        organization = Organization(name="Griddo")
        viewer = User(email="viewer@griddo.io", password_hash="x", is_active=True)
        db_session.add_all([organization, viewer])
        db_session.flush()
        db_session.add(
            OrganizationMember(
                organization_id=organization.id, user_id=test_user.id, role=OrgRole.OWNER
            )
        )
        if role is not None:
            db_session.add(
                OrganizationMember(organization_id=organization.id, user_id=viewer.id, role=role)
            )
        shared = _campaign(db_session, test_user, organization_id=organization.id)
        db_session.commit()
        headers = {"Authorization": f"Bearer {create_access_token(data={'sub': viewer.email})}"}

        assert _get(client, headers, shared, "users").status_code == expected
        for route in ROUTES:
            assert _get(client, headers, shared, route).status_code == expected, route

    def test_an_id_that_isnt_one(self, client, auth_headers):
        for route in ROUTES:
            url = f"/api/v1/analytics/campaigns/nope/{route}"
            assert client.get(url, headers=auth_headers).status_code == 400, route
