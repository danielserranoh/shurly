"""Phase 3.10.5 — CSV export from analytics endpoints."""

import csv
import io

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from server.core.models import URL, Campaign, User, Visitor
from server.core.models.url import URLType
from server.utils.domain import get_or_create_default_domain


@pytest.mark.integration
class TestCSVExport:
    def _make_url(self, db_session: Session, test_user: User, code: str = "csv1") -> URL:
        domain = get_or_create_default_domain(db_session)
        url = URL(
            short_code=code,
            domain_id=domain.id,
            original_url="https://example.com",
            url_type=URLType.STANDARD,
            created_by=test_user.id,
        )
        db_session.add(url)
        db_session.commit()
        db_session.refresh(url)
        return url

    def test_daily_csv_headers_and_disposition(
        self, client: TestClient, db_session: Session, test_user: User, auth_headers
    ):
        self._make_url(db_session, test_user, "csv1")
        r = client.get(
            "/api/v1/analytics/urls/csv1/daily?format=csv", headers=auth_headers
        )
        assert r.status_code == 200
        assert r.headers["content-type"].startswith("text/csv")
        assert "csv1-daily.csv" in r.headers.get("content-disposition", "")

        rows = list(csv.reader(io.StringIO(r.text)))
        assert rows[0] == ["date", "clicks"]
        # 7 days of data after the header
        assert len(rows) == 8

    def test_geo_csv_structure(
        self, client: TestClient, db_session: Session, test_user: User, auth_headers
    ):
        url = self._make_url(db_session, test_user, "csv2")
        for ip, country in [("1.1.1.1", "ES"), ("2.2.2.2", "ES"), ("3.3.3.3", "FR")]:
            db_session.add(
                Visitor(
                    url_id=url.id,
                    short_code="csv2",
                    ip=ip,
                    country=country,
                    is_bot=False,
                    is_pixel=False,
                )
            )
        db_session.commit()

        r = client.get(
            "/api/v1/analytics/urls/csv2/geo?format=csv", headers=auth_headers
        )
        assert r.status_code == 200
        rows = list(csv.reader(io.StringIO(r.text)))
        assert rows[0] == ["country", "clicks"]
        # ES has 2, FR has 1; order should follow the JSON endpoint (clicks desc)
        countries = {row[0]: int(row[1]) for row in rows[1:]}
        assert countries == {"ES": 2, "FR": 1}

    def test_invalid_format_rejected(
        self, client: TestClient, db_session: Session, test_user: User, auth_headers
    ):
        self._make_url(db_session, test_user, "csv3")
        r = client.get(
            "/api/v1/analytics/urls/csv3/daily?format=xml", headers=auth_headers
        )
        assert r.status_code == 422  # Pydantic regex validation

    def test_default_format_still_json(
        self, client: TestClient, db_session: Session, test_user: User, auth_headers
    ):
        self._make_url(db_session, test_user, "csv4")
        r = client.get("/api/v1/analytics/urls/csv4/daily", headers=auth_headers)
        assert r.status_code == 200
        assert r.headers["content-type"].startswith("application/json")
        assert r.json()["short_code"] == "csv4"


@pytest.mark.integration
class TestCampaignUsersCSV:
    def test_campaign_users_csv_flattens_user_data(
        self, client: TestClient, db_session: Session, test_user: User, auth_headers
    ):
        domain = get_or_create_default_domain(db_session)
        campaign = Campaign(
            name="C1",
            original_url="https://example.com",
            csv_columns=["firstName", "lastName"],
            created_by=test_user.id,
        )
        db_session.add(campaign)
        db_session.flush()

        for i, (fn, ln) in enumerate([("Ada", "Lovelace"), ("Alan", "Turing")]):
            db_session.add(
                URL(
                    short_code=f"camp{i}",
                    domain_id=domain.id,
                    original_url="https://example.com",
                    url_type=URLType.CAMPAIGN,
                    user_data={"firstName": fn, "lastName": ln},
                    campaign_id=campaign.id,
                    created_by=test_user.id,
                )
            )
        db_session.commit()

        r = client.get(
            f"/api/v1/analytics/campaigns/{campaign.id}/users?format=csv",
            headers=auth_headers,
        )
        assert r.status_code == 200
        rows = list(csv.reader(io.StringIO(r.text)))
        # Headers: firstName, lastName, short_code, clicks, unique_ips, last_clicked
        assert rows[0][:2] == ["firstName", "lastName"]
        assert "short_code" in rows[0]
        names = {(row[0], row[1]) for row in rows[1:]}
        assert names == {("Ada", "Lovelace"), ("Alan", "Turing")}
