"""
Phase 10.2 — service accounts v2, the data model (`_board/plan_sa-v2-scopes-audit.md`, T2).

- A token's `scopes` default to every scope, in Python and in the database, so the tokens in use
  before v2 keep doing what they did.
- `allowed_ip_ranges` is NULL (any address) unless set.
- `audit_events` keeps ids, without foreign keys: its rows outlive the account, token or person
  they name.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import inspect, text
from sqlalchemy.orm import Session

from server.core.models import AuditEvent, ServiceToken, User
from server.core.models.service_token import SERVICE_SCOPES, every_scope


def _service_account(db: Session) -> User:
    account = User(
        email=f"svc-{uuid.uuid4().hex[:8]}@service.invalid",
        password_hash="!",
        is_active=True,
        kind="service",
        display_name="Propuestas Griddo",
    )
    db.add(account)
    db.flush()
    return account


def _token(db: Session, account: User, **fields) -> ServiceToken:
    token = ServiceToken(
        service_account_id=account.id,
        prefix=uuid.uuid4().hex[:8],
        token_hash=uuid.uuid4().hex + uuid.uuid4().hex,
        **fields,
    )
    db.add(token)
    db.commit()
    db.expire_all()
    return db.get(ServiceToken, token.id)


class TestServiceTokenScopes:
    def test_the_scopes(self):
        assert SERVICE_SCOPES == (
            "urls:read",
            "urls:write",
            "urls:delete",
            "tags:write",
            "analytics:read",
            "act_on_behalf",
        )

    def test_a_new_token_gets_every_scope(self, db_session: Session):
        token = _token(db_session, _service_account(db_session))

        assert token.scopes == list(SERVICE_SCOPES)
        assert token.allowed_ip_ranges is None

    def test_each_token_gets_its_own_list(self):
        mine = every_scope()
        mine.remove("urls:delete")

        assert every_scope() == list(SERVICE_SCOPES)

    def test_a_row_written_without_scopes_gets_every_scope_from_the_database(
        self, db_session: Session
    ):
        """As the tokens made before 0019, or by the previous release during the rollout."""
        account = _service_account(db_session)
        token_id = uuid.uuid4()
        db_session.execute(
            text(
                "INSERT INTO service_tokens (id, service_account_id, prefix, token_hash, created_at)"
                " VALUES (:id, :account, 'abcd1234', :hash, :now)"
            ),
            {
                "id": token_id.hex,
                "account": account.id.hex,
                "hash": uuid.uuid4().hex * 2,
                "now": datetime.utcnow(),
            },
        )
        db_session.commit()

        assert db_session.get(ServiceToken, token_id).scopes == list(SERVICE_SCOPES)

    def test_scopes_and_ranges_round_trip(self, db_session: Session):
        token = _token(
            db_session,
            _service_account(db_session),
            scopes=["urls:read", "analytics:read"],
            allowed_ip_ranges=["203.0.113.0/24", "2001:db8::/32"],
        )

        assert token.scopes == ["urls:read", "analytics:read"]
        assert token.allowed_ip_ranges == ["203.0.113.0/24", "2001:db8::/32"]


class TestAuditEvent:
    def test_round_trip(self, db_session: Session):
        organization_id, account_id, token_id, person_id = (uuid.uuid4() for _ in range(4))
        event = AuditEvent(
            organization_id=organization_id,
            service_account_id=account_id,
            token_id=token_id,
            on_behalf_of_id=person_id,
            action="url.updated",
            target_type="url",
            target_id="abc123",
            detail={"fields": ["title", "tags"]},
        )
        db_session.add(event)
        db_session.commit()
        db_session.expire_all()

        kept = db_session.get(AuditEvent, event.id)
        assert kept.at is not None and kept.at <= datetime.utcnow()
        assert kept.organization_id == organization_id
        assert kept.service_account_id == account_id
        assert kept.token_id == token_id
        assert kept.actor_id is None
        assert kept.on_behalf_of_id == person_id
        assert (kept.action, kept.target_type, kept.target_id) == ("url.updated", "url", "abc123")
        assert kept.detail == {"fields": ["title", "tags"]}

    def test_an_account_event_has_no_token_and_names_who_made_it(self, db_session: Session):
        owner_id = uuid.uuid4()
        event = AuditEvent(
            organization_id=uuid.uuid4(),
            service_account_id=uuid.uuid4(),
            actor_id=owner_id,
            action="service_account.created",
            target_type="service_account",
        )
        db_session.add(event)
        db_session.commit()
        db_session.expire_all()

        kept = db_session.get(AuditEvent, event.id)
        assert kept.actor_id == owner_id
        assert kept.token_id is None and kept.on_behalf_of_id is None
        assert kept.target_id is None and kept.detail is None

    def test_no_foreign_keys_so_rows_outlive_what_they_name(self):
        assert AuditEvent.__table__.foreign_keys == set()

    def test_indexes(self, db_session: Session):
        indexes = {
            tuple(index["column_names"])
            for index in inspect(db_session.get_bind()).get_indexes("audit_events")
        }

        assert ("organization_id", "at") in indexes
        assert ("service_account_id",) in indexes
