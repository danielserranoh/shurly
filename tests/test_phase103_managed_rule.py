"""
Phase 10.3 — the managed-link rule (server/utils/managed.py, server/utils/access.py).

A link made through a service account is managed by it: only that account changes it, people
change its tags as before, and only the account and the organization's owners read its
destination. A campaign link a service account made isn't managed. These are the rule's unit
tests, role by role; the routes are tests/test_phase103_managed_api.py.
"""

from __future__ import annotations

import uuid

import pytest
from fastapi import HTTPException

from server.core.models import URL, OrgRole, User
from server.core.models.url import URLType
from server.utils import managed
from server.utils import organization as org_service
from server.utils.access import viewer, visible_url_or_404
from server.utils.domain import get_or_create_default_domain
from server.utils.errors import MANAGED_LINK_PROTECTED, CodedHTTPException
from tests.test_phase101_service_accounts import (
    BASE,
    _create_account,
    _for_ana,
    _issue,
    _make_link,
    _person,
    _session,
)

SECRET = "https://propuestas.griddo.io/p/abc?t=s3cr3t"


@pytest.fixture
def team(db_session):
    return {
        "owner": _person(db_session, "owner@griddo.io", OrgRole.OWNER, "Olga", "Owner"),
        "admin": _person(db_session, "admin@griddo.io", OrgRole.ADMIN),
        "ana": _person(db_session, "ana.garcia@griddo.io", OrgRole.MEMBER, "Ana", "García"),
        "bob": _person(db_session, "bob@griddo.io", OrgRole.MEMBER),
    }


def _account(client, db_session, team, name: str, role: str = "member") -> tuple[User, str]:
    account = _create_account(client, team, role=role, name=name)
    token = _issue(client, team, account["id"])["token"]
    return db_session.get(User, uuid.UUID(account["id"])), token


@pytest.fixture
def world(client, db_session, team):
    """Propuestas (a member service account) made a link for Ana: managed. Ana made one
    herself: ordinary. Two other service accounts, a member and an admin."""
    propuestas, token = _account(client, db_session, team, "Propuestas Griddo")
    other, _ = _account(client, db_session, team, "Another integration")
    other_admin, _ = _account(client, db_session, team, "An admin integration", role="admin")

    made = _make_link(client, _for_ana({"token": token}), url=SECRET)
    assert made.status_code == 201, made.text
    mine = _make_link(client, _session(team["ana"]), url="https://example.com/ana?x=1")
    assert mine.status_code == 201, mine.text

    def link(code: str) -> URL:
        return db_session.query(URL).filter(URL.short_code == code).one()

    return {
        **team,
        "manager": propuestas,
        "other_service": other,
        "other_admin_service": other_admin,
        "token": token,
        "managed": link(made.json()["short_code"]),
        "ordinary": link(mine.json()["short_code"]),
    }


# who: (can_change, can_change_tags, sees_destination) on the managed link, then on the ordinary.
ROLES = {
    "bob": ((False, False, False), (False, False, True)),  # a member
    "ana": ((False, True, False), (True, True, True)),  # the person it was made for / creator
    "admin": ((False, True, False), (True, True, True)),
    "owner": ((False, True, True), (True, True, True)),
    "manager": ((True, True, True), (False, False, True)),
    "other_service": ((False, False, False), (False, False, True)),
    "other_admin_service": ((False, True, False), (True, True, True)),
}


class TestEachRole:
    @pytest.mark.parametrize("who", ROLES)
    @pytest.mark.parametrize("which", ["managed", "ordinary"])
    def test_the_rule(self, world, db_session, who, which):
        expected = ROLES[who][0 if which == "managed" else 1]
        me = viewer(db_session, world[who])
        url = world[which]
        assert (
            me.can_change(url),
            me.can_change_tags(url),
            managed.sees_destination(me, url),
        ) == expected

    def test_which_is_managed(self, world):
        assert managed.is_managed(world["managed"])
        assert managed.manager_id(world["managed"]) == world["manager"].id
        assert world["managed"].created_by == world["ana"].id  # made for Ana
        assert not managed.is_managed(world["ordinary"])
        assert managed.manager_id(world["ordinary"]) is None

    @pytest.mark.parametrize("who", ["bob", "ana", "admin", "owner", "other_service"])
    def test_anyone_but_the_manager_gets_managed_link_protected(self, world, db_session, who):
        me = viewer(db_session, world[who])
        with pytest.raises(CodedHTTPException) as refused:
            me.ensure_can_change(world["managed"])
        assert refused.value.status_code == 403
        assert refused.value.code == MANAGED_LINK_PROTECTED
        assert refused.value.detail == (
            "This link is managed by Propuestas Griddo. Change or delete it from there."
        )

    def test_the_manager_passes(self, world, db_session):
        me = viewer(db_session, world["manager"])
        me.ensure_can_change(world["managed"])
        me.ensure_can_change_tags(world["managed"])
        managed.ensure_may_change(me, world["managed"])

    def test_an_ordinary_link_keeps_its_plain_403(self, world, db_session):
        me = viewer(db_session, world["bob"])
        for check in (me.ensure_can_change, me.ensure_can_change_tags):
            with pytest.raises(HTTPException) as refused:
                check(world["ordinary"])
            assert refused.value.status_code == 403
            assert not isinstance(refused.value, CodedHTTPException)
            assert (
                refused.value.detail
                == "Only its creator, or an admin or owner, can change this link."
            )
        managed.ensure_may_change(me, world["ordinary"])  # not managed: nothing to say

    def test_people_who_cant_tag_get_the_plain_403_on_a_managed_link(self, world, db_session):
        me = viewer(db_session, world["bob"])
        with pytest.raises(HTTPException) as refused:
            me.ensure_can_change_tags(world["managed"])
        assert refused.value.status_code == 403
        assert not isinstance(refused.value, CodedHTTPException)


class TestVisibleUrlOr404:
    def test_to_change_true_is_the_locked_path(self, world, db_session):
        code = world["managed"].short_code
        with pytest.raises(CodedHTTPException) as refused:
            visible_url_or_404(db_session, world["owner"], code, to_change=True)
        assert refused.value.code == MANAGED_LINK_PROTECTED
        found = visible_url_or_404(db_session, world["manager"], code, to_change=True)
        assert found.id == world["managed"].id

    def test_to_change_tags_is_the_tags_path(self, world, db_session):
        code = world["managed"].short_code
        for who in ("owner", "admin", "ana", "manager"):
            found = visible_url_or_404(db_session, world[who], code, to_change="tags")
            assert found.id == world["managed"].id
        with pytest.raises(HTTPException) as refused:
            visible_url_or_404(db_session, world["bob"], code, to_change="tags")
        assert refused.value.status_code == 403

    def test_reading_needs_nothing_more(self, world, db_session):
        code = world["managed"].short_code
        assert visible_url_or_404(db_session, world["bob"], code).id == world["managed"].id

    def test_an_ordinary_link_is_as_before(self, world, db_session):
        code = world["ordinary"].short_code
        for to_change in (True, "tags"):
            assert visible_url_or_404(db_session, world["admin"], code, to_change=to_change)
            with pytest.raises(HTTPException) as refused:
                visible_url_or_404(db_session, world["bob"], code, to_change=to_change)
            assert refused.value.status_code == 403


class TestRemovedManager:
    def test_its_links_stay_managed_and_protected(self, client, world, db_session):
        account = world["manager"]
        removed = client.delete(f"{BASE}/{account.id}", headers=_session(world["owner"]))
        assert removed.status_code == 204, removed.text
        db_session.expire_all()
        url = world["managed"]
        assert db_session.get(User, account.id).is_active is False

        assert managed.is_managed(url)
        assert managed.manager_id(url) == account.id
        for who in ("owner", "admin", "ana", "bob"):
            assert not viewer(db_session, world[who]).can_change(url), who
        assert managed.sees_destination(viewer(db_session, world["owner"]), url)
        assert not managed.sees_destination(viewer(db_session, world["admin"]), url)
        with pytest.raises(CodedHTTPException) as refused:
            viewer(db_session, world["owner"]).ensure_can_change(url)
        assert "Propuestas Griddo" in refused.value.detail
        # Tags, as before: the person it was made for, admins, owners.
        assert viewer(db_session, world["ana"]).can_change_tags(url)
        # Still its manager by id: it can't sign in any more (its tokens are revoked).
        assert managed.is_manager(viewer(db_session, account), url)


class TestCampaignLinks:
    def test_a_campaign_link_a_service_account_made_isnt_managed(self, world, db_session):
        organization = org_service.get_or_create_default_organization(db_session)
        url = URL(
            short_code="camp01",
            original_url=SECRET,
            url_type=URLType.CAMPAIGN,
            created_by=world["ana"].id,
            organization_id=organization.id,
            via_service_account_id=world["manager"].id,
            domain_id=get_or_create_default_domain(db_session).id,
        )
        db_session.add(url)
        db_session.commit()

        assert not managed.is_managed(url)
        assert managed.manager_id(url) is None
        admin = viewer(db_session, world["admin"])
        assert admin.can_change(url) and admin.can_change_tags(url)
        assert managed.sees_destination(viewer(db_session, world["bob"]), url)
        managed.ensure_may_change(viewer(db_session, world["bob"]), url)

        managed_ids = {u.id for u in db_session.query(URL).filter(managed.managed_clause())}
        unmanaged_ids = {u.id for u in db_session.query(URL).filter(managed.not_managed_clause())}
        assert managed_ids == {world["managed"].id}
        assert unmanaged_ids == {world["ordinary"].id, url.id}

    def test_campaigns_themselves_are_never_managed(self):
        class Campaign:  # no via_service_account_id, no url_type
            created_by = None

        assert not managed.is_managed(Campaign())


class TestDestination:
    def test_destination_for(self, world, db_session):
        url = world["managed"]
        assert managed.destination_for(viewer(db_session, world["owner"]), url) == SECRET
        assert managed.destination_for(viewer(db_session, world["manager"]), url) == SECRET
        for who in ("admin", "ana", "bob", "other_service"):
            shown = managed.destination_for(viewer(db_session, world[who]), url)
            assert shown == "https://propuestas.griddo.io/…", who
        ordinary = world["ordinary"]
        bob = viewer(db_session, world["bob"])
        assert managed.destination_for(bob, ordinary) == ordinary.original_url

    def test_an_owner_of_another_organization_doesnt_see_it(self, world, db_session):
        from server.utils.access import Viewer

        stranger = Viewer(user=world["bob"], organization_id=uuid.uuid4(), role=OrgRole.OWNER)
        assert not managed.sees_destination(stranger, world["managed"])
        nobody = Viewer(user=world["bob"], organization_id=None, role=None)
        assert not managed.sees_destination(nobody, world["managed"])


class TestMessage:
    def test_without_the_account_loaded_a_generic_phrase(self):
        url = URL(via_service_account_id=uuid.uuid4(), url_type=URLType.STANDARD)
        assert managed.protected_message(url) == (
            "This link is managed by the integration that made it (a service account). "
            "Change or delete it from there."
        )
        error = managed.protected_error(url)
        assert (error.status_code, error.code) == (403, MANAGED_LINK_PROTECTED)


class TestMasked:
    @pytest.mark.parametrize(
        ("destination", "expected"),
        [
            ("https://propuestas.griddo.io/p/abc?t=x", "https://propuestas.griddo.io/…"),
            ("https://propuestas.griddo.io", "https://propuestas.griddo.io/…"),
            ("https://propuestas.griddo.io/", "https://propuestas.griddo.io/…"),
            ("https://propuestas.griddo.io/…", "https://propuestas.griddo.io/…"),  # idempotent
            ("http://localhost:8000/x#frag", "http://localhost:8000/…"),
            ("HTTPS://Propuestas.Griddo.IO/P", "https://propuestas.griddo.io/…"),
            ("https://user:pass@host.example/x", "https://host.example/…"),  # no credentials
            ("https://[2001:db8::1]:8443/x", "https://[2001:db8::1]:8443/…"),
            ("https://example.com?q=1", "https://example.com/…"),
            ("https://example.com:99999/x", "…"),  # a port out of range
            ("https://example.com:abc/x", "…"),
            ("propuestas.griddo.io/p/abc", "…"),  # no scheme
            ("/p/abc?t=x", "…"),
            ("mailto:ana@griddo.io", "…"),
            ("", "…"),
            ("…", "…"),
            ("not a url", "…"),
            (None, "…"),
            (42, "…"),
            (b"https://example.com/x", "…"),
        ],
    )
    def test_masked(self, destination, expected):
        assert managed.masked(destination) == expected
