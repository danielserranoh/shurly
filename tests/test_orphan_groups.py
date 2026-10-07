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


def test_a_long_code_is_looked_for_too(client, auth_headers, db_session, test_user):
    """Codes run to 64 characters since Shlink's import (8.4), the longest 44."""
    code = "jane-doe-acme-corp-2026-q4-outreach-followup"
    _link(db_session, test_user, code)
    _hits(db_session, f"/{code[:-1]}", timedelta(minutes=1))  # its last character missing

    assert _suggested(client, auth_headers, f"/{code[:-1]}") == [code]


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
        ("/" + "a" * 65, "a" * 64),  # longer than any code: one deletion away, but not looked for
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


# ---------------------------------------------------------------------------
# Typos only (3.10.8): what a person could have mistyped, without scanners and bots
# ---------------------------------------------------------------------------

BROWSER = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_5) AppleWebKit/605.1.15 Version/17.5 Safari/605.1.15"
)
CRAWLER = "Mozilla/5.0 (compatible; Googlebot/2.1; +http://www.google.com/bot.html)"
SCANNED = [
    "/.env",
    "/favicon.ico",
    "/info.php",
    "/wp-login.php",
    "/.git/config",
    "/wp-admin",
    "/admin",
    "/Administrator",  # the scanners' words, whatever their case
    "/HNAP1",
    "/phpmyadmin",
]


def _hit(db, path: str, *, agent: str | None = BROWSER, kind=OrphanVisitType.INVALID_SHORT_URL):
    db.add(
        OrphanVisit(
            type=kind, attempted_path=path, user_agent=agent, created_at=NOW - timedelta(hours=1)
        )
    )
    db.commit()


@pytest.mark.parametrize("path", SCANNED)
def test_a_scanners_probe_isnt_a_typo(client, auth_headers, db_session, path):
    _hit(db_session, path)

    body = _groups(client, auth_headers, "?typos_only=true")

    assert body["groups"] == []
    assert (body["total_visits"], body["total_paths"], body["pages"]) == (0, 0, 0)
    assert (body["hidden_visits"], body["hidden_paths"]) == (1, 1)


@pytest.mark.parametrize("path", ["/co-utadeo-lisa-garca", "/Wn7zf", "/abc12"])
def test_a_real_typo_is_one(client, auth_headers, db_session, path):
    _hit(db_session, path)
    _hit(db_session, path, agent=None)  # no user agent isn't a bot's, as for a link's visits

    body = _groups(client, auth_headers, "?typos_only=true")

    assert [(g["attempted_path"], g["visits"]) for g in body["groups"]] == [(path, 2)]
    assert (body["hidden_visits"], body["hidden_paths"]) == (0, 0)


def test_a_typo_still_gets_its_did_you_mean(client, auth_headers, db_session, test_user):
    _link(db_session, test_user, "co-utadeo-lisa-garcia")
    _link(db_session, test_user, "wn7zfa")
    _hit(db_session, "/co-utadeo-lisa-garca")
    _hit(db_session, "/Wn7zf")

    groups = _groups(client, auth_headers, "?typos_only=true")["groups"]

    assert {g["attempted_path"]: [s["short_code"] for s in g["did_you_mean"]] for g in groups} == {
        "/co-utadeo-lisa-garca": ["co-utadeo-lisa-garcia"],
        "/Wn7zf": ["wn7zfa"],
    }


@pytest.mark.parametrize(
    "agent",
    [CRAWLER, "curl/8.4.0", "python-requests/2.31", "Go-http-client/1.1", "Wget/1.21", "a Spider"],
)
def test_a_bot_on_a_code_shaped_path_isnt_a_typo(client, auth_headers, db_session, agent):
    _hit(db_session, "/abc12", agent=agent)

    body = _groups(client, auth_headers, "?typos_only=true")

    assert body["groups"] == []
    assert (body["hidden_visits"], body["hidden_paths"]) == (1, 1)


def test_a_path_people_and_bots_tried_counts_the_people(client, auth_headers, db_session):
    _hit(db_session, "/abc12")
    _hit(db_session, "/abc12", agent=CRAWLER)
    _hit(db_session, "/abc12", agent="curl/8.4.0")

    body = _groups(client, auth_headers, "?typos_only=true")

    assert [(g["attempted_path"], g["visits"]) for g in body["groups"]] == [("/abc12", 1)]
    assert (body["total_visits"], body["total_paths"]) == (1, 1)
    # Two hits hidden, but no path: /abc12 is shown.
    assert (body["hidden_visits"], body["hidden_paths"]) == (2, 0)


def test_the_bare_domain_isnt_a_typo(client, auth_headers, db_session):
    _hit(db_session, "/", kind=OrphanVisitType.BASE_URL)
    _hit(db_session, "/abc12", kind=OrphanVisitType.REGULAR_404)  # nothing records these yet

    body = _groups(client, auth_headers, "?typos_only=true")

    assert body["groups"] == []
    # Neither is in the section without the filter either: only unknown codes are.
    assert (body["hidden_visits"], body["hidden_paths"]) == (0, 0)


def test_a_scanners_word_that_is_a_links_code_isnt_hidden(
    client, auth_headers, db_session, test_user
):
    """A link with that code, on any domain: its hits elsewhere could be typos of the domain."""
    go = Domain(hostname="go.example.com", is_default=False)
    db_session.add(go)
    db_session.commit()
    _link(db_session, test_user, "console", domain=go)
    _hit(db_session, "/console")
    _hit(db_session, "/Console")
    _hit(db_session, "/admin")

    body = _groups(client, auth_headers, "?typos_only=true")

    assert sorted(g["attempted_path"] for g in body["groups"]) == ["/Console", "/console"]
    assert (body["hidden_visits"], body["hidden_paths"]) == (1, 1)


def test_typos_only_pages_and_counts_only_whats_shown(client, auth_headers, db_session):
    for i in range(12):
        for _ in range(12 - i):
            _hit(db_session, f"/t{i:02d}")
        _hit(db_session, f"/t{i:02d}", agent=CRAWLER)  # one bot hit on each
    for path in SCANNED:
        for _ in range(20):  # the most tried of all, but not typos
            _hit(db_session, path)

    first = _groups(client, auth_headers, "?typos_only=true&page_size=5")
    last = _groups(client, auth_headers, "?typos_only=true&page_size=5&page=3")

    assert (first["groups"][0]["attempted_path"], first["groups"][0]["visits"]) == ("/t00", 12)
    assert (first["total_paths"], first["pages"], len(first["groups"])) == (12, 3, 5)
    assert first["total_visits"] == sum(range(1, 13))
    assert [g["attempted_path"] for g in last["groups"]] == ["/t10", "/t11"]
    assert first["hidden_visits"] == 12 + 20 * len(SCANNED)
    assert first["hidden_paths"] == len(SCANNED)


def test_without_typos_only_everything_as_before(client, auth_headers, db_session):
    _hit(db_session, "/abc12")
    _hit(db_session, "/abc12", agent=CRAWLER)
    for path in SCANNED:
        _hit(db_session, path)
    _hit(db_session, "/", kind=OrphanVisitType.BASE_URL)

    default = _groups(client, auth_headers)
    off = _groups(client, auth_headers, "?typos_only=false")

    assert default == off
    assert (default["groups"][0]["attempted_path"], default["groups"][0]["visits"]) == ("/abc12", 2)
    assert (default["total_visits"], default["total_paths"]) == (2 + len(SCANNED), 1 + len(SCANNED))
    assert (default["hidden_visits"], default["hidden_paths"]) == (0, 0)


def test_the_mcp_tool_can_leave_out_scanners_and_bots_too(db_session, test_user):
    from mcp_server import curated

    _hit(db_session, "/abc12")
    _hit(db_session, "/abc12", agent=CRAWLER)
    _hit(db_session, "/.env")
    _hit(db_session, "/", kind=OrphanVisitType.BASE_URL)

    everything = curated.list_orphan_visits_grouped(db_session, test_user)
    typos = curated.list_orphan_visits_grouped(db_session, test_user, typos_only=True)

    assert (everything["total_visits"], everything["distinct_paths"]) == (4, 3)
    assert (everything["hidden_visits"], everything["hidden_paths"]) == (0, 0)
    assert [(g["attempted_path"], g["count"]) for g in typos["groups"]] == [("/abc12", 1)]
    assert (typos["total_visits"], typos["distinct_paths"]) == (1, 1)
    assert (typos["hidden_visits"], typos["hidden_paths"]) == (3, 2)
    # Its samples are the hits shown: not the crawler's.
    assert [s["user_agent"] for s in typos["groups"][0]["samples"]] == [BROWSER]


@pytest.mark.parametrize(
    "agent",
    [None, "", BROWSER, CRAWLER, "CURL/7", "Java/17.0.2", "Mozilla/5.0 (compatible; bingbot/2.0)"],
)
def test_a_bot_in_sql_is_a_bot_for_a_visit(db_session, agent):
    """The query's test is a visit's `is_bot`, from the same patterns."""
    from server.utils.user_agent import bot_agent, is_bot

    _hit(db_session, "/abc12", agent=agent)

    flagged = db_session.query(bot_agent(OrphanVisit.user_agent)).scalar()

    assert bool(flagged) is is_bot(agent)
