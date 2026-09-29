"""
Analytics queries that only PostgreSQL can reject.

The suite runs on SQLite, which lets a GROUP BY include a `json` column.
PostgreSQL doesn't: `json` has no equality operator. The campaign summary's
top-performers query grouped by `urls.user_data` (JSON), so on PostgreSQL every
campaign summary returned 500 ("could not identify an equality operator for
type json") while the SQLite tests stayed green. Found in the 3.14 frontend's
manual pass against docker-compose's PostgreSQL.

The schema here comes from the real migrations, as in production.
"""

from __future__ import annotations

from datetime import datetime

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import sessionmaker

from main import app
from server.core import get_db
from server.core.auth import create_access_token, hash_password
from server.core.migrations import run_migrations
from server.core.models import URL, Campaign, URLType, User, Visitor
from server.utils.domain import get_or_create_default_domain


@pytest.fixture
def pg_session(pg_engine):
    run_migrations(pg_engine)
    session = sessionmaker(bind=pg_engine)()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture
def pg_client(pg_session):
    def override_get_db():
        yield pg_session

    app.dependency_overrides[get_db] = override_get_db
    try:
        with TestClient(app) as client:
            yield client
    finally:
        app.dependency_overrides.clear()


def test_campaign_summary_works_on_postgresql(pg_client, pg_session):
    user = User(email="owner@example.com", password_hash=hash_password("secret123"), is_active=True)
    pg_session.add(user)
    pg_session.flush()
    campaign = Campaign(
        name="Q4", original_url="https://example.org", csv_columns=["name"], created_by=user.id
    )
    pg_session.add(campaign)
    pg_session.flush()
    domain = get_or_create_default_domain(pg_session)
    for i, name in enumerate(("Ana", "Luis")):
        url = URL(
            short_code=f"pgq4{i}",
            original_url="https://example.org",
            url_type=URLType.CAMPAIGN,
            campaign_id=campaign.id,
            user_data={"name": name},
            created_by=user.id,
            domain_id=domain.id,
        )
        pg_session.add(url)
        pg_session.flush()
        for _ in range(i + 1):
            pg_session.add(
                Visitor(
                    url_id=url.id,
                    short_code=url.short_code,
                    ip="203.0.113.0",
                    visited_at=datetime.utcnow(),
                )
            )
    pg_session.commit()

    token = create_access_token(data={"sub": user.email})
    response = pg_client.get(
        f"/api/v1/analytics/campaigns/{campaign.id}/summary",
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 200, response.text
    top = response.json()["top_performers"]
    assert [p["user_data"]["name"] for p in top] == ["Luis", "Ana"]  # most clicks first
    assert [p["clicks"] for p in top] == [2, 1]


def test_a_links_analytics_on_postgresql(pg_client, pg_session):
    """
    Phase 3.16 — the per-link routes on PostgreSQL, and visits of the same instant paged
    without repeats. SQL leaves the order of ties open, so the list breaks them by id.
    """
    user = User(email="owner@example.com", password_hash=hash_password("secret123"), is_active=True)
    pg_session.add(user)
    pg_session.flush()
    url = URL(
        short_code="pg316",
        original_url="https://example.org",
        created_by=user.id,
        domain_id=get_or_create_default_domain(pg_session).id,
    )
    pg_session.add(url)
    pg_session.flush()
    instant = datetime.utcnow().replace(microsecond=0)
    for n in range(40):
        pg_session.add(
            Visitor(
                url_id=url.id,
                short_code=url.short_code,
                ip="203.0.113.0",
                user_agent=f"Mozilla/5.0 (Windows NT 10.0) Chrome/{100 + n}.0 Safari/537.36",
                referer=f"https://r{n}.example/",
                country="ES" if n % 2 else None,
                visited_at=instant,
            )
        )
    pg_session.commit()
    headers = {"Authorization": f"Bearer {create_access_token(data={'sub': user.email})}"}
    base = "/api/v1/analytics/urls/pg316"

    seen = []
    for page in range(1, 7):
        response = pg_client.get(f"{base}/visits?page={page}&page_size=7", headers=headers)
        assert response.status_code == 200, response.text
        seen += [visit["referrer"] for visit in response.json()["visits"]]
    assert sorted(seen) == sorted(f"r{n}.example" for n in range(40))

    for route in ("totals", "timeseries?group_by=week", "breakdown?type=all", "visits.csv"):
        assert pg_client.get(f"{base}/{route}", headers=headers).status_code == 200, route
    breakdown = pg_client.get(f"{base}/breakdown", headers=headers).json()
    assert [(c["name"], c["count"]) for c in breakdown["countries"]] == [
        ("ES", 20),
        ("Unknown", 20),
    ]


def test_a_campaigns_analytics_on_postgresql(pg_client, pg_session):
    """Phase 3.17 — a campaign's routes on PostgreSQL: its links' visits, through a subquery."""
    user = User(email="owner@example.com", password_hash=hash_password("secret123"), is_active=True)
    pg_session.add(user)
    pg_session.flush()
    campaign = Campaign(
        name="Q4", original_url="https://example.org", csv_columns=["name"], created_by=user.id
    )
    pg_session.add(campaign)
    pg_session.flush()
    domain = get_or_create_default_domain(pg_session)
    for i, name in enumerate(("Ana", "Luis", "Marta")):
        url = URL(
            short_code=f"pg317{i}",
            original_url="https://example.org",
            url_type=URLType.CAMPAIGN,
            campaign_id=campaign.id,
            user_data={"name": name},
            created_by=user.id,
            domain_id=domain.id,
        )
        pg_session.add(url)
        pg_session.flush()
        for pixel in [False] * (2 - i) + [True] * i:  # Ana 2 clicks, Luis 1 and 1, Marta 2 opens
            pg_session.add(
                Visitor(
                    url_id=url.id,
                    short_code=url.short_code,
                    ip="203.0.113.0",
                    is_pixel=pixel,
                    visited_at=datetime.utcnow(),
                )
            )
    pg_session.commit()
    headers = {"Authorization": f"Bearer {create_access_token(data={'sub': user.email})}"}
    base = f"/api/v1/analytics/campaigns/{campaign.id}"

    totals = pg_client.get(f"{base}/totals", headers=headers).json()
    assert (totals["recipients"], totals["clicked"], totals["opened"]) == (3, 2, 2)
    assert (totals["clicks"], totals["opens"], totals["click_rate"]) == (3, 3, 0.6667)
    for route in ("timeseries?group_by=month", "breakdown?type=all"):
        assert pg_client.get(f"{base}/{route}", headers=headers).status_code == 200, route
