"""
Orphan visits by the path tried (ROADMAP 3.10.4): the analytics page's "Typos & broken links"
and the MCP's `list_orphan_visits_grouped`, from one grouping in SQL (`server/utils/orphans.py`).

- `GET /api/v1/analytics/orphan-visits/grouped`: the paths tried on unknown codes in a period,
  most tried first, a page at a time, with their first and last hit. Never an IP, a user agent
  or a referrer.
- "Did you mean": the links, among those the viewer sees, that the path is one edit away from
  (a character deleted, inserted, replaced, or swapped with its neighbour), or the same but for
  case where codes are lowercase. Found by index, in one query per path: none for a path no code
  could be one edit from (too long, or with a character no code has).
"""

from datetime import datetime, timedelta, timezone

import pytest

from server.core.config import settings
from server.core.models import URL, Domain, OrphanVisit, OrphanVisitType, User
from server.utils.domain import get_or_create_default_domain
from tests.test_pagination_and_query_counts import _request_sql

GROUPED = "/api/v1/analytics/orphan-visits/grouped"
NOW = datetime.now(timezone.utc).replace(tzinfo=None, microsecond=0)
IP, AGENT, REFERER = "203.0.113.77", "MarkerAgent/9.9", "https://marker.example/secret"


def _hits(db, path: str, *ages: timedelta, kind=OrphanVisitType.INVALID_SHORT_URL) -> None:
    for age in ages:
        db.add(
            OrphanVisit(
                type=kind,
                attempted_path=path,
                ip=IP,
                user_agent=AGENT,
                referer=REFERER,
                created_at=NOW - age,
            )
        )
    db.commit()


def _link(db, user: User, code: str, *, domain: Domain | None = None, age=timedelta(0)) -> URL:
    url = URL(
        short_code=code,
        original_url=f"https://example.com/{code}",
        title=f"Title of {code}",
        created_by=user.id,
        domain_id=(domain or get_or_create_default_domain(db)).id,
        created_at=NOW - age,
    )
    db.add(url)
    db.commit()
    return url


def _groups(client, headers, query: str = "") -> dict:
    response = client.get(f"{GROUPED}{query}", headers=headers)
    assert response.status_code == 200, response.text
    return response.json()


def _suggested(client, headers, path: str) -> list[str]:
    group = next(g for g in _groups(client, headers)["groups"] if g["attempted_path"] == path)
    return [link["short_code"] for link in group["did_you_mean"]]


# ---------------------------------------------------------------------------
# The groups
# ---------------------------------------------------------------------------


def test_the_paths_tried_most_first_with_their_first_and_last_hit(client, auth_headers, db_session):
    _hits(db_session, "/abc12", timedelta(days=3), timedelta(hours=5), timedelta(minutes=1))
    _hits(db_session, "/zzz", timedelta(days=1))
    _hits(db_session, "/", timedelta(hours=1), timedelta(hours=2), kind=OrphanVisitType.BASE_URL)
    _hits(db_session, "/old", timedelta(days=40))  # before the period

    body = _groups(client, auth_headers)

    assert (body["total_visits"], body["total_paths"], body["pages"]) == (4, 2, 1)
    assert [(g["attempted_path"], g["visits"]) for g in body["groups"]] == [
        ("/abc12", 3),
        ("/zzz", 1),
    ]
    first = body["groups"][0]
    assert first["first_seen"] == (NOW - timedelta(days=3)).isoformat() + "Z"
    assert first["last_seen"] == (NOW - timedelta(minutes=1)).isoformat() + "Z"
    assert body["timezone"] == "Etc/UTC"  # no time zone in their profile


def test_a_tie_goes_to_the_latest_hit_then_the_path(client, auth_headers, db_session):
    _hits(db_session, "/bbb", timedelta(hours=2))
    _hits(db_session, "/aaa", timedelta(hours=2))
    _hits(db_session, "/ccc", timedelta(hours=1))

    paths = [g["attempted_path"] for g in _groups(client, auth_headers)["groups"]]

    assert paths == ["/ccc", "/aaa", "/bbb"]


def test_a_page_at_a_time(client, auth_headers, db_session):
    for i in range(25):
        _hits(db_session, f"/p{i:02d}", *[timedelta(minutes=m) for m in range(25 - i)])

    first = _groups(client, auth_headers, "?page_size=10")
    last = _groups(client, auth_headers, "?page_size=10&page=3")
    past = _groups(client, auth_headers, "?page_size=10&page=4")

    assert (first["total_paths"], first["pages"], len(first["groups"])) == (25, 3, 10)
    assert first["groups"][0]["attempted_path"] == "/p00"  # 25 hits
    assert [g["attempted_path"] for g in last["groups"]] == [f"/p{i}" for i in range(20, 25)]
    assert past["groups"] == []


def test_the_period(client, auth_headers, db_session):
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    db_session.add(
        OrphanVisit(type=OrphanVisitType.INVALID_SHORT_URL, attempted_path="/today", created_at=now)
    )
    _hits(db_session, "/lastweek", timedelta(days=6))

    paths = [g["attempted_path"] for g in _groups(client, auth_headers, "?period=1")["groups"]]

    assert paths == ["/today"]


def test_a_range_counts_only_its_days(client, auth_headers, db_session):
    _hits(db_session, "/inside", timedelta(days=6))
    _hits(db_session, "/after", timedelta(days=2))
    _hits(db_session, "/before", timedelta(days=12))
    first, last = (NOW - timedelta(days=8)).date(), (NOW - timedelta(days=4)).date()

    body = _groups(client, auth_headers, f"?from={first}&to={last}")

    assert [g["attempted_path"] for g in body["groups"]] == ["/inside"]
    assert (body["from"], body["to"]) == (str(first), str(last))


def test_never_an_ip_a_user_agent_or_a_referrer(client, auth_headers, db_session, test_user):
    _hits(db_session, "/abc12", timedelta(minutes=1))
    _link(db_session, test_user, "abc123")

    response = client.get(GROUPED, headers=auth_headers)

    assert not [marker for marker in (IP, AGENT, REFERER) if marker in response.text]
    group = response.json()["groups"][0]
    assert set(group) == {"attempted_path", "visits", "first_seen", "last_seen", "did_you_mean"}
    assert set(group["did_you_mean"][0]) == {"short_code", "domain", "short_url", "title"}


def test_it_needs_signing_in(client):
    assert client.get(GROUPED).status_code == 401


# ---------------------------------------------------------------------------
# Did you mean
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "typed",
    [
        "/abc124",  # a character replaced
        "/abc12",  # one missing
        "/abc1234",  # one too many
        "/acb123",  # two neighbours swapped
        "/ABC123",  # capitals, where codes are lowercase
    ],
)
def test_a_path_one_edit_from_a_code_suggests_it(
    client, auth_headers, db_session, test_user, typed
):
    _link(db_session, test_user, "abc123")
    _hits(db_session, typed, timedelta(minutes=1))

    assert _suggested(client, auth_headers, typed) == ["abc123"]


@pytest.mark.parametrize("typed", ["/abd12", "/bac132", "/abc1235x"])
def test_two_edits_away_suggests_nothing(client, auth_headers, db_session, test_user, typed):
    _link(db_session, test_user, "abc123")
    _hits(db_session, typed, timedelta(minutes=1))

    assert _suggested(client, auth_headers, typed) == []


def test_the_likeliest_first_and_three_at_most(client, auth_headers, db_session, test_user):
    """The same code but for case first, then the newest of those one edit away."""
    for age, code in enumerate(["abc124", "abd123", "xbc123", "abc12"]):
        _link(db_session, test_user, code, age=timedelta(days=age))
    _link(db_session, test_user, "abc123", age=timedelta(days=9))
    _hits(db_session, "/ABC123", timedelta(minutes=1))

    assert _suggested(client, auth_headers, "/ABC123") == ["abc123", "abc124", "abd123"]


def test_strict_codes_keep_their_case(client, auth_headers, db_session, test_user, monkeypatch):
    """With SHORT_URL_MODE=strict a code's case is its own: capitals are edits like any other."""
    monkeypatch.setattr(settings, "short_url_mode", "strict")
    _link(db_session, test_user, "abc123")
    _hits(db_session, "/Abc123", timedelta(minutes=1))
    _hits(db_session, "/ABC123", timedelta(minutes=1))

    assert _suggested(client, auth_headers, "/Abc123") == ["abc123"]
    assert _suggested(client, auth_headers, "/ABC123") == []


def test_only_links_the_viewer_sees(client, auth_headers, db_session, test_user):
    someone = User(email="someone@else.example", password_hash="x", is_active=True)
    db_session.add(someone)
    db_session.commit()
    _link(db_session, someone, "abc124")  # someone's personal link
    _link(db_session, test_user, "abc125")
    _hits(db_session, "/abc12", timedelta(minutes=1))

    assert _suggested(client, auth_headers, "/abc12") == ["abc125"]


def test_a_link_on_another_domain_comes_with_it(client, auth_headers, db_session, test_user):
    go = Domain(hostname="go.example.com", is_default=False)
    db_session.add(go)
    db_session.commit()
    _link(db_session, test_user, "abc123", domain=go)
    _hits(db_session, "/abc12", timedelta(minutes=1))

    group = _groups(client, auth_headers)["groups"][0]

    assert group["did_you_mean"] == [
        {
            "short_code": "abc123",
            "domain": "go.example.com",
            "short_url": "https://go.example.com/abc123",
            "title": "Title of abc123",
        }
    ]


@pytest.mark.parametrize(
    "typed, code",
    [
        ("/" + "a" * 21, "a" * 20),  # longer than any code: one deletion away, but not looked for
        ("/abc12.", "abc123"),  # a character no code has: one replacement away, not looked for
        ("/wp-login.php", "wp-loginxphp"),
    ],
)
def test_no_lookup_for_a_path_no_code_could_be(
    client, auth_headers, db_session, test_user, typed, code
):
    """Scanners' probes and overlong paths: no suggestion, and no query for one."""
    _link(db_session, test_user, code)
    _hits(db_session, typed, timedelta(minutes=1))

    response, statements = _request_sql(client, db_session, "GET", GROUPED, headers=auth_headers)

    assert response.json()["groups"][0]["did_you_mean"] == []
    assert not [s for s in statements if "FROM urls" in s], statements


def test_suggestions_cost_the_same_whatever_the_number_of_links(
    client, auth_headers, db_session, test_user
):
    _hits(db_session, "/abc12", timedelta(minutes=1))
    _hits(db_session, "/xyz98", timedelta(minutes=2))
    _link(db_session, test_user, "abc123")
    _, few = _request_sql(client, db_session, "GET", GROUPED, headers=auth_headers)

    for i in range(200):
        _link(db_session, test_user, f"n{i:04d}x")
    _link(db_session, test_user, "xyz987")
    response, many = _request_sql(client, db_session, "GET", GROUPED, headers=auth_headers)

    assert len(many) == len(few), many
    assert sum("FROM urls" in s for s in many) == 2  # one per path on the page
    suggested = {g["attempted_path"]: g["did_you_mean"] for g in response.json()["groups"]}
    assert [s["short_code"] for s in suggested["/xyz98"]] == ["xyz987"]


# ---------------------------------------------------------------------------
# The MCP's list_orphan_visits_grouped
# ---------------------------------------------------------------------------


def test_the_mcp_tool_groups_the_same_way_and_suggests_too(
    client, auth_headers, db_session, test_user
):
    from mcp_server import curated

    _hits(db_session, "/abc12", timedelta(days=2), timedelta(hours=3), timedelta(minutes=1))
    _hits(db_session, "/zzz", timedelta(days=1))
    _hits(db_session, "/", timedelta(hours=1), kind=OrphanVisitType.BASE_URL)
    _link(db_session, test_user, "abc123")

    result = curated.list_orphan_visits_grouped(db_session, test_user, since_days=30)
    page = _groups(client, auth_headers)

    # Every kind, as it always has: "/" too, ahead of /zzz on the tie as its hit is later.
    assert [(g["attempted_path"], g["count"]) for g in result["groups"]] == [
        ("/abc12", 3),
        ("/", 1),
        ("/zzz", 1),
    ]
    assert (result["total_visits"], result["distinct_paths"]) == (5, 3)
    abc = result["groups"][0]
    # UTC, with Z like the API's datetimes (strict MCP clients reject a date-time without an offset).
    assert abc["first_seen"] == (NOW - timedelta(days=2)).isoformat() + "Z"
    assert abc["last_seen"] == (NOW - timedelta(minutes=1)).isoformat() + "Z"
    assert abc["did_you_mean"] == page["groups"][0]["did_you_mean"]
    # Its samples stay as they were (their IPs are a decision pending): the newest 3.
    assert [s["created_at"] for s in abc["samples"]] == [
        (NOW - age).isoformat() + "Z"
        for age in (timedelta(minutes=1), timedelta(hours=3), timedelta(days=2))
    ]
    assert abc["samples"][0]["ip"] == IP


def test_the_grouped_route_isnt_an_mcp_tool():
    """The curated list_orphan_visits_grouped is the MCP's grouping."""
    import asyncio

    pytest.importorskip("fastmcp")
    from mcp_server.server import _build_mcp_server

    names = {tool.name for tool in asyncio.run(_build_mcp_server().list_tools())}

    assert [name for name in names if "grouped" in name] == ["list_orphan_visits_grouped"]
