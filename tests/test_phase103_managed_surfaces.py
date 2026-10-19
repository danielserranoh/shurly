"""
Phase 10.3 — the other surfaces that show a link's destination (plan T3).

A managed link's destination (a link made through a service account, server/utils/managed.py)
is read only by its manager and the owners of its organization; everyone else gets the mask,
`https://propuestas.griddo.io/…`. Besides the link responses (tests/test_phase103_managed_api.py),
that's the overview's `top_urls`, the owners' and admins' `GET /service-accounts/{id}/links`
and the curated MCP tools. Masking hides nothing from the numbers: the totals still count
managed links and their clicks.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

import pytest

from server.core.models import URL, OrgRole, User, Visitor
from server.core.models.url import URLType
from server.utils import organization as org_service
from server.utils.domain import get_or_create_default_domain
from tests.test_phase101_service_accounts import (
    BASE,
    _bearer,
    _create_account,
    _for_ana,
    _issue,
    _make_link,
    _person,
    _session,
)

SECRET = "https://propuestas.griddo.io/p/abc?t=s3cr3t"
MASK = "https://propuestas.griddo.io/…"
ORDINARY = "https://example.com/ana?x=1"
OVERVIEW = "/api/v1/analytics/overview"
PROTECTED = "This link is managed by Propuestas Griddo. Change or delete it from there."

# Who reads a managed link's destination, and who gets the mask.
SEES = ["owner", "manager"]
MASKED = ["bob", "ana", "admin"]


@pytest.fixture
def world(client, db_session):
    """Propuestas (a member service account) made a link for Ana: managed, 3 clicks and a
    bot's visit. Ana made one herself: ordinary, 1 click."""
    team = {
        "owner": _person(db_session, "owner@griddo.io", OrgRole.OWNER, "Olga", "Owner"),
        "admin": _person(db_session, "admin@griddo.io", OrgRole.ADMIN),
        "ana": _person(db_session, "ana.garcia@griddo.io", OrgRole.MEMBER, "Ana", "García"),
        "bob": _person(db_session, "bob@griddo.io", OrgRole.MEMBER),
    }
    account = _create_account(client, team)
    token = _issue(client, team, account["id"])["token"]

    made = _make_link(client, _for_ana({"token": token}), url=SECRET)
    assert made.status_code == 201, made.text
    mine = _make_link(client, _session(team["ana"]), url=ORDINARY)
    assert mine.status_code == 201, mine.text

    def link(code: str) -> URL:
        return db_session.query(URL).filter(URL.short_code == code).one()

    managed_link, ordinary = link(made.json()["short_code"]), link(mine.json()["short_code"])
    now = datetime.now(timezone.utc)
    visits = [(managed_link, f"10.0.0.{n}", False) for n in range(3)]
    visits += [(managed_link, "10.0.9.9", True), (ordinary, "10.0.1.1", False)]
    db_session.add_all(
        Visitor(url_id=url.id, short_code=url.short_code, ip=ip, visited_at=now, is_bot=bot)
        for url, ip, bot in visits
    )
    db_session.commit()

    return {
        **team,
        "manager": db_session.get(User, uuid.UUID(account["id"])),
        "account_id": account["id"],
        "token": token,
        "managed": managed_link,
        "ordinary": ordinary,
    }


def _headers(world, who: str) -> dict:
    return _bearer(world["token"]) if who == "manager" else _session(world[who])


def _overview(client, world, who: str) -> dict:
    response = client.get(OVERVIEW, headers=_headers(world, who))
    assert response.status_code == 200, response.text
    return response.json()


def _top(overview: dict, url: URL) -> dict:
    return next(item for item in overview["top_urls"] if item["short_code"] == url.short_code)


class TestOverviewTopUrls:
    @pytest.mark.parametrize("who", MASKED)
    def test_masked_for_members_the_person_it_was_made_for_and_admins(self, client, world, who):
        overview = _overview(client, world, who)
        assert _top(overview, world["managed"])["original_url"] == MASK
        assert _top(overview, world["ordinary"])["original_url"] == ORDINARY
        assert "s3cr3t" not in str(overview)

    @pytest.mark.parametrize("who", SEES)
    def test_the_owner_and_the_manager_read_it(self, client, world, who):
        overview = _overview(client, world, who)
        assert _top(overview, world["managed"])["original_url"] == SECRET
        assert _top(overview, world["ordinary"])["original_url"] == ORDINARY

    def test_the_totals_still_count_managed_links_and_their_clicks(self, client, world):
        seen = {who: _overview(client, world, who) for who in MASKED + SEES}
        for who, overview in seen.items():
            assert overview["total_urls"] == 2, who
            assert overview["total_clicks"] == 4, who  # 3 on the managed link, 1 on Ana's
            assert overview["total_unique_visitors"] == 4, who
            assert overview["recent_clicks_7d"] == 4, who
            top = _top(overview, world["managed"])
            assert (top["clicks"], top["url_type"]) == (3, "standard"), who
            assert _top(overview, world["ordinary"])["clicks"] == 1, who
        # Masking changes the destination and nothing else.
        numbers = {who: {k: v for k, v in o.items() if k != "top_urls"} for who, o in seen.items()}
        assert len({str(n) for n in numbers.values()}) == 1
        tops = {
            who: [{k: v for k, v in t.items() if k != "original_url"} for t in o["top_urls"]]
            for who, o in seen.items()
        }
        assert len({str(t) for t in tops.values()}) == 1

    def test_with_bots_the_bots_visit_counts_too(self, client, world):
        response = client.get(
            OVERVIEW, params={"include_bots": True}, headers=_session(world["bob"])
        )
        assert response.status_code == 200, response.text
        assert response.json()["total_clicks"] == 5
        assert _top(response.json(), world["managed"]) == {
            **_top(response.json(), world["managed"]),
            "original_url": MASK,
            "clicks": 4,
        }


def _campaign_link(db_session, world) -> URL:
    """A campaign link the service account made: a campaign link, not managed."""
    url = URL(
        short_code="camp01",
        original_url="https://propuestas.griddo.io/campaign?t=open",
        url_type=URLType.CAMPAIGN,
        created_by=world["ana"].id,
        organization_id=org_service.get_or_create_default_organization(db_session).id,
        via_service_account_id=world["manager"].id,
        domain_id=get_or_create_default_domain(db_session).id,
    )
    db_session.add(url)
    db_session.commit()
    return url


class TestServiceAccountLinks:
    def _links(self, client, world, who: str) -> dict:
        response = client.get(f"{BASE}/{world['account_id']}/links", headers=_session(world[who]))
        assert response.status_code == 200, response.text
        return {item["short_code"]: item for item in response.json()["urls"]}

    def test_the_owner_reads_the_destination(self, client, world):
        links = self._links(client, world, "owner")
        assert links[world["managed"].short_code]["original_url"] == SECRET

    def test_an_admin_gets_the_mask(self, client, world):
        links = self._links(client, world, "admin")
        found = links[world["managed"].short_code]
        assert found["original_url"] == MASK
        assert found["click_count"] == 3  # the numbers aren't masked
        assert "s3cr3t" not in str(links)

    def test_a_campaign_link_it_made_isnt_masked(self, client, world, db_session):
        campaign_link = _campaign_link(db_session, world)
        links = self._links(client, world, "admin")
        assert links["camp01"]["original_url"] == campaign_link.original_url
        assert links[world["managed"].short_code]["original_url"] == MASK

    @pytest.mark.parametrize("who", ["bob", "ana"])
    def test_members_still_cant_list_them(self, client, world, who):
        response = client.get(f"{BASE}/{world['account_id']}/links", headers=_session(world[who]))
        assert response.status_code == 403
        assert "s3cr3t" not in response.text

    def test_the_service_account_itself_cant_list_them(self, client, world):
        response = client.get(
            f"{BASE}/{world['account_id']}/links", headers=_bearer(world["token"])
        )
        assert response.status_code in (401, 403)
        assert "s3cr3t" not in response.text


@pytest.fixture
def curated():
    pytest.importorskip("fastmcp")
    from mcp_server import curated

    return curated


class TestCuratedAnalyticsSummary:
    @pytest.mark.parametrize("who", MASKED)
    def test_masked(self, curated, db_session, world, who):
        result = curated.get_url_analytics_summary(
            db_session, world[who], short_code=world["managed"].short_code
        )
        assert result["original_url"] == MASK
        assert "s3cr3t" not in str(result)
        assert result["totals"]["clicks"] == 3

    @pytest.mark.parametrize("who", SEES)
    def test_the_owner_and_the_manager_read_it(self, curated, db_session, world, who):
        result = curated.get_url_analytics_summary(
            db_session, world[who], short_code=world["managed"].short_code
        )
        assert result["original_url"] == SECRET
        assert result["totals"]["clicks"] == 3

    def test_the_numbers_are_the_same_for_everyone(self, curated, db_session, world):
        seen = [
            curated.get_url_analytics_summary(
                db_session, world[who], short_code=world["managed"].short_code, include_bots=True
            )
            for who in MASKED + SEES
        ]
        assert {result["totals"]["clicks"] for result in seen} == {4}
        without = [{k: v for k, v in r.items() if k != "original_url"} for r in seen]
        assert all(result == without[0] for result in without)

    def test_an_ordinary_link_isnt_masked(self, curated, db_session, world):
        result = curated.get_url_analytics_summary(
            db_session, world["bob"], short_code=world["ordinary"].short_code
        )
        assert result["original_url"] == ORDINARY


class TestCuratedAddRedirectRule:
    def _add(self, curated, db_session, user, url: URL):
        return curated.add_redirect_rule(
            db_session,
            user,
            short_code=url.short_code,
            target_url="https://example.com/mobile",
            device="mobile",
        )

    @pytest.mark.parametrize("who", ["bob", "ana", "admin", "owner"])
    def test_people_get_the_managed_message(self, curated, db_session, world, who):
        with pytest.raises(PermissionError) as refused:
            self._add(curated, db_session, world[who], world["managed"])
        assert str(refused.value) == PROTECTED
        assert not world["managed"].redirect_rules

    def test_the_manager_adds_it(self, curated, db_session, world):
        result = self._add(curated, db_session, world["manager"], world["managed"])
        assert result["target_url"] == "https://example.com/mobile"
        assert result["conditions"] == [{"type": "device", "value": "mobile"}]

    def test_an_ordinary_link_keeps_its_message(self, curated, db_session, world):
        with pytest.raises(PermissionError) as refused:
            self._add(curated, db_session, world["bob"], world["ordinary"])
        assert str(refused.value) == "Only its creator, or an admin or owner, can change this link."
        assert self._add(curated, db_session, world["ana"], world["ordinary"])["id"]
