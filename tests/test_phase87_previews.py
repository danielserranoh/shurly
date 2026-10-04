"""
Phase 8.7 — previews from the page.

A link's social preview is the destination's own; Shurly's fields only rewrite it, or add one where
the page has none. Two layers per link: `og_*` hold only what a person typed (the overrides),
`page_*` cache what the page declares, its icon included. Each field's effective value is the
override, else the page's.

- Creating a link fetches the page every time, overrides or not, into `page_*`.
- refresh-preview replaces `page_*` with what the page declares now, and never touches an override;
  a fetch that failed leaves them. A new destination is fetched too.
- PATCH with an override null (or blank) drops it: the page's own shows again.
- A social crawler gets the redirect a person gets, and reads the page's own tags, unless something
  is rewritten: then Shurly's preview page, each field the override, else the page's.
"""

from datetime import datetime, timedelta, timezone

import pytest

from server.app import urls as urls_module
from server.core.config import settings
from server.core.models import URL, RedirectRule, URLType, Visitor
from server.utils.domain import get_or_create_default_domain
from server.utils.opengraph import OpenGraphMetadata

LINKEDIN = "LinkedInBot/1.0 (compatible; Mozilla/5.0; Apache-HttpClient +http://www.linkedin.com)"
BROWSER = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 Safari/605.1.15"

PAGE = OpenGraphMetadata(
    title="The page's title",
    description="The page's description",
    image_url="https://example.com/share.png",
    favicon_url="https://example.com/favicon.svg",
)


class FakePages:
    """The fetcher: `answers[url]` for a URL (PAGE by default), and what it was `asked`."""

    def __init__(self):
        self.answers: dict[str, OpenGraphMetadata] = {}
        self.asked: list[str] = []

    async def fetch(self, url):
        self.asked.append(url)
        return self.answers.get(url, PAGE)


@pytest.fixture
def pages(monkeypatch) -> FakePages:
    fake = FakePages()
    monkeypatch.setattr(urls_module, "fetch_opengraph_metadata", fake.fetch)
    return fake


def _link(db, user, code="pv1", **extra) -> URL:
    url = URL(
        short_code=code,
        original_url=extra.pop("original_url", "https://example.com/article"),
        url_type=URLType.STANDARD,
        created_by=user.id,
        domain_id=get_or_create_default_domain(db).id,
        **extra,
    )
    db.add(url)
    db.commit()
    return url


def _cached(**overrides) -> dict:
    """A link's page_* columns, as a fetch of PAGE left them."""
    return {
        "page_og_title": PAGE.title,
        "page_og_description": PAGE.description,
        "page_og_image_url": PAGE.image_url,
        "page_favicon_url": PAGE.favicon_url,
        "page_fetched_at": datetime.now(timezone.utc) - timedelta(days=1),
        **overrides,
    }


class TestCreating:
    def test_the_page_is_fetched_into_its_own_fields(self, client, auth_headers, pages):
        body = client.post(
            "/api/v1/urls", json={"url": "https://example.com/a"}, headers=auth_headers
        ).json()

        assert (body["og_title"], body["og_description"], body["og_image_url"]) == (None,) * 3
        assert body["page_og_title"] == "The page's title"
        assert body["page_og_description"] == "The page's description"
        assert body["page_og_image_url"] == "https://example.com/share.png"
        assert body["page_favicon_url"] == "https://example.com/favicon.svg"
        assert body["page_fetched_at"].endswith("Z")
        assert body["has_custom_preview"] is False

    def test_an_override_doesnt_stop_the_fetch(self, client, auth_headers, pages):
        """A title typed: the page's image still shows."""
        body = client.post(
            "/api/v1/urls",
            json={"url": "https://example.com/a", "og_title": "Mine"},
            headers=auth_headers,
        ).json()

        assert pages.asked == ["https://example.com/a"]
        assert (body["og_title"], body["page_og_title"]) == ("Mine", "The page's title")
        assert body["og_image_url"] is None
        assert body["page_og_image_url"] == "https://example.com/share.png"
        assert body["has_custom_preview"] is True

    def test_a_custom_code_too(self, client, auth_headers, pages):
        body = client.post(
            "/api/v1/urls/custom",
            json={"url": "https://example.com/a", "custom_code": "mine", "og_description": "D"},
            headers=auth_headers,
        ).json()

        assert (body["og_description"], body["page_og_title"]) == ("D", "The page's title")

    def test_a_blank_override_is_none(self, client, auth_headers, pages):
        body = client.post(
            "/api/v1/urls",
            json={"url": "https://example.com/a", "og_title": "  ", "og_image_url": ""},
            headers=auth_headers,
        ).json()

        assert (body["og_title"], body["og_image_url"], body["has_custom_preview"]) == (
            None,
            None,
            False,
        )

    def test_a_page_that_didnt_answer(self, client, auth_headers, pages):
        pages.answers["https://down.example.com/"] = OpenGraphMetadata.failed()

        body = client.post(
            "/api/v1/urls", json={"url": "https://down.example.com/"}, headers=auth_headers
        ).json()

        assert (body["page_og_title"], body["page_fetched_at"]) == (None, None)

    def test_a_long_title_is_cut_and_nul_dropped(self, client, auth_headers, pages):
        pages.answers["https://example.com/long"] = OpenGraphMetadata(title="T\x00" + "x" * 300)

        body = client.post(
            "/api/v1/urls", json={"url": "https://example.com/long"}, headers=auth_headers
        ).json()

        assert body["page_og_title"] == "T" + "x" * 254


class TestRefreshing:
    def test_the_pages_values_are_replaced(
        self, client, auth_headers, db_session, test_user, pages
    ):
        """What the page declares now, a field it dropped included: never only the empty ones."""
        _link(db_session, test_user, **_cached(page_og_title="Old title"))
        pages.answers["https://example.com/article"] = OpenGraphMetadata(title="New title")

        body = client.post("/api/v1/urls/pv1/refresh-preview", headers=auth_headers).json()

        assert body["og_title"] == body["page_og_title"] == "New title"
        assert body["og_image_url"] is body["page_og_image_url"] is None
        assert body["page_favicon_url"] is None
        assert body["has_custom_preview"] is False

    def test_the_overrides_are_never_touched(
        self, client, auth_headers, db_session, test_user, pages
    ):
        link = _link(db_session, test_user, og_title="Mine", **_cached())

        body = client.post("/api/v1/urls/pv1/refresh-preview", headers=auth_headers).json()

        assert body["og_title"] == "Mine"
        assert body["og_title_overridden"] is True
        assert body["og_image_url"] == PAGE.image_url
        assert body["og_image_url_overridden"] is False
        db_session.refresh(link)
        assert (link.og_title, link.og_description, link.og_image_url) == ("Mine", None, None)

    def test_a_failed_fetch_leaves_what_the_link_knew(
        self, client, auth_headers, db_session, test_user, pages
    ):
        link = _link(db_session, test_user, **_cached())
        fetched_at = link.page_fetched_at
        pages.answers["https://example.com/article"] = OpenGraphMetadata.failed()

        body = client.post("/api/v1/urls/pv1/refresh-preview", headers=auth_headers).json()

        assert body["page_og_title"] == PAGE.title
        db_session.refresh(link)
        assert link.page_fetched_at.replace(tzinfo=None) == fetched_at.replace(tzinfo=None)

    def test_the_old_og_fetched_at_isnt_written(
        self, client, auth_headers, db_session, test_user, pages
    ):
        link = _link(db_session, test_user)

        client.post("/api/v1/urls/pv1/refresh-preview", headers=auth_headers)

        db_session.refresh(link)
        assert link.og_fetched_at is None and link.page_fetched_at is not None


class TestThePreview:
    def test_each_field_the_override_else_the_pages(
        self, client, auth_headers, db_session, test_user
    ):
        _link(db_session, test_user, og_description="My description", **_cached())

        body = client.get("/api/v1/urls/pv1/preview", headers=auth_headers).json()

        assert body["og_title"] == PAGE.title
        assert body["og_description"] == "My description"
        assert body["og_image_url"] == PAGE.image_url
        assert (
            body["og_title_overridden"],
            body["og_description_overridden"],
            body["og_image_url_overridden"],
        ) == (False, True, False)
        assert body["has_custom_preview"] is True
        assert body["page_og_description"] == PAGE.description
        assert body["page_favicon_url"] == PAGE.favicon_url
        assert body["fetched_at"].endswith("Z")

    def test_no_page_title_the_links(self, client, auth_headers, db_session, test_user):
        _link(db_session, test_user, title="My link")

        body = client.get("/api/v1/urls/pv1/preview", headers=auth_headers).json()

        assert (body["og_title"], body["fetched_at"]) == ("My link", None)


class TestEditing:
    def test_null_overrides_go_back_to_the_pages_preview(
        self, client, auth_headers, db_session, test_user, pages
    ):
        _link(
            db_session,
            test_user,
            og_title="A",
            og_description="B",
            og_image_url="https://x.io/i.png",
        )

        body = client.patch(
            "/api/v1/urls/pv1",
            json={"og_title": None, "og_description": None, "og_image_url": None},
            headers=auth_headers,
        ).json()

        assert (body["og_title"], body["og_description"], body["og_image_url"]) == (None,) * 3
        assert body["has_custom_preview"] is False
        assert pages.asked == []  # the same destination: nothing fetched

    def test_blank_overrides_too(self, client, auth_headers, db_session, test_user, pages):
        _link(db_session, test_user, og_title="A")

        body = client.patch(
            "/api/v1/urls/pv1", json={"og_title": "", "og_image_url": "  "}, headers=auth_headers
        ).json()

        assert (body["og_title"], body["has_custom_preview"]) == (None, False)

    def test_a_new_destination_is_fetched(self, client, auth_headers, db_session, test_user, pages):
        _link(db_session, test_user, og_title="Kept", **_cached(page_og_title="Old page"))
        pages.answers["https://example.org/new"] = OpenGraphMetadata(title="New page")

        body = client.patch(
            "/api/v1/urls/pv1",
            json={"original_url": "https://example.org/new"},
            headers=auth_headers,
        ).json()

        assert pages.asked == ["https://example.org/new"]
        assert (body["page_og_title"], body["page_og_image_url"]) == ("New page", None)
        assert body["og_title"] == "Kept"

    def test_a_new_destination_that_didnt_answer_forgets_the_old_pages(
        self, client, auth_headers, db_session, test_user, pages
    ):
        _link(db_session, test_user, **_cached())
        pages.answers["https://example.org/new"] = OpenGraphMetadata.failed()

        body = client.patch(
            "/api/v1/urls/pv1",
            json={"original_url": "https://example.org/new"},
            headers=auth_headers,
        ).json()

        assert body["page_og_title"] is body["page_fetched_at"] is None

    def test_the_same_destination_isnt(self, client, auth_headers, db_session, test_user, pages):
        _link(db_session, test_user)

        client.patch(
            "/api/v1/urls/pv1",
            json={"original_url": "https://example.com/article", "title": "T"},
            headers=auth_headers,
        )

        assert pages.asked == []


class TestASocialCrawler:
    def _get(self, client, path, user_agent=LINKEDIN):
        return client.get(path, headers={"user-agent": user_agent}, follow_redirects=False)

    def test_nothing_rewritten_the_redirect_a_person_gets(self, client, db_session, test_user):
        _link(db_session, test_user, **_cached())

        crawler = self._get(client, "/pv1?utm_source=linkedin")
        person = self._get(client, "/pv1?utm_source=linkedin", BROWSER)

        assert crawler.status_code == person.status_code == 302
        assert crawler.headers["location"] == person.headers["location"]
        assert crawler.headers["location"] == "https://example.com/article?utm_source=linkedin"
        assert crawler.headers["cache-control"] == person.headers["cache-control"]

    def test_with_the_configured_status_and_cache(self, client, db_session, test_user, monkeypatch):
        monkeypatch.setattr(settings, "redirect_status_code", 301)
        monkeypatch.setattr(settings, "redirect_cache_lifetime", 600)
        _link(db_session, test_user)

        response = self._get(client, "/pv1")

        assert response.status_code == 301
        assert response.headers["cache-control"] == "public, max-age=600"

    def test_the_rules_pick_its_destination(self, client, db_session, test_user):
        link = _link(db_session, test_user)
        db_session.add(
            RedirectRule(
                url_id=link.id,
                priority=0,
                conditions=[{"type": "query_param", "param": "lang", "value": "es"}],
                target_url="https://example.com/es",
            )
        )
        db_session.commit()

        assert self._get(client, "/pv1?lang=es").headers["location"] == (
            "https://example.com/es?lang=es"
        )

    def test_its_visit_isnt_logged_as_before(self, client, db_session, test_user):
        _link(db_session, test_user)

        self._get(client, "/pv1")

        assert db_session.query(Visitor).count() == 0

    def test_something_rewritten_shurlys_preview_page(self, client, db_session, test_user):
        """Each field the override, else the page's: a title typed, the page's image."""
        _link(db_session, test_user, og_title="My title", **_cached())

        response = self._get(client, "/pv1")

        assert response.status_code == 200
        assert 'property="og:title" content="My title"' in response.text
        assert f'property="og:description" content="{PAGE.description}"' in response.text.replace(
            "&#39;", "'"
        )
        assert f'property="og:image" content="{PAGE.image_url}"' in response.text
        assert response.headers["cache-control"] == "public, max-age=300"

    def test_an_override_on_a_link_with_no_page_preview(self, client, db_session, test_user):
        _link(db_session, test_user, og_image_url="https://images.example.com/mine.png")

        response = self._get(client, "/pv1")

        assert 'property="og:image" content="https://images.example.com/mine.png"' in response.text
        assert 'property="og:title" content="https://example.com/article"' in response.text
