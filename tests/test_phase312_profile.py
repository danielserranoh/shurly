"""
Phase 3.12 — the profile: first and last name, country and time zone.

`GET /api/v1/auth/me` returns it under `profile`, and `PATCH /api/v1/auth/me/profile`
changes the fields it's sent. Its row in `user_profiles` is made on the first save, so an
account without one reads as an empty profile.

Countries and time zones come from the `tzdata` package (server/utils/timezones.py), the
same list in every environment. The frontend's picker reads a JSON made from it
(frontend/src/data/timezones.json), which must match what the API accepts.
"""

import asyncio
import json
from pathlib import Path

import pytest
from sqlalchemy import inspect

from scripts.generate_timezones import OUTPUT
from server.core.models import User, UserProfile
from server.utils import timezones

PROFILE = "/api/v1/auth/me/profile"
EMPTY = {"first_name": None, "last_name": None, "country": None, "timezone": None}


def _profile(client, headers) -> dict:
    response = client.get("/api/v1/auth/me", headers=headers)
    assert response.status_code == 200
    return response.json()["profile"]


def _patch(client, headers, **fields):
    return client.patch(PROFILE, headers=headers, json=fields)


def _refused(response, field: str) -> str:
    """The message for `field` in a 422."""
    assert response.status_code == 422, response.text
    messages = [e["msg"] for e in response.json()["detail"] if e["loc"][-1] == field]
    assert messages, response.json()
    return messages[0]


class TestReading:
    def test_an_account_without_one_reads_as_empty(self, client, auth_headers, db_session):
        assert _profile(client, auth_headers) == EMPTY
        assert db_session.query(UserProfile).count() == 0  # reading makes no row

    def test_me_keeps_every_field_it_had(self, client, auth_headers):
        body = client.get("/api/v1/auth/me", headers=auth_headers).json()

        assert {
            "id",
            "email",
            "is_active",
            "created_at",
            "has_api_key",
            "api_key_prefix",
            "has_password",
            "has_google",
            "profile",
        } <= body.keys()


class TestUpdating:
    def test_saves_the_fields_sent(self, client, auth_headers):
        saved = {
            "first_name": "Ana",
            "last_name": "García",
            "country": "ES",
            "timezone": "Atlantic/Canary",
        }
        response = _patch(client, auth_headers, **saved)

        assert response.status_code == 200
        assert response.json() == saved
        assert _profile(client, auth_headers) == saved

    def test_changes_only_the_fields_sent(self, client, auth_headers):
        _patch(client, auth_headers, first_name="Ana", country="ES")
        response = _patch(client, auth_headers, timezone="Europe/Madrid")

        assert response.json() == {
            "first_name": "Ana",
            "last_name": None,
            "country": "ES",
            "timezone": "Europe/Madrid",
        }

    def test_null_or_blank_clears_a_field(self, client, auth_headers):
        _patch(client, auth_headers, first_name="Ana", last_name="García", country="ES")
        response = _patch(client, auth_headers, first_name=None, last_name="   ", country="")

        assert response.json() == EMPTY

    def test_nothing_sent_changes_nothing(self, client, auth_headers, db_session):
        response = _patch(client, auth_headers)

        assert response.status_code == 200
        assert response.json() == EMPTY
        assert db_session.query(UserProfile).count() == 0

    def test_one_row_per_account(self, client, auth_headers, db_session, test_user):
        _patch(client, auth_headers, first_name="Ana")
        _patch(client, auth_headers, last_name="García")

        rows = db_session.query(UserProfile).all()
        assert [(row.user_id, row.first_name, row.last_name) for row in rows] == [
            (test_user.id, "Ana", "García")
        ]

    def test_other_fields_are_refused(self, client, auth_headers):
        response = _patch(client, auth_headers, email="someone@else.test")

        assert response.status_code == 422

    def test_needs_a_signed_in_person(self, client):
        assert client.patch(PROFILE, json={"first_name": "Ana"}).status_code == 401


class TestNames:
    def test_are_trimmed(self, client, auth_headers):
        response = _patch(client, auth_headers, first_name="  José María ", last_name="\tNúñez ")

        assert response.json()["first_name"] == "José María"
        assert response.json()["last_name"] == "Núñez"

    def test_up_to_100_characters(self, client, auth_headers):
        assert _patch(client, auth_headers, first_name="a" * 100).status_code == 200
        assert "100" in _refused(_patch(client, auth_headers, first_name="a" * 101), "first_name")

    @pytest.mark.parametrize("name", ["Ana\nMaría", "Ana\x00", "Ana\u2028María"])
    def test_no_control_characters(self, client, auth_headers, name):
        _refused(_patch(client, auth_headers, last_name=name), "last_name")

    def test_must_be_text(self, client, auth_headers):
        _refused(_patch(client, auth_headers, first_name=42), "first_name")


class TestCountry:
    @pytest.mark.parametrize("sent", ["ES", "es", " es "])
    def test_an_iso_code_in_capitals(self, client, auth_headers, sent):
        assert _patch(client, auth_headers, country=sent).json()["country"] == "ES"

    @pytest.mark.parametrize("sent", ["XX", "ESP", "E", "Spain"])
    def test_anything_else_is_refused(self, client, auth_headers, sent):
        assert "ISO 3166-1" in _refused(_patch(client, auth_headers, country=sent), "country")


class TestTimezone:
    @pytest.mark.parametrize(
        "sent",
        ["Atlantic/Canary", "Europe/Madrid", "America/Argentina/Buenos_Aires", "Etc/UTC"],
    )
    def test_an_iana_name(self, client, auth_headers, sent):
        assert _patch(client, auth_headers, timezone=sent).json()["timezone"] == sent

    @pytest.mark.parametrize(
        "sent, stored",
        [
            # Chrome still reports this one for India.
            ("Asia/Calcutta", "Asia/Kolkata"),
            ("Europe/Kiev", "Europe/Kyiv"),
            ("US/Pacific", "America/Los_Angeles"),
            ("UTC", "Etc/UTC"),
        ],
    )
    def test_a_legacy_name_is_stored_as_the_current_one(self, client, auth_headers, sent, stored):
        assert _patch(client, auth_headers, timezone=sent).json()["timezone"] == stored

    def test_a_countrys_own_name_is_kept(self, client, auth_headers):
        # A link to Europe/Berlin since 2022, but the name zone.tab gives Sweden.
        response = _patch(client, auth_headers, timezone="Europe/Stockholm")

        assert response.json()["timezone"] == "Europe/Stockholm"

    def test_capitals_are_forgiven(self, client, auth_headers):
        response = _patch(client, auth_headers, timezone="atlantic/canary")

        assert response.json()["timezone"] == "Atlantic/Canary"

    @pytest.mark.parametrize("sent", ["+02:00", "UTC+2", "GMT+2", "2", "Mars/Olympus_Mons"])
    def test_an_offset_or_unknown_name_is_refused(self, client, auth_headers, sent):
        assert "IANA" in _refused(_patch(client, auth_headers, timezone=sent), "timezone")


class TestTheLists:
    def test_every_zone_the_picker_offers_is_stored_as_offered(self):
        offered = {zone for zones in timezones.zones_by_country().values() for zone in zones}

        assert "Etc/UTC" in timezones.picker_zones()
        assert offered < set(timezones.picker_zones())
        assert all(timezones.preferred_timezone(zone) == zone for zone in timezones.picker_zones())

    def test_every_alias_leads_to_a_zone_the_picker_offers_or_a_zone(self):
        offered = set(timezones.picker_zones())

        for alias, target in timezones.aliases().items():
            assert timezones.preferred_timezone(alias) == target
            assert target in offered or timezones.preferred_timezone(target) == target

    def test_the_countries_are_iso_3166(self):
        codes = timezones.countries()

        assert len(codes) > 240
        assert {"ES", "MX", "US", "GB", "SE"} <= set(codes)
        assert timezones.zones_by_country()["ES"] == [
            "Africa/Ceuta",
            "Atlantic/Canary",
            "Europe/Madrid",
        ]

    def test_the_frontend_list_matches_the_api(self):
        committed = json.loads(Path(OUTPUT).read_text(encoding="utf-8"))

        assert committed == timezones.picker_data(), (
            "frontend/src/data/timezones.json is out of date with the tzdata package: "
            "run `uv run python scripts/generate_timezones.py`"
        )


class TestThroughTheMcp:
    def test_update_my_profile_changes_only_what_it_is_sent(self, db_session, test_user):
        """An assistant setting the time zone must not clear the names it didn't send."""
        pytest.importorskip("fastmcp")
        from main import app
        from mcp_server.server import build_mcp_for_app
        from server.core import get_db
        from tests.test_phase54_mcp_auth import _bound_access_token

        db_session.add(UserProfile(user_id=test_user.id, first_name="Ana", country="IN"))
        test_user.set_api_key("profile-key")
        db_session.commit()
        app.dependency_overrides[get_db] = lambda: db_session
        try:
            with _bound_access_token("profile-key"):
                result = asyncio.run(
                    build_mcp_for_app(app).call_tool(
                        "update_my_profile", {"timezone": "Asia/Calcutta"}
                    )
                )
        finally:
            app.dependency_overrides.pop(get_db, None)

        assert result.structured_content == {
            "first_name": "Ana",
            "last_name": None,
            "country": "IN",
            "timezone": "Asia/Kolkata",
        }


class TestModel:
    def test_round_trips(self, db_session, test_user):
        db_session.add(
            UserProfile(
                user_id=test_user.id, first_name="Ana", country="ES", timezone="Europe/Madrid"
            )
        )
        db_session.commit()
        db_session.expire_all()

        profile = db_session.get(User, test_user.id).profile
        assert (profile.first_name, profile.last_name, profile.country, profile.timezone) == (
            "Ana",
            None,
            "ES",
            "Europe/Madrid",
        )
        assert profile.updated_at is not None

    def test_loading_an_account_leaves_its_profile_unloaded(self, db_session, test_user):
        db_session.add(UserProfile(user_id=test_user.id, first_name="Ana"))
        db_session.commit()
        db_session.expire_all()

        user = db_session.get(User, test_user.id)
        assert "profile" in inspect(user).unloaded

    def test_deleting_the_account_deletes_its_profile(self, db_session, test_user):
        db_session.add(UserProfile(user_id=test_user.id, first_name="Ana"))
        db_session.commit()

        db_session.delete(test_user)
        db_session.commit()

        assert db_session.query(UserProfile).count() == 0
