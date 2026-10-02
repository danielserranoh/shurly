"""
Phase 8.4 — importing Shlink's links from a snapshot and its review sheet.

Each kept link arrives with its exact code, its domain and its creation date, owned by the
organization. What maps is mapped, what doesn't is reported, and nothing is dropped
silently. The import can run again: an identical link is left alone, one that differs
stops it. With `--visits` (decision A, 2026-09-28), Shlink's visits come too.
"""

import csv
import json
from datetime import datetime

import httpx
import pytest

from server.core.auth import hash_password
from server.core.config import settings
from server.core.models import (
    URL,
    Domain,
    Organization,
    OrganizationMember,
    OrgRole,
    RedirectRule,
    Tag,
    User,
    Visitor,
)
from server.tools.shlink import __main__ as cli
from server.tools.shlink import importer
from server.tools.shlink.export import export_snapshot, shlink_client
from server.tools.shlink.importer import ImportRefused, import_snapshot
from server.tools.shlink.review import review_rows
from tests.conftest import TestingSessionLocal
from tests.test_phase84_shlink_export import BAD_SECOND, KEY, YEAR, FakeShlink, short_url, visit
from tests.test_phase84_shlink_export import URL as SHLINK_URL

HOST = "go.shlink.test"  # Shlink's default domain in the fixtures
LONG = "jane-doe-acme-corp-2026-q4-outreach-followup"  # 44 characters, as go.griddo.io's longest


@pytest.fixture
def owner(db_session) -> User:
    organization = Organization(name="Griddo")
    user = User(
        email="owner@griddo.io", password_hash=hash_password("x-password-1"), is_active=True
    )
    db_session.add_all([organization, user])
    db_session.flush()
    db_session.add(
        OrganizationMember(organization_id=organization.id, user_id=user.id, role=OrgRole.OWNER)
    )
    db_session.commit()
    return user


def snapshot(*links: dict) -> dict:
    return {
        "format": "shurly.shlink-snapshot/1",
        "exported_at": "2026-09-28T10:15:00+00:00",
        "shlink": {"url": f"https://{HOST}", "version": "4.2.1"},
        "links": list(links),
    }


def run(db, owner, *links, decisions=None, visits=False):
    return import_snapshot(db, snapshot(*links), decisions or {}, owner, visits=visits)


def only_url(db) -> URL:
    return db.query(URL).one()


class TestALink:
    def test_keeps_its_code_domain_and_date(self, db_session, owner):
        link = short_url(
            "AbC12", "https://example.com/offer", dateCreated="2024-01-02T10:00:00+01:00"
        )

        report = run(db_session, owner, {"short_url": link})
        db_session.commit()

        url = only_url(db_session)
        assert url.short_code == "AbC12"  # verbatim: Shlink's default mode is case-sensitive
        assert (url.domain.hostname, url.domain.is_default) == (HOST, False)
        assert url.created_at == datetime(2024, 1, 2, 9, 0)
        membership = db_session.query(OrganizationMember).one()
        assert (url.organization_id, url.created_by) == (membership.organization_id, owner.id)
        assert report.created == [f"{HOST}/AbC12"] and report.domains_created == [HOST]

    def test_answers_on_its_domain_with_its_exact_code(self, client, db_session, owner):
        """ROADMAP 8.2: imported codes are never lowercased on the way in or out."""
        run(db_session, owner, {"short_url": short_url("AbC12", "https://example.com/offer")})
        db_session.commit()

        hit = client.get("/AbC12", headers={"host": HOST}, follow_redirects=False)
        miss = client.get("/abc12", headers={"host": HOST}, follow_redirects=False)

        assert (hit.status_code, hit.headers["location"]) == (302, "https://example.com/offer")
        assert miss.status_code == 404

    def test_a_code_up_to_64_characters_long(self, client, db_session, owner):
        """go.griddo.io's personalized links run to 44 characters, and are out there already."""
        link = {
            "short_url": short_url(LONG, "https://example.com/offer"),
            "visits": [visit("2025-03-01T10:00:00+00:00")],
        }

        report = run(db_session, owner, link, visits=True)
        db_session.commit()

        assert (report.blocked, report.created) == (False, [f"{HOST}/{LONG}"])
        assert db_session.query(Visitor.short_code).scalar() == LONG
        hit = client.get(f"/{LONG}", headers={"host": HOST}, follow_redirects=False)
        assert (hit.status_code, hit.headers["location"]) == (302, "https://example.com/offer")

    def test_a_path_the_app_serves_on_its_own_host_only(
        self, client, db_session, owner, monkeypatch
    ):
        """Phase 8.4: `/mcp` is the MCP on the app's host, and a link on a short domain:
        go.griddo.io's points at a video, with 41 visits. Without an app host (the other tests),
        it's refused on every domain."""
        monkeypatch.setattr(settings, "mcp_public_url", "https://shurly.griddo.io/mcp")
        video = "https://www.youtube.com/watch?v=abc"

        report = run(db_session, owner, {"short_url": short_url("mcp", video)})
        db_session.commit()

        assert (report.blocked, report.created) == (False, [f"{HOST}/mcp"])
        hit = client.get("/mcp", headers={"host": HOST}, follow_redirects=False)
        assert (hit.status_code, hit.headers["location"]) == (302, video)

    def test_the_fields_that_map(self, db_session, owner):
        db_session.add(
            Tag(name="email", display_name="email", color="blue-500", is_predefined=True)
        )
        db_session.commit()
        link = short_url(
            "offer",
            title="The offer",
            tags=["email", "Q4 Promo"],
            meta={
                "validSince": "2025-01-01T00:00:00+00:00",
                "validUntil": "2027-01-01T00:00:00Z",
                "maxVisits": 500,
            },
            crawlable=True,
            forwardQuery=False,
        )

        report = run(db_session, owner, {"short_url": link})
        db_session.commit()

        url = only_url(db_session)
        assert (url.title, url.crawlable, url.forward_parameters, url.max_visits) == (
            "The offer",
            True,
            False,
            500,
        )
        assert (url.valid_since.year, url.valid_until.year) == (2025, 2027)
        assert sorted(tag.name for tag in url.tags) == ["email", "q4 promo"]
        assert report.tags_created == ["q4 promo"]


class TestRules:
    def test_what_maps_is_migrated_and_the_rest_reported(self, db_session, owner):
        rules = {
            "defaultLongUrl": "https://example.com/",
            "redirectRules": [
                {
                    "priority": 1,
                    "longUrl": "https://example.com/ios",
                    "conditions": [
                        {"type": "device", "matchKey": None, "matchValue": "ios"},
                        {"type": "query-param", "matchKey": "utm", "matchValue": "mail"},
                    ],
                },
                {
                    "priority": 2,
                    "longUrl": "https://example.com/en",
                    "conditions": [
                        {"type": "language", "matchKey": None, "matchValue": "en-US"},
                    ],
                },
                {
                    "priority": 3,
                    "longUrl": "https://example.com/office",
                    "conditions": [
                        {"type": "ip-address", "matchKey": None, "matchValue": "10.0.0.0/8"},
                    ],
                },
            ],
        }

        report = run(
            db_session,
            owner,
            {"short_url": short_url("ruled", hasRedirectRules=True), "redirect_rules": rules},
        )
        db_session.commit()

        migrated = db_session.query(RedirectRule).order_by(RedirectRule.priority).all()
        assert [(r.priority, r.target_url, r.conditions) for r in migrated] == [
            (
                1,
                "https://example.com/ios",
                [
                    {"type": "device", "value": "ios"},
                    {"type": "query_param", "param": "utm", "value": "mail"},
                ],
            ),
            (2, "https://example.com/en", [{"type": "language", "value": "en"}]),
        ]
        assert report.rules_migrated == 2
        assert report.rules_approximated == [
            f"{HOST}/ruled rule 2: language en-US matches every en"
        ]
        assert report.rules_skipped == [
            f"{HOST}/ruled rule 3: ip-address has no equivalent in Shurly"
        ]


class TestDecisions:
    def test_drop_archive_and_the_links_the_review_left_out(self, db_session, owner):
        decisions = {(HOST, "gone"): "drop", (HOST, "old"): "archive"}

        report = run(
            db_session,
            owner,
            {"short_url": short_url("gone")},
            {"short_url": short_url("old")},
            {"short_url": short_url("kept")},
            decisions=decisions,
        )
        db_session.commit()

        urls = {url.short_code: url for url in db_session.query(URL).all()}
        assert sorted(urls) == ["kept", "old"]
        assert [tag.name for tag in urls["old"].tags] == ["legacy"]
        assert (report.dropped, report.archived, report.not_reviewed) == (
            [f"{HOST}/gone"],
            [f"{HOST}/old"],
            [f"{HOST}/kept"],
        )


class TestAgain:
    def test_an_identical_link_is_left_alone(self, db_session, owner):
        links = ({"short_url": short_url("abc")}, {"short_url": short_url("xyz")})
        run(db_session, owner, *links)
        db_session.commit()

        report = run(db_session, owner, *links)
        db_session.commit()

        assert db_session.query(URL).count() == 2
        assert (report.created, report.unchanged) == ([], [f"{HOST}/abc", f"{HOST}/xyz"])

    def test_one_that_differs_stops_the_import_before_anything_is_written(self, db_session, owner):
        run(db_session, owner, {"short_url": short_url("abc", "https://example.com/one")})
        db_session.commit()

        report = run(
            db_session,
            owner,
            {"short_url": short_url("abc", "https://example.com/two")},
            {"short_url": short_url("new", domain="s.shlink.test")},
        )

        assert report.blocked
        assert report.conflicts == [f"{HOST}/abc: already there, to https://example.com/one"]
        assert db_session.query(URL).count() == 1
        assert db_session.query(Domain).filter(Domain.hostname == "s.shlink.test").count() == 0

    @pytest.mark.parametrize(
        ("code", "destination", "why"),
        [
            ("x" * 65, "https://example.com/", "longer than 64 characters"),
            ("docs", "https://example.com/", "a path Shurly serves itself"),
            ("app", "myapp://open", "not an http(s) destination"),
        ],
    )
    def test_a_link_shurly_cannot_take_stops_it_unless_dropped(
        self, db_session, owner, code, destination, why
    ):
        link = {"short_url": short_url(code, destination)}

        refused = run(db_session, owner, link)
        dropped = run(db_session, owner, link, decisions={(HOST, code): "drop"})

        assert refused.blocked and refused.refused == [f"{HOST}/{code}: {why}"]
        assert not dropped.blocked


class TestVisits:
    """Decision A (2026-09-28): Shlink's visits come too, with --visits."""

    def test_a_visits_city_by_its_name_never_its_coordinates(self, db_session, owner):
        """Phase 8.4 — `visitLocation.cityName`, the English name, as Shurly's own visits keep
        one (from GeoLite2 City, as Shlink's are). Its latitude and longitude stay behind."""
        located = {
            "countryCode": "ES",
            "countryName": "Spain",
            "regionName": "Aragon",
            "cityName": "Zaragoza",
            "latitude": 41.6561,
            "longitude": -0.8773,
            "timezone": "Europe/Madrid",
            "isEmpty": False,
        }
        visits = [
            {**visit("2025-03-01T10:00:00+00:00"), "visitLocation": located},
            {**visit("2025-03-02T10:00:00+00:00"), "visitLocation": {**located, "cityName": ""}},
            {**visit("2025-03-03T10:00:00+00:00"), "visitLocation": {"countryCode": "PT"}},
            {**visit("2025-03-04T10:00:00+00:00"), "visitLocation": {"cityName": "Ll" * 100}},
        ]

        run(db_session, owner, {"short_url": short_url("abc"), "visits": visits}, visits=True)
        db_session.commit()

        rows = db_session.query(Visitor).order_by(Visitor.visited_at).all()
        assert [(v.country, v.city) for v in rows] == [
            ("ES", "Zaragoza"),
            ("ES", None),
            ("PT", None),
            (None, ("Ll" * 100)[: Visitor.city.type.length]),
        ]

    VISITS = [
        {**visit("2025-03-01T10:00:00+02:00"), "potentialBot": True},
        {**visit("2025-03-02T10:00:00+00:00"), "visitLocation": None, "referer": None},
        {**visit("2025-03-03T10:00:00+00:00"), "redirectUrl": None},  # Shlink's /track pixel
    ]

    def test_as_decided(self, db_session, owner):
        report = run(
            db_session, owner, {"short_url": short_url("abc"), "visits": self.VISITS}, visits=True
        )
        db_session.commit()

        rows = db_session.query(Visitor).order_by(Visitor.visited_at).all()
        assert [(v.ip, v.country, v.referer, v.is_bot, v.is_pixel) for v in rows] == [
            ("unknown", "ES", "https://t.co", True, False),
            ("unknown", None, None, False, False),
            ("unknown", "ES", "https://t.co", False, True),
        ]
        assert [v.visited_at for v in rows] == [
            datetime(2025, 3, 1, 8, 0),
            datetime(2025, 3, 2, 10, 0),
            datetime(2025, 3, 3, 10, 0),
        ]
        assert {v.user_agent for v in rows} == {"Mozilla/5.0"}
        # The newest click, pixels aside; SQLite hands the zone back off.
        assert only_url(db_session).last_click_at.replace(tzinfo=None) == datetime(
            2025, 3, 2, 10, 0
        )
        assert report.visits == 3

    def test_the_clicks_count_toward_the_cap(self, client, db_session, owner):
        """As Shurly's own: the bot and the pixel don't. Shlink counted all three."""
        link = short_url("abc", meta={"validSince": None, "validUntil": None, "maxVisits": 2})
        run(db_session, owner, {"short_url": link, "visits": self.VISITS}, visits=True)
        db_session.commit()

        answers = [
            client.get("/abc", headers={"host": HOST}, follow_redirects=False).status_code
            for _ in range(2)
        ]

        assert answers == [302, 410]  # one imported click, one left

    def test_without_the_flag_none(self, db_session, owner):
        run(db_session, owner, {"short_url": short_url("abc"), "visits": self.VISITS})
        db_session.commit()

        assert db_session.query(Visitor).count() == 0

    def test_a_later_snapshot_brings_only_the_newer_ones(self, db_session, owner):
        """The cutover's final delta: the links are there, the visits since then aren't."""
        run(
            db_session,
            owner,
            {"short_url": short_url("abc"), "visits": self.VISITS[:2]},
            visits=True,
        )
        db_session.commit()

        report = run(
            db_session, owner, {"short_url": short_url("abc"), "visits": self.VISITS}, visits=True
        )
        db_session.commit()

        assert db_session.query(Visitor).count() == 3
        assert (report.unchanged, report.visits) == ([f"{HOST}/abc"], 1)

    def test_what_shlink_failed_to_export_is_named_never_made_up(self, db_session, owner):
        """The export's `visits_gaps`: the visits it recovered come, and the report names
        the ranges it lost."""
        second = "2025-03-04T10:00:07+00:00"
        error = {"status": 500, "detail": "An unknown error occurred."}
        links = [
            {
                "short_url": short_url("partial", visitsSummary={"total": 9, "nonBots": 9}),
                "visits": self.VISITS,
                "visits_error": error,
                "visits_gaps": [{"start": second, "end": second}],
            },
            {
                "short_url": short_url("failed"),
                "visits": [],
                "visits_error": error,
                "visits_gaps": [{"start": "1970-01-01T00:00:00+00:00", "end": second}],
            },
            {
                "short_url": short_url("recovered"),
                "visits": self.VISITS[:1],
                "visits_error": error,
                "visits_gaps": [],
            },
        ]

        report = run(db_session, owner, *links, visits=True)
        db_session.commit()

        assert report.visits == 4 == db_session.query(Visitor).count()
        assert report.visits_lost == [
            f"{HOST}/partial (partial): {second}/{second}",
            f"{HOST}/failed (failed): 1970-01-01T00:00:00+00:00/{second}",
        ]
        text = importer.format_report(report, snapshot(*links), visits=True)
        assert "visits Shlink failed to export, so not imported" in text
        assert f"    {HOST}/partial (partial): {second}/{second}" in text
        assert "recovered" not in text

    def test_from_an_export_shlink_failed_on(self, db_session, owner):
        """End to end, from the fake Shlink: one visit it can't serialize is all that's lost."""
        fake = FakeShlink(
            [short_url("23q4griddo")],
            visits={(None, "23q4griddo"): [visit(BAD_SECOND), *YEAR]},
            broken={(None, "23q4griddo"): {0}},
        )
        client = shlink_client(SHLINK_URL, KEY, transport=httpx.MockTransport(fake.handle))
        exported = export_snapshot(client, visits=True, sleep=lambda seconds: None)

        (row,) = review_rows(exported)
        report = import_snapshot(db_session, exported, {}, owner, visits=True)
        db_session.commit()

        assert (row["visits_export"], row["visits_lost"]) == (
            "partial",
            f"{BAD_SECOND}/{BAD_SECOND}",
        )
        assert report.visits == len(YEAR) == db_session.query(Visitor).count()
        assert report.visits_lost == [f"{HOST}/23q4griddo (partial): {BAD_SECOND}/{BAD_SECOND}"]

    def test_without_the_flag_no_gaps_either(self, db_session, owner):
        link = {
            "short_url": short_url("partial"),
            "visits": [],
            "visits_gaps": [{"start": None, "end": None}],
        }

        report = run(db_session, owner, link)

        assert report.visits_lost == []


class TestOwner:
    def test_must_own_the_organization(self, db_session, owner):
        member = User(email="member@griddo.io", password_hash="x", is_active=True)
        db_session.add(member)
        db_session.flush()
        organization_id = db_session.query(OrganizationMember).one().organization_id
        db_session.add(
            OrganizationMember(
                organization_id=organization_id, user_id=member.id, role=OrgRole.MEMBER
            )
        )
        db_session.commit()

        with pytest.raises(ImportRefused, match="owner"):
            run(db_session, member, {"short_url": short_url("abc")})


class TestALinkListedTwice:
    """R17: production's export listed `co-upb-luis-ochoa` twice, and the import failed on
    the database's unique code with a traceback. It's refused first, by name."""

    def test_is_refused_before_anything_is_written(self, db_session, owner):
        twice = {"short_url": short_url("co-upb-luis-ochoa")}

        with pytest.raises(ImportRefused, match=f"{HOST}/co-upb-luis-ochoa"):
            run(db_session, owner, {"short_url": short_url("abc")}, twice, twice)

        assert db_session.query(URL).count() == 0
        assert db_session.query(Domain).count() == 0

    def test_even_when_the_review_drops_it(self, db_session, owner):
        """Another link may be missing from such a snapshot: export it again."""
        twice = {"short_url": short_url("co-upb-luis-ochoa")}

        with pytest.raises(ImportRefused, match="Export"):
            run(
                db_session,
                owner,
                twice,
                twice,
                decisions={(HOST, "co-upb-luis-ochoa"): "drop"},
            )

    def test_the_command_says_which_and_exits_2(
        self, tmp_path, owner, db_session, monkeypatch, capsys
    ):
        monkeypatch.setattr(importer, "session_factory", TestingSessionLocal)
        twice = {"short_url": short_url("co-upb-luis-ochoa")}
        path = tmp_path / "shlink.snapshot.json"
        path.write_text(json.dumps(snapshot(twice, twice)))
        review = tmp_path / "shlink.review.csv"
        review.write_text("code,domain,decision\n")

        assert cli.main(["import", str(path), str(review), "--as", owner.email]) == 2

        error = capsys.readouterr().err
        assert f"{HOST}/co-upb-luis-ochoa" in error and "Traceback" not in error
        db_session.expire_all()
        assert db_session.query(URL).count() == 0


class TestCommand:
    @pytest.fixture
    def files(self, tmp_path, monkeypatch):
        monkeypatch.setattr(importer, "session_factory", TestingSessionLocal)
        path = tmp_path / "shlink.snapshot.json"
        path.write_text(
            json.dumps(
                snapshot(
                    {"short_url": short_url("abc"), "visits": [visit("2025-03-01T10:00:00+00:00")]},
                    {"short_url": short_url("=formula")},
                )
            )
        )
        review = tmp_path / "shlink.review.csv"
        with review.open("w", newline="") as f:
            writer = csv.writer(f)
            writer.writerow(["code", "domain", "decision"])
            writer.writerow(["abc", HOST, "keep"])
            writer.writerow(["'=formula", HOST, "Drop "])  # as a spreadsheet leaves it
        return path, review

    def test_a_dry_run_writes_nothing(self, files, owner, db_session, capsys):
        assert (
            cli.main(["import", *map(str, files), "--as", owner.email, "--visits", "--dry-run"])
            == 0
        )

        output = capsys.readouterr().out
        assert "Dry run: nothing was written." in output
        assert 'ip "unknown"' in output
        db_session.expire_all()
        assert db_session.query(URL).count() == 0

    def test_the_import_writes(self, files, owner, db_session, capsys):
        assert cli.main(["import", *map(str, files), "--as", owner.email, "--visits"]) == 0

        db_session.expire_all()
        assert [url.short_code for url in db_session.query(URL).all()] == ["abc"]
        assert db_session.query(Visitor).count() == 1

    def test_an_unknown_decision_stops_it(self, files, owner, capsys):
        snapshot_path, review = files
        review.write_text("code,domain,decision\nabc,go.shlink.test,maybe\n")

        assert cli.main(["import", str(snapshot_path), str(review), "--as", owner.email]) == 2
        assert "maybe" in capsys.readouterr().err

    def test_a_blocked_import_exits_1(self, files, owner, db_session, capsys):
        domain = Domain(hostname=HOST)
        db_session.add(domain)
        db_session.flush()
        db_session.add(
            URL(
                short_code="abc",
                original_url="https://elsewhere.test/",
                created_by=owner.id,
                domain_id=domain.id,
            )
        )
        db_session.commit()

        assert cli.main(["import", *map(str, files), "--as", owner.email]) == 1
        assert "already there" in capsys.readouterr().out


def test_on_postgresql(pg_engine):
    """The whole import, twice, on the real database: dates, case-sensitive codes, rules, and a
    code longer than 20, in the columns the migrations made."""
    from sqlalchemy.orm import sessionmaker

    from server.core.migrations import run_migrations

    run_migrations(pg_engine)
    with sessionmaker(bind=pg_engine)() as db:
        organization = Organization(name="Griddo")
        user = User(email="owner@griddo.io", password_hash="x", is_active=True)
        db.add_all([organization, user])
        db.flush()
        db.add(
            OrganizationMember(organization_id=organization.id, user_id=user.id, role=OrgRole.OWNER)
        )
        db.commit()
        links = (
            {
                "short_url": short_url("AbC", "https://example.com/a", tags=["q4"]),
                "visits": [visit("2025-03-01T10:00:00+02:00")],
            },
            {"short_url": short_url("abc", "https://example.com/b")},
            {
                "short_url": short_url(LONG, "https://example.com/c"),
                "visits": [visit("2025-03-02T10:00:00+00:00")],
            },
        )

        first = import_snapshot(db, snapshot(*links), {}, user, visits=True)
        db.commit()
        second = import_snapshot(db, snapshot(*links), {}, user, visits=True)
        db.commit()

        assert (len(first.created), len(second.unchanged), second.visits) == (3, 3, 0)
        assert sorted(url.short_code for url in db.query(URL).all()) == ["AbC", "abc", LONG]
        visits = dict(db.query(Visitor.short_code, Visitor.visited_at).all())
        assert visits == {"AbC": datetime(2025, 3, 1, 8, 0), LONG: datetime(2025, 3, 2, 10, 0)}
