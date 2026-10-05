"""
Phase 9.1 — the waitlist: people outside Griddo, who can't sign in, say they're interested.

- `POST /api/v1/waitlist` is public: no account. It validates every field, needs consent to be
  contacted, and is limited per client IP. A filled honeypot answers as a sign-up does and stores
  nothing. The same email again updates its entry, and the answer never says whether the email
  was already listed. Nothing personal is echoed back, and the IP is never stored.
- The organization's owners and admins read the list (`GET`), with counts by kind and by company
  size, export it as a CSV, and remove an entry when its person asks. A member gets a 403.
- `waitlist.joined` is logged with the kind and the company size only.
"""

from __future__ import annotations

import csv
import io
import json
import time
import uuid
from datetime import datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from main import app
from server.core.auth import create_access_token, hash_password
from server.core.config import settings
from server.core.models import OrganizationMember, OrgRole, User, WaitlistEntry
from server.utils import organization as org_service
from server.utils import rate_limit

URL = "/api/v1/waitlist"
_PASSWORD_HASH = hash_password("secret123")


def _join(client, **overrides):
    body = {
        "email": "Ada@Example.com",
        "name": "Ada Lovelace",
        "kind": "individual",
        "consent": True,
    }
    body.update(overrides)
    body = {key: value for key, value in body.items() if value is not ...}
    return client.post(URL, json=body)


def _company(**overrides):
    body = {
        "email": "grace@acme.example",
        "name": "Grace Hopper",
        "kind": "company",
        "company": "Acme",
        "company_size": "51-200",
        "role": "Head of marketing",
        "use_case": "Tracking proposals we send to universities.",
        "source": "A colleague or friend",
        "consent": True,
    }
    body.update(overrides)
    return body


def _entries(db):
    db.expire_all()
    return db.query(WaitlistEntry).all()


def _events(stderr: str, event: str) -> list[dict]:
    found = []
    for line in stderr.splitlines():
        try:
            record = json.loads(line)
        except ValueError:
            continue
        if isinstance(record, dict) and record.get("event") == event:
            found.append(record)
    return found


def _person(db, email: str, role: OrgRole | None) -> User:
    user = User(email=email, password_hash=_PASSWORD_HASH, is_active=True)
    db.add(user)
    db.flush()
    if role is not None:
        organization = org_service.get_or_create_default_organization(db)
        db.add(OrganizationMember(organization_id=organization.id, user_id=user.id, role=role))
    db.commit()
    return user


def _as(user: User) -> dict:
    return {"Authorization": f"Bearer {create_access_token(data={'sub': user.email})}"}


@pytest.fixture
def team(db_session):
    return {
        "owner": _person(db_session, "owner@griddo.io", OrgRole.OWNER),
        "admin": _person(db_session, "admin@griddo.io", OrgRole.ADMIN),
        "member": _person(db_session, "member@griddo.io", OrgRole.MEMBER),
        "outsider": _person(db_session, "someone@elsewhere.example", None),
    }


# ---------------------------------------------------------------- Joining


class TestJoin:
    def test_an_individual_joins_without_an_account(self, client, db_session):
        response = _join(client)

        assert response.status_code == 201
        [entry] = _entries(db_session)
        assert entry.email == "ada@example.com"  # normalized
        assert entry.name == "Ada Lovelace"
        assert entry.kind == "individual"
        assert entry.company is None and entry.company_size is None
        assert entry.consent_at is not None and entry.created_at is not None

    def test_a_company_keeps_its_answers(self, client, db_session):
        response = client.post(URL, json=_company())

        assert response.status_code == 201
        [entry] = _entries(db_session)
        assert (entry.kind, entry.company, entry.company_size) == ("company", "Acme", "51-200")
        assert entry.role == "Head of marketing"
        assert entry.use_case == "Tracking proposals we send to universities."
        assert entry.source == "A colleague or friend"

    def test_the_answer_echoes_nothing_personal(self, client):
        response = client.post(URL, json=_company())

        text = response.text.lower()
        assert "grace" not in text and "acme" not in text and "@" not in text

    def test_whitespace_is_trimmed_and_blank_optionals_are_none(self, client, db_session):
        _join(client, email="  ada@example.com ", name="  Ada  ", role="   ", source="")

        [entry] = _entries(db_session)
        assert (entry.email, entry.name, entry.role, entry.source) == (
            "ada@example.com",
            "Ada",
            None,
            None,
        )

    def test_an_individual_has_no_company(self, client, db_session):
        _join(client, company="Acme", company_size="1-10")

        [entry] = _entries(db_session)
        assert entry.company is None and entry.company_size is None

    def test_a_company_may_leave_its_size_out(self, client, db_session):
        assert client.post(URL, json=_company(company_size=None)).status_code == 201
        assert _entries(db_session)[0].company_size is None

    def test_the_ip_is_never_stored(self, client, db_session):
        _join(client)
        [entry] = _entries(db_session)
        columns = {column.name for column in WaitlistEntry.__table__.columns}
        assert not {"ip", "ip_address", "remote_addr"} & columns
        assert "testclient" not in json.dumps(
            {column: str(getattr(entry, column)) for column in columns}
        )


class TestValidation:
    @pytest.mark.parametrize(
        ("overrides", "field"),
        [
            ({"email": "not-an-email"}, "email"),
            ({"email": ...}, "email"),
            ({"name": ...}, "name"),
            ({"name": "   "}, "name"),
            ({"name": "n" * 201}, "name"),
            ({"kind": "government"}, "kind"),
            ({"kind": ...}, "kind"),
            ({"consent": False}, "consent"),
            ({"consent": ...}, "consent"),
            ({"role": "r" * 121}, "role"),
            ({"use_case": "u" * 1001}, "use_case"),
            ({"source": "s" * 101}, "source"),
        ],
    )
    def test_a_bad_field_is_a_422_on_that_field(self, client, db_session, overrides, field):
        response = _join(client, **overrides)

        assert response.status_code == 422
        assert field in {issue["loc"][-1] for issue in response.json()["detail"]}
        assert _entries(db_session) == []

    def test_a_company_needs_its_name(self, client, db_session):
        response = client.post(URL, json=_company(company="  "))

        assert response.status_code == 422
        assert "company" in {issue["loc"][-1] for issue in response.json()["detail"]}
        assert _entries(db_session) == []

    def test_a_company_size_is_one_of_the_list(self, client):
        response = client.post(URL, json=_company(company_size="huge"))

        assert response.status_code == 422
        assert "company_size" in {issue["loc"][-1] for issue in response.json()["detail"]}

    def test_an_email_longer_than_its_column_is_refused(self, client):
        response = _join(client, email=f"{'a' * 64}@{'b' * 250}.com")
        assert response.status_code == 422


class TestHoneypot:
    def test_a_filled_honeypot_answers_success_and_stores_nothing(self, client, db_session):
        joined = _join(client, email="real@example.com")
        trapped = _join(client, email="bot@example.com", website="https://spam.example")

        assert trapped.status_code == joined.status_code == 201
        assert trapped.json() == joined.json()
        assert [entry.email for entry in _entries(db_session)] == ["real@example.com"]

    def test_an_empty_honeypot_is_a_person(self, client, db_session):
        assert _join(client, website="").status_code == 201
        assert len(_entries(db_session)) == 1


class TestTheSameEmailAgain:
    def test_it_updates_the_entry_and_answers_the_same(self, client, db_session):
        first = _join(client, email="ada@example.com")
        [before] = _entries(db_session)
        created_at = before.created_at

        again = client.post(URL, json=_company(email="ADA@example.com", name="Ada L."))

        assert again.status_code == first.status_code == 201
        assert again.json() == first.json()
        [entry] = _entries(db_session)
        assert entry.name == "Ada L."
        assert (entry.kind, entry.company) == ("company", "Acme")
        assert entry.created_at == created_at
        assert entry.updated_at is not None

    def test_two_sign_ups_at_once_leave_one_entry(self, client, db_session, monkeypatch):
        """The other one committed between this one's lookup and its insert: it updates that one."""
        from server.app import waitlist
        from server.schemas.waitlist import WaitlistJoin

        _join(client, email="ada@example.com")
        real_query = db_session.query
        missed = []

        def query_missing_once(*args):
            result = real_query(*args)
            if not missed:
                missed.append(True)
                return result.filter(False)
            return result

        real_rollback, rollbacks = db_session.rollback, []
        monkeypatch.setattr(db_session, "query", query_missing_once)
        monkeypatch.setattr(db_session, "rollback", lambda: rollbacks.append(1) or real_rollback())
        waitlist._save(
            db_session,
            WaitlistJoin(
                email="ada@example.com", name="Ada again", kind="individual", consent=True
            ),
        )
        monkeypatch.undo()

        assert rollbacks == [1]  # its insert was refused, as the email was there
        [entry] = _entries(db_session)
        assert entry.name == "Ada again"


class TestEventLog:
    def test_joining_logs_the_kind_and_the_size_only(self, client, capfd):
        client.post(URL, json=_company())

        err = capfd.readouterr().err
        [event] = _events(err, "waitlist.joined")
        assert event["kind"] == "company"
        assert event["company_size"] == "51-200"
        assert set(event) == {"ts", "event", "kind", "company_size"}
        for line in err.splitlines():
            assert "grace" not in line.lower() and "acme" not in line.lower()

    def test_a_honeypot_hit_logs_no_joining(self, client, capfd):
        _join(client, website="spam")

        err = capfd.readouterr().err
        assert _events(err, "waitlist.joined") == []
        assert len(_events(err, "waitlist.honeypot")) == 1


class TestRateLimit:
    @pytest.fixture(autouse=True)
    def frozen_clock(self, monkeypatch):
        now = time.time() // 3600 * 3600 + 1
        monkeypatch.setattr(rate_limit, "_now", lambda: now)

    def _from(self, ip: str) -> TestClient:
        return TestClient(app, client=(ip, 50000))

    def test_the_sign_up_over_the_limit_is_refused(self, client, db_session, monkeypatch):
        monkeypatch.setattr(settings, "rate_limit_waitlist_per_ip", 2)
        ana = self._from("203.0.113.7")
        for i in range(2):
            assert _join(ana, email=f"n{i}@example.com").status_code == 201

        refused = _join(ana, email="n9@example.com")

        assert refused.status_code == 429
        assert 0 < int(refused.headers["retry-after"]) <= 3600
        assert len(_entries(db_session)) == 2

    def test_another_address_has_its_own_count(self, client, monkeypatch):
        monkeypatch.setattr(settings, "rate_limit_waitlist_per_ip", 1)
        assert _join(self._from("203.0.113.7")).status_code == 201
        assert _join(self._from("203.0.113.7"), email="b@example.com").status_code == 429
        assert _join(self._from("198.51.100.4"), email="c@example.com").status_code == 201

    def test_the_default_is_ten_an_hour(self):
        assert settings.rate_limit_waitlist_per_ip == 10
        assert rate_limit.WAITLIST_PER_IP.window == 3600


def test_a_browser_on_an_allowed_origin_may_post_without_signing_in(client, monkeypatch):
    origin = settings.cors_origins[0]
    preflight = client.options(
        URL,
        headers={
            "Origin": origin,
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "content-type",
        },
    )
    assert preflight.status_code == 200
    assert preflight.headers["access-control-allow-origin"] == origin

    response = client.post(
        URL,
        json={"email": "a@example.com", "name": "A", "kind": "individual", "consent": True},
        headers={"Origin": origin},
    )
    assert response.status_code == 201
    assert response.headers["access-control-allow-origin"] == origin


# ---------------------------------------------------------------- Reading the list


def _seed(db, count: int = 3):
    """Entries of each kind, a minute apart, newest last."""
    start = datetime.utcnow() - timedelta(hours=1)
    rows = [
        ("ind1@example.com", "individual", None, None),
        ("co1@example.com", "company", "Acme", "1-10"),
        ("co2@example.com", "company", "Bolt", "1-10"),
        ("co3@example.com", "company", "Corp", "1000+"),
        ("co4@example.com", "company", "Dyn", None),
        ("ind2@example.com", "individual", None, None),
    ]
    for i, (email, kind, company, size) in enumerate(rows):
        at = start + timedelta(minutes=i)
        db.add(
            WaitlistEntry(
                email=email,
                name=email.split("@")[0],
                kind=kind,
                company=company,
                company_size=size,
                consent_at=at,
                created_at=at,
            )
        )
    db.commit()


class TestList:
    @pytest.mark.parametrize("who", ["owner", "admin"])
    def test_owners_and_admins_read_it_newest_first_with_counts(
        self, client, db_session, team, who
    ):
        _seed(db_session)

        response = client.get(URL, headers=_as(team[who]))

        assert response.status_code == 200
        body = response.json()
        assert body["total"] == 6
        assert [entry["email"] for entry in body["entries"]][:2] == [
            "ind2@example.com",
            "co4@example.com",
        ]
        assert body["counts"] == {
            "total": 6,
            "individual": 2,
            "company": 4,
            "by_company_size": {
                "1-10": 2,
                "11-50": 0,
                "51-200": 0,
                "201-1000": 0,
                "1000+": 1,
                "not_given": 1,
            },
        }
        first = body["entries"][0]
        assert set(first) == {
            "id",
            "email",
            "name",
            "kind",
            "company",
            "company_size",
            "role",
            "use_case",
            "source",
            "consent_at",
            "created_at",
            "updated_at",
        }
        assert first["created_at"].endswith("Z")

    def test_it_pages(self, client, db_session, team):
        _seed(db_session)

        response = client.get(f"{URL}?skip=2&limit=2", headers=_as(team["owner"]))

        body = response.json()
        assert body["total"] == 6
        assert [entry["email"] for entry in body["entries"]] == [
            "co3@example.com",
            "co2@example.com",
        ]

    @pytest.mark.parametrize("query", ["limit=0", "limit=201", "skip=-1", "skip=1000000001"])
    def test_out_of_range_paging_is_a_422(self, client, team, query):
        assert client.get(f"{URL}?{query}", headers=_as(team["owner"])).status_code == 422

    @pytest.mark.parametrize("who", ["member", "outsider"])
    def test_anyone_else_signed_in_gets_a_403(self, client, db_session, team, who):
        _seed(db_session)

        response = client.get(URL, headers=_as(team[who]))

        assert response.status_code == 403
        assert "@" not in response.text

    def test_signed_out_is_a_401(self, client):
        assert client.get(URL).status_code == 401


class TestExport:
    def test_owners_get_every_entry_as_a_csv(self, client, db_session, team):
        _seed(db_session)
        db_session.add(
            WaitlistEntry(
                email="eve@example.com",
                name="=HYPERLINK(1)",
                kind="individual",
                consent_at=datetime.utcnow(),
                created_at=datetime.utcnow(),
            )
        )
        db_session.commit()

        response = client.get(f"{URL}/export", headers=_as(team["admin"]))

        assert response.status_code == 200
        assert response.headers["content-type"].startswith("text/csv")
        assert "attachment" in response.headers["content-disposition"]
        rows = list(csv.reader(io.StringIO(response.text)))
        assert rows[0] == [
            "created_at",
            "email",
            "name",
            "kind",
            "company",
            "company_size",
            "role",
            "use_case",
            "source",
            "consent_at",
        ]
        assert len(rows) == 8
        assert rows[1][1] == "eve@example.com"
        assert rows[1][2] == "'=HYPERLINK(1)"  # never a live formula

    def test_a_member_gets_a_403(self, client, team):
        assert client.get(f"{URL}/export", headers=_as(team["member"])).status_code == 403


class TestRemove:
    def test_an_admin_removes_an_entry_when_its_person_asks(self, client, db_session, team, capfd):
        _seed(db_session)
        entry = db_session.query(WaitlistEntry).filter_by(email="co1@example.com").one()

        response = client.delete(f"{URL}/{entry.id}", headers=_as(team["admin"]))

        assert response.status_code == 204
        assert "co1@example.com" not in [e.email for e in _entries(db_session)]
        [event] = _events(capfd.readouterr().err, "waitlist.removed")
        assert event["actor_id"] == str(team["admin"].id)
        assert "co1" not in json.dumps(event)

    def test_an_unknown_entry_is_a_404(self, client, team):
        response = client.delete(f"{URL}/{uuid.uuid4()}", headers=_as(team["owner"]))
        assert response.status_code == 404

    def test_a_member_gets_a_403_and_nothing_goes(self, client, db_session, team):
        _seed(db_session)
        entry = db_session.query(WaitlistEntry).first()

        response = client.delete(f"{URL}/{entry.id}", headers=_as(team["member"]))

        assert response.status_code == 403
        assert len(_entries(db_session)) == 6
