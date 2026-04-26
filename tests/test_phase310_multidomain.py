"""Phase 3.10.1 — multi-domain foundation."""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from server.core.models import URL, Domain, User
from server.core.models.url import URLType
from server.utils.domain import get_or_create_default_domain, resolve_domain_for_host


class TestDomainHelpers:
    def test_get_or_create_default_domain_is_idempotent(self, db_session: Session):
        a = get_or_create_default_domain(db_session)
        b = get_or_create_default_domain(db_session)
        assert a.id == b.id
        assert a.is_default is True
        assert (
            db_session.query(Domain).filter(Domain.is_default.is_(True)).count() == 1
        )

    def test_resolve_domain_strips_port(self, db_session: Session):
        get_or_create_default_domain(db_session)
        d = resolve_domain_for_host(db_session, "shurl.griddo.io:8000")
        assert d.hostname == "shurl.griddo.io"

    def test_resolve_unknown_host_falls_back_to_default(self, db_session: Session):
        d = resolve_domain_for_host(db_session, "vanity.example.com")
        assert d.is_default is True


@pytest.mark.integration
class TestMultiDomainUniqueness:
    def test_same_code_on_different_domains_allowed(
        self, db_session: Session, test_user: User
    ):
        default = get_or_create_default_domain(db_session)
        other = Domain(hostname="alt.example.com", is_default=False)
        db_session.add(other)
        db_session.commit()
        db_session.refresh(other)

        db_session.add(
            URL(
                short_code="abc123",
                domain_id=default.id,
                original_url="https://a",
                url_type=URLType.STANDARD,
                created_by=test_user.id,
            )
        )
        db_session.add(
            URL(
                short_code="abc123",
                domain_id=other.id,
                original_url="https://b",
                url_type=URLType.STANDARD,
                created_by=test_user.id,
            )
        )
        db_session.commit()  # must not raise

        rows = db_session.query(URL).filter(URL.short_code == "abc123").all()
        assert len(rows) == 2
        assert {row.domain_id for row in rows} == {default.id, other.id}

    def test_same_code_same_domain_violates_unique(
        self, db_session: Session, test_user: User
    ):
        default = get_or_create_default_domain(db_session)
        db_session.add(
            URL(
                short_code="dup1",
                domain_id=default.id,
                original_url="https://a",
                url_type=URLType.STANDARD,
                created_by=test_user.id,
            )
        )
        db_session.commit()

        db_session.add(
            URL(
                short_code="dup1",
                domain_id=default.id,
                original_url="https://b",
                url_type=URLType.STANDARD,
                created_by=test_user.id,
            )
        )
        with pytest.raises(IntegrityError):
            db_session.commit()
        db_session.rollback()


@pytest.mark.integration
class TestRedirectByDomain:
    def test_redirect_uses_host_to_pick_domain(
        self, client: TestClient, db_session: Session, test_user: User
    ):
        default = get_or_create_default_domain(db_session)
        other = Domain(hostname="alt.example.com", is_default=False)
        db_session.add(other)
        db_session.commit()
        db_session.refresh(other)

        # Same code on two domains, different destinations
        db_session.add_all([
            URL(
                short_code="hop",
                domain_id=default.id,
                original_url="https://default-target.example",
                url_type=URLType.STANDARD,
                created_by=test_user.id,
            ),
            URL(
                short_code="hop",
                domain_id=other.id,
                original_url="https://alt-target.example",
                url_type=URLType.STANDARD,
                created_by=test_user.id,
            ),
        ])
        db_session.commit()

        r1 = client.get(
            "/hop",
            headers={"Host": "shurl.griddo.io"},
            follow_redirects=False,
        )
        assert r1.status_code == 302
        assert r1.headers["location"] == "https://default-target.example"

        r2 = client.get(
            "/hop",
            headers={"Host": "alt.example.com"},
            follow_redirects=False,
        )
        assert r2.status_code == 302
        assert r2.headers["location"] == "https://alt-target.example"

    def test_unknown_host_falls_back_to_default_domain(
        self, client: TestClient, db_session: Session, test_user: User
    ):
        default = get_or_create_default_domain(db_session)
        db_session.add(
            URL(
                short_code="onlyone",
                domain_id=default.id,
                original_url="https://default-target.example",
                url_type=URLType.STANDARD,
                created_by=test_user.id,
            )
        )
        db_session.commit()

        r = client.get(
            "/onlyone",
            headers={"Host": "unknown.example.com"},
            follow_redirects=False,
        )
        assert r.status_code == 302
        assert r.headers["location"] == "https://default-target.example"
