"""Phase 3.10.2 — dynamic redirect rules."""

from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from server.core.models import URL, RedirectRule, User
from server.core.models.url import URLType
from server.utils.domain import get_or_create_default_domain
from server.utils.redirect_rules import pick_target, rule_matches


# ---- Pure-function tests for the matcher ----


class TestEvaluator:
    def _ctx(self, **overrides):
        defaults = dict(
            user_agent=None,
            accept_language=None,
            query_params={},
            now=datetime(2026, 4, 1, tzinfo=timezone.utc),
        )
        defaults.update(overrides)
        return defaults

    def test_device_ios_matches(self):
        assert rule_matches(
            [{"type": "device", "value": "ios"}],
            **self._ctx(user_agent="Mozilla/5.0 (iPhone; CPU iPhone OS 17_0)"),
        )

    def test_device_android_matches(self):
        assert rule_matches(
            [{"type": "device", "value": "android"}],
            **self._ctx(user_agent="Mozilla/5.0 (Linux; Android 14)"),
        )

    def test_device_windows_matches(self):
        assert rule_matches(
            [{"type": "device", "value": "windows"}],
            **self._ctx(user_agent="Mozilla/5.0 (Windows NT 10.0)"),
        )

    def test_device_macos_matches(self):
        assert rule_matches(
            [{"type": "device", "value": "macos"}],
            **self._ctx(user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 14_0)"),
        )

    def test_language_primary_subtag(self):
        assert rule_matches(
            [{"type": "language", "value": "es"}],
            **self._ctx(accept_language="es-ES,es;q=0.9,en;q=0.5"),
        )
        assert not rule_matches(
            [{"type": "language", "value": "fr"}],
            **self._ctx(accept_language="es-ES"),
        )

    def test_query_param_value_match(self):
        assert rule_matches(
            [{"type": "query_param", "param": "src", "value": "newsletter"}],
            **self._ctx(query_params={"src": "newsletter"}),
        )
        assert not rule_matches(
            [{"type": "query_param", "param": "src", "value": "newsletter"}],
            **self._ctx(query_params={"src": "ads"}),
        )

    def test_query_param_presence_only(self):
        assert rule_matches(
            [{"type": "query_param", "param": "debug"}],
            **self._ctx(query_params={"debug": ""}),
        )

    def test_before_date(self):
        assert rule_matches(
            [{"type": "before_date", "value": "2026-05-01T00:00:00Z"}],
            **self._ctx(now=datetime(2026, 4, 30, tzinfo=timezone.utc)),
        )
        assert not rule_matches(
            [{"type": "before_date", "value": "2026-04-01T00:00:00Z"}],
            **self._ctx(now=datetime(2026, 4, 30, tzinfo=timezone.utc)),
        )

    def test_after_date(self):
        assert rule_matches(
            [{"type": "after_date", "value": "2026-04-01T00:00:00Z"}],
            **self._ctx(now=datetime(2026, 4, 1, tzinfo=timezone.utc)),
        )

    def test_browser_match(self):
        assert rule_matches(
            [{"type": "browser", "value": "Chrome"}],
            **self._ctx(
                user_agent=(
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 Chrome/120.0.0.0 Safari/537.36"
                )
            ),
        )

    def test_unknown_type_fails_closed(self):
        assert not rule_matches(
            [{"type": "supernova", "value": "yes"}],
            **self._ctx(),
        )

    def test_and_semantics(self):
        # Both must match
        assert rule_matches(
            [
                {"type": "device", "value": "ios"},
                {"type": "language", "value": "en"},
            ],
            **self._ctx(
                user_agent="Mozilla/5.0 (iPhone; CPU iPhone OS 17_0)",
                accept_language="en-US,en;q=0.9",
            ),
        )
        assert not rule_matches(
            [
                {"type": "device", "value": "ios"},
                {"type": "language", "value": "fr"},
            ],
            **self._ctx(
                user_agent="Mozilla/5.0 (iPhone; CPU iPhone OS 17_0)",
                accept_language="en-US",
            ),
        )


class TestPriorityOrder:
    class _R:
        def __init__(self, priority, conditions, target_url):
            self.priority = priority
            self.conditions = conditions
            self.target_url = target_url

    def test_first_matching_rule_wins_by_priority(self):
        rules = [
            self._R(10, [{"type": "device", "value": "android"}], "https://low.example"),
            self._R(0, [{"type": "device", "value": "ios"}], "https://hi.example"),
        ]
        target = pick_target(
            rules,
            "https://default.example",
            user_agent="Mozilla/5.0 (iPhone)",
            accept_language=None,
            query_params={},
        )
        assert target == "https://hi.example"

    def test_falls_back_to_default(self):
        rules = [
            self._R(0, [{"type": "device", "value": "ios"}], "https://ios.example"),
        ]
        target = pick_target(
            rules,
            "https://default.example",
            user_agent="Mozilla/5.0 (Windows NT 10.0)",
            accept_language=None,
            query_params={},
        )
        assert target == "https://default.example"


# ---- Integration tests against the redirect endpoint + CRUD ----


@pytest.mark.integration
class TestRulesEndToEnd:
    def _make_url(self, db_session: Session, test_user: User, code: str = "rules1") -> URL:
        domain = get_or_create_default_domain(db_session)
        url = URL(
            short_code=code,
            domain_id=domain.id,
            original_url="https://default.example",
            url_type=URLType.STANDARD,
            created_by=test_user.id,
        )
        db_session.add(url)
        db_session.commit()
        db_session.refresh(url)
        return url

    def test_redirect_uses_matching_rule(
        self, client: TestClient, db_session: Session, test_user: User
    ):
        url = self._make_url(db_session, test_user)
        db_session.add(
            RedirectRule(
                url_id=url.id,
                priority=0,
                conditions=[{"type": "device", "value": "ios"}],
                target_url="https://ios.example",
            )
        )
        db_session.commit()

        r = client.get(
            "/rules1",
            headers={"User-Agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0)"},
            follow_redirects=False,
        )
        assert r.status_code == 302
        assert r.headers["location"] == "https://ios.example"

    def test_non_matching_rule_falls_back_to_original(
        self, client: TestClient, db_session: Session, test_user: User
    ):
        url = self._make_url(db_session, test_user, "rules2")
        db_session.add(
            RedirectRule(
                url_id=url.id,
                priority=0,
                conditions=[{"type": "device", "value": "ios"}],
                target_url="https://ios.example",
            )
        )
        db_session.commit()

        r = client.get(
            "/rules2",
            headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0)"},
            follow_redirects=False,
        )
        assert r.status_code == 302
        assert r.headers["location"] == "https://default.example"

    def test_crud_endpoints_round_trip(
        self, client: TestClient, db_session: Session, test_user: User, auth_headers
    ):
        self._make_url(db_session, test_user, "rules3")

        # Create
        r = client.post(
            "/api/v1/urls/rules3/rules",
            json={
                "priority": 5,
                "conditions": [{"type": "language", "value": "es"}],
                "target_url": "https://es.example",
            },
            headers=auth_headers,
        )
        assert r.status_code == 201
        rule_id = r.json()["id"]

        # List
        r = client.get("/api/v1/urls/rules3/rules", headers=auth_headers)
        assert r.status_code == 200
        assert len(r.json()) == 1

        # Update
        r = client.patch(
            f"/api/v1/urls/rules3/rules/{rule_id}",
            json={"priority": 1},
            headers=auth_headers,
        )
        assert r.status_code == 200
        assert r.json()["priority"] == 1

        # Delete
        r = client.delete(
            f"/api/v1/urls/rules3/rules/{rule_id}",
            headers=auth_headers,
        )
        assert r.status_code == 204

        r = client.get("/api/v1/urls/rules3/rules", headers=auth_headers)
        assert r.json() == []
