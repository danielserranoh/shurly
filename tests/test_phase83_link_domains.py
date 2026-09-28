"""
Phase 8.3 — a link is its code and its domain. Once Shlink's links are imported, one
code can name a link on the default domain and another on go.griddo.io. Every route
that takes a code also takes `?domain=`; without it the default domain's link answers
(a link from before domains counts as the default's), then by hostname. And every short
URL is built on its link's own domain.
"""

import asyncio
from urllib.parse import quote

import pytest

from server.core.config import settings
from server.core.models import URL, Campaign, Domain, RedirectRule, Tag, URLType, User, Visitor
from server.utils.domain import get_or_create_default_domain, resolve_domain_for_host

GO = "go.griddo.io"


@pytest.fixture
def domains(db_session):
    default = get_or_create_default_domain(db_session)
    go = Domain(hostname=GO, is_default=False)
    db_session.add(go)
    db_session.commit()
    return default, go


def _link(db, user, domain, code="promo", **fields) -> URL:
    url = URL(
        short_code=code,
        original_url=f"https://example.com/{domain.hostname if domain else 'legacy'}/{code}",
        url_type=URLType.STANDARD,
        created_by=user.id,
        domain_id=domain.id if domain else None,
        **fields,
    )
    db.add(url)
    db.commit()
    return url


@pytest.fixture
def both(db_session, test_user, domains) -> tuple[URL, URL]:
    """The same code on the default domain and on go.griddo.io, both the user's."""
    default, go = domains
    return _link(db_session, test_user, default), _link(db_session, test_user, go)


def _visits(db, url: URL, count: int) -> None:
    db.add_all(
        Visitor(url_id=url.id, short_code=url.short_code, ip="203.0.113.0", country="Spain")
        for _ in range(count)
    )
    db.commit()


class TestAddressing:
    def test_without_a_domain_the_default_domains_link(self, client, auth_headers, both):
        """Old bookmarks of the link page (`?code=` only) keep working this way."""
        body = client.get("/api/v1/urls/promo", headers=auth_headers).json()

        assert (body["original_url"], body["domain"]) == (
            both[0].original_url,
            settings.default_domain,
        )

    def test_with_a_domain_that_domains_link(self, client, auth_headers, both):
        body = client.get(f"/api/v1/urls/promo?domain={GO}", headers=auth_headers).json()

        assert (body["original_url"], body["domain"]) == (both[1].original_url, GO)

    @pytest.mark.parametrize(
        "written", ["GO.Griddo.IO", "go.griddo.io.", "go.griddo.io:443", "Go.Griddo.io.:8443"]
    )
    def test_the_domain_is_read_as_the_redirect_path_reads_a_host(
        self, client, auth_headers, db_session, both, written
    ):
        """`?domain=` and a request's Host name the same domain the same way: lowercase, no
        port, no trailing dot."""
        assert resolve_domain_for_host(db_session, written).hostname == GO

        response = client.get(f"/api/v1/urls/promo?domain={quote(written)}", headers=auth_headers)

        assert response.json()["domain"] == GO

    def test_an_unknown_domain_or_no_such_link_on_it_is_a_404(
        self, client, auth_headers, db_session, test_user, domains
    ):
        _link(db_session, test_user, domains[0], code="solo")

        assert (
            client.get("/api/v1/urls/solo?domain=nowhere.test", headers=auth_headers).status_code
            == 404
        )
        assert client.get(f"/api/v1/urls/solo?domain={GO}", headers=auth_headers).status_code == 404

    def test_without_the_default_domain_by_hostname(
        self, client, auth_headers, db_session, test_user, domains
    ):
        later, earlier = Domain(hostname="b.example"), Domain(hostname="a.example")
        db_session.add_all([later, earlier])
        db_session.commit()
        _link(db_session, test_user, later, code="twin")
        _link(db_session, test_user, earlier, code="twin")

        assert client.get("/api/v1/urls/twin", headers=auth_headers).json()["domain"] == "a.example"

    def test_a_link_from_before_domains_counts_as_the_default_domains(
        self, client, auth_headers, db_session, test_user, domains
    ):
        legacy = _link(db_session, test_user, None, code="old")
        _link(db_session, test_user, domains[1], code="old")

        plain = client.get("/api/v1/urls/old", headers=auth_headers).json()
        named = client.get(
            f"/api/v1/urls/old?domain={settings.default_domain}", headers=auth_headers
        ).json()

        assert plain["original_url"] == named["original_url"] == legacy.original_url
        assert plain["domain"] == settings.default_domain

    def test_the_default_domains_own_link_before_one_from_before_domains(
        self, client, auth_headers, db_session, test_user, domains
    ):
        _link(db_session, test_user, None, code="dup")
        current = _link(db_session, test_user, domains[0], code="dup")

        assert client.get("/api/v1/urls/dup", headers=auth_headers).json()["id"] == str(current.id)

    def test_someone_elses_personal_link_stays_hidden(
        self, client, auth_headers, db_session, domains
    ):
        other = User(email="other@griddo.io", password_hash="x", is_active=True)
        db_session.add(other)
        db_session.commit()
        _link(db_session, other, domains[1], code="theirs")

        assert (
            client.get(f"/api/v1/urls/theirs?domain={GO}", headers=auth_headers).status_code == 404
        )


class TestEveryRouteTakesTheDomain:
    def test_update(self, client, auth_headers, db_session, both):
        response = client.patch(
            f"/api/v1/urls/promo?domain={GO}", json={"title": "Go"}, headers=auth_headers
        )

        assert response.status_code == 200
        db_session.expire_all()
        assert (both[0].title, both[1].title) == (None, "Go")

    def test_delete(self, client, auth_headers, db_session, both):
        assert (
            client.delete(f"/api/v1/urls/promo?domain={GO}", headers=auth_headers).status_code
            == 204
        )

        assert [url.domain_id for url in db_session.query(URL).all()] == [both[0].domain_id]

    def test_tags(self, client, auth_headers, db_session, test_user, both):
        tag = Tag(name="q4", display_name="Q4", color="gray-500", created_by=test_user.id)
        db_session.add(tag)
        db_session.commit()

        response = client.patch(
            f"/api/v1/urls/promo/tags?domain={GO}",
            json={"tag_ids": [str(tag.id)]},
            headers=auth_headers,
        )

        assert response.status_code == 200
        db_session.expire_all()
        assert ([t.name for t in both[0].tags], [t.name for t in both[1].tags]) == ([], ["q4"])

    def test_rules(self, client, auth_headers, db_session, both):
        rule = {
            "priority": 1,
            "conditions": [{"type": "device", "value": "ios"}],
            "target_url": "https://apps.test/",
        }

        created = client.post(
            f"/api/v1/urls/promo/rules?domain={GO}", json=rule, headers=auth_headers
        )

        assert created.status_code == 201
        assert db_session.query(RedirectRule).one().url_id == both[1].id
        assert (
            len(client.get(f"/api/v1/urls/promo/rules?domain={GO}", headers=auth_headers).json())
            == 1
        )
        assert client.get("/api/v1/urls/promo/rules", headers=auth_headers).json() == []
        rule_id = created.json()["id"]
        assert (
            client.delete(f"/api/v1/urls/promo/rules/{rule_id}", headers=auth_headers).status_code
            == 404
        )
        assert (
            client.delete(
                f"/api/v1/urls/promo/rules/{rule_id}?domain={GO}", headers=auth_headers
            ).status_code
            == 204
        )

    def test_preview_and_refresh(self, client, auth_headers, both, monkeypatch):
        from server.app import urls as urls_module
        from server.utils.opengraph import OpenGraphMetadata

        fetched = []

        async def fetch(url, *args, **kwargs):
            fetched.append(url)
            return OpenGraphMetadata(title="Fresh")

        monkeypatch.setattr(urls_module, "fetch_opengraph_metadata", fetch)

        preview = client.get(f"/api/v1/urls/promo/preview?domain={GO}", headers=auth_headers).json()
        client.post(f"/api/v1/urls/promo/refresh-preview?domain={GO}", headers=auth_headers)

        assert preview["og_url"] == f"https://{GO}/promo"
        assert fetched == [both[1].original_url]

    @pytest.mark.parametrize("stats", ["daily", "weekly", "geo"])
    def test_analytics(self, client, auth_headers, db_session, both, stats):
        _visits(db_session, both[0], 2)
        _visits(db_session, both[1], 3)

        plain = client.get(f"/api/v1/analytics/urls/promo/{stats}", headers=auth_headers).json()
        named = client.get(
            f"/api/v1/analytics/urls/promo/{stats}?domain={GO}", headers=auth_headers
        ).json()

        assert (plain["total_clicks"], named["total_clicks"]) == (2, 3)


class TestTheMcp:
    def test_the_curated_tools_take_the_domain(self, db_session, test_user, both):
        pytest.importorskip("fastmcp")
        from mcp_server.curated import add_redirect_rule, get_url_analytics_summary

        _visits(db_session, both[1], 3)

        add_redirect_rule(
            db_session,
            test_user,
            short_code="promo",
            domain=GO,
            target_url="https://apps.test/",
            device="ios",
        )
        summary = get_url_analytics_summary(db_session, test_user, short_code="promo", domain=GO)

        assert db_session.query(RedirectRule).one().url_id == both[1].id
        assert (summary["domain"], summary["totals"]["clicks"]) == (GO, 3)

    def test_the_generated_tools_take_it_too(self):
        pytest.importorskip("fastmcp")
        from mcp_server.server import _build_mcp_server

        tools = {tool.name: tool for tool in asyncio.run(_build_mcp_server().list_tools())}

        for name in (
            "get_url",
            "update_url",
            "delete_url",
            "list_redirect_rules",
            "get_url_daily_stats",
        ):
            assert "domain" in tools[name].parameters["properties"], name

    def test_bulk_tagging_says_when_to_name_domains(self):
        """An assistant reads this: plain codes take one link each, by the default rule."""
        pytest.importorskip("fastmcp")
        from mcp_server.server import _build_mcp_server

        tools = {tool.name: tool for tool in asyncio.run(_build_mcp_server().list_tools())}

        assert "`links`" in tools["bulk_tag_urls"].description
        assert "one link per code" in tools["bulk_tag_urls"].description


class TestBulkTagging:
    @pytest.fixture
    def tag(self, db_session, test_user) -> Tag:
        tag = Tag(name="q4", display_name="Q4", color="gray-500", created_by=test_user.id)
        db_session.add(tag)
        db_session.commit()
        return tag

    def test_links_name_their_domain(self, client, auth_headers, db_session, both, tag):
        body = {"links": [{"short_code": "promo", "domain": GO}], "tag_ids": [str(tag.id)]}

        assert (
            client.post("/api/v1/urls/bulk/tags", json=body, headers=auth_headers).json()["updated"]
            == 1
        )

        db_session.expire_all()
        assert ([t.name for t in both[0].tags], [t.name for t in both[1].tags]) == ([], ["q4"])

    def test_plain_codes_take_one_link_each_by_the_default_rule(
        self, client, auth_headers, db_session, both, tag
    ):
        body = {"short_codes": ["promo"], "tag_ids": [str(tag.id)]}

        assert (
            client.post("/api/v1/urls/bulk/tags", json=body, headers=auth_headers).json()["updated"]
            == 1
        )

        db_session.expire_all()
        assert ([t.name for t in both[0].tags], [t.name for t in both[1].tags]) == (["q4"], [])


class TestShortUrls:
    def test_each_link_on_its_own_domain(self, client, auth_headers, both):
        items = client.get("/api/v1/urls", headers=auth_headers).json()["urls"]

        assert sorted((item["domain"], item["short_url"]) for item in items) == sorted(
            [
                (settings.default_domain, f"https://{settings.default_domain}/promo"),
                (GO, f"https://{GO}/promo"),
            ]
        )

    def test_base_url_moves_only_the_default_domains_links(
        self, client, auth_headers, both, monkeypatch
    ):
        """BASE_URL is for staging and local runs of the default domain."""
        monkeypatch.setattr(settings, "base_url", "http://localhost:8000")

        items = client.get("/api/v1/urls", headers=auth_headers).json()["urls"]

        assert sorted(item["short_url"] for item in items) == [
            "http://localhost:8000/promo",
            f"https://{GO}/promo",
        ]

    def test_campaigns(self, client, auth_headers, db_session, test_user, domains):
        campaign = Campaign(
            name="Q4",
            original_url="https://example.com/",
            csv_columns=["name"],
            created_by=test_user.id,
        )
        db_session.add(campaign)
        db_session.commit()
        _link(
            db_session,
            test_user,
            domains[1],
            code="ana",
            campaign_id=campaign.id,
            user_data={"name": "Ana"},
        )

        detail = client.get(f"/api/v1/campaigns/{campaign.id}", headers=auth_headers).json()
        export = client.get(f"/api/v1/campaigns/{campaign.id}/export", headers=auth_headers).text

        assert (detail["urls"][0]["short_url"], detail["urls"][0]["domain"]) == (
            f"https://{GO}/ana",
            GO,
        )
        assert f"https://{GO}/ana" in export

    def test_the_overview(self, client, auth_headers, db_session, both):
        _visits(db_session, both[1], 3)

        (top, *_) = client.get("/api/v1/analytics/overview", headers=auth_headers).json()[
            "top_urls"
        ]

        assert (top["short_url"], top["domain"]) == (f"https://{GO}/promo", GO)

    def test_a_crawlers_preview_names_the_domain_it_was_asked_on(self, client, both):
        response = client.get(
            "/promo",
            headers={"host": GO, "user-agent": "facebookexternalhit/1.1"},
            follow_redirects=False,
        )

        assert f"https://{GO}/promo" in response.text
