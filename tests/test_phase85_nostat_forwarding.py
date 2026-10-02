"""
Phase 8.5 — `?nostat` is ours, not the destination's.

DISABLE_TRACK_PARAM (`nostat` by default) makes a redirect log no visit. With
`forward_parameters` on, the redirect used to pass it on as well: `go.griddo.io/mcp?nostat` went
to YouTube with `&nostat=` on the end. Shlink drops it before forwarding the query, and so do we:
in the plain redirect, a redirect rule's target and a crawler's preview. Everything else the
address carries goes on as it came: the other parameters, their order and their repeats, after
the destination's own query.
"""

from urllib.parse import parse_qsl, urlsplit

import pytest

from server.core.models import URL, Campaign, RedirectRule, URLType, Visitor
from server.utils.domain import get_or_create_default_domain

DESTINATION = "https://www.youtube.com/watch?v=abc&t=2047s"
LINKEDIN = "LinkedInBot/1.0 (compatible; Mozilla/5.0; Apache-HttpClient +http://www.linkedin.com)"


def _link(db, user, code: str, *, forward: bool = True, original: str = DESTINATION) -> URL:
    url = URL(
        short_code=code,
        original_url=original,
        url_type=URLType.STANDARD,
        forward_parameters=forward,
        created_by=user.id,
        domain_id=get_or_create_default_domain(db).id,
    )
    db.add(url)
    db.commit()
    return url


def _location(client, path: str, **headers) -> str:
    response = client.get(path, headers=headers, follow_redirects=False)
    assert response.status_code == 302, response.text
    return response.headers["location"]


def _query(location: str) -> list[tuple[str, str]]:
    return parse_qsl(urlsplit(location).query, keep_blank_values=True)


def _visits(db, code: str) -> int:
    return db.query(Visitor).filter(Visitor.short_code == code).count()


@pytest.mark.parametrize(
    ("query", "forwarded"),
    [
        ("?nostat", []),
        ("?nostat=1", []),
        ("?nostat=", []),
        ("?a=1&nostat&b=2", [("a", "1"), ("b", "2")]),
        ("?a=1&nostat=yes&b=2", [("a", "1"), ("b", "2")]),
    ],
)
def test_nostat_isnt_forwarded(client, db_session, test_user, query, forwarded):
    _link(db_session, test_user, "ns1")

    location = _location(client, f"/ns1{query}")

    assert _query(location) == [("v", "abc"), ("t", "2047s"), *forwarded]
    assert "nostat" not in location
    assert _visits(db_session, "ns1") == 0  # and it still logs nothing


def test_nostat_alone_leaves_the_destination_as_it_is(client, db_session, test_user):
    _link(db_session, test_user, "ns2")

    assert _location(client, "/ns2?nostat") == DESTINATION


def test_a_destination_without_a_query_gets_no_stray_question_mark(client, db_session, test_user):
    _link(db_session, test_user, "ns3", original="https://example.com/page")

    assert _location(client, "/ns3?nostat=1") == "https://example.com/page"


def test_without_forwarding_nothing_is_passed_on(client, db_session, test_user):
    _link(db_session, test_user, "ns4", forward=False)

    for query in ("?nostat", "?a=1&nostat&b=2", "?nostat=1"):
        assert _location(client, f"/ns4{query}") == DESTINATION
    assert _visits(db_session, "ns4") == 0


def test_order_and_repeated_keys_are_kept(client, db_session, test_user):
    _link(db_session, test_user, "ns5")

    location = _location(client, "/ns5?b=2&tag=x&nostat&a=1&tag=y")

    assert _query(location) == [
        ("v", "abc"),
        ("t", "2047s"),
        ("b", "2"),
        ("tag", "x"),
        ("a", "1"),
        ("tag", "y"),
    ]


def test_a_visit_without_nostat_forwards_and_logs(client, db_session, test_user):
    _link(db_session, test_user, "ns6")

    location = _location(client, "/ns6?utm_source=email")

    assert _query(location)[-1] == ("utm_source", "email")
    assert _visits(db_session, "ns6") == 1


def test_a_redirect_rule_target_doesnt_get_it_either(client, db_session, test_user):
    url = _link(db_session, test_user, "ns7")
    db_session.add(
        RedirectRule(
            url_id=url.id,
            priority=0,
            conditions=[{"type": "query_param", "param": "src", "value": "qa"}],
            target_url="https://example.com/rule?x=1",
        )
    )
    db_session.commit()

    location = _location(client, "/ns7?src=qa&nostat")

    assert urlsplit(location).path == "/rule"
    assert _query(location) == [("x", "1"), ("src", "qa")]


def test_a_crawlers_preview_doesnt_carry_it(client, db_session, test_user):
    _link(db_session, test_user, "ns8")

    response = client.get(
        "/ns8?a=1&nostat", headers={"user-agent": LINKEDIN}, follow_redirects=False
    )

    assert response.status_code == 200
    assert "nostat" not in response.text
    assert "a=1" in response.text


def test_a_campaign_link_keeps_its_recipient_data_and_drops_nostat(client, db_session, test_user):
    campaign = Campaign(
        name="QA",
        original_url="https://example.com/webinar",
        csv_columns=["name"],
        created_by=test_user.id,
    )
    db_session.add(campaign)
    db_session.flush()
    db_session.add(
        URL(
            short_code="ns9",
            original_url=campaign.original_url,
            url_type=URLType.CAMPAIGN,
            campaign_id=campaign.id,
            user_data={"name": "Zelda"},
            created_by=test_user.id,
            domain_id=get_or_create_default_domain(db_session).id,
        )
    )
    db_session.commit()

    location = _location(client, "/ns9?nostat&utm_source=email")

    assert _query(location) == [("name", "Zelda"), ("utm_source", "email")]


def test_the_parameter_is_the_configured_one(client, db_session, test_user, monkeypatch):
    from server.core.config import settings

    monkeypatch.setattr(settings, "disable_track_param", "qa")
    _link(db_session, test_user, "ns10")

    location = _location(client, "/ns10?qa&nostat=1")

    assert _query(location) == [("v", "abc"), ("t", "2047s"), ("nostat", "1")]
    assert _visits(db_session, "ns10") == 0
