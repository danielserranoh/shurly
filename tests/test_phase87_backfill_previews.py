"""
Phase 8.7 — `python -m server.tools.previews backfill`: the page's own preview and icon for every
link (the ones imported from Shlink had none).

- Each distinct destination is fetched once, a few at a time, and its page cached on every link
  with that URL.
- The overrides (og_*, what a person typed) are never touched, even one that equals the page's.
- A page that doesn't answer leaves its links as they were.
- Re-runnable: a second run refreshes the page's values.
- A dry run unless --for-real. What it prints are counts, never a destination.
"""

import asyncio

import pytest

from server.core.models import URL, URLType
from server.tools import previews
from server.utils.domain import get_or_create_default_domain
from server.utils.opengraph import OpenGraphMetadata
from tests.conftest import TestingSessionLocal

ARTICLE = "https://example.com/article?email=jane.doe@example.com"
HOME = "https://example.org/"
DOWN = "https://down.example.net/"

PAGES = {
    ARTICLE: OpenGraphMetadata(
        title="The article",
        description="What it's about",
        image_url="https://example.com/img/share.png",
        favicon_url="https://example.com/favicon.svg",
    ),
    HOME: OpenGraphMetadata(favicon_url="https://example.org/favicon.ico"),  # an icon, no preview
    DOWN: OpenGraphMetadata.failed(),
}


class FakePages:
    def __init__(self, pages=PAGES):
        self.pages = dict(pages)
        self.asked: list[str] = []
        self.in_flight = self.most_in_flight = 0

    async def fetch(self, url):
        self.asked.append(url)
        self.in_flight += 1
        self.most_in_flight = max(self.most_in_flight, self.in_flight)
        await asyncio.sleep(0.01)
        self.in_flight -= 1
        return self.pages[url]


@pytest.fixture
def pages(monkeypatch) -> FakePages:
    fake = FakePages()
    monkeypatch.setattr(previews, "fetch", fake.fetch)
    monkeypatch.setattr(previews, "session_factory", TestingSessionLocal)
    return fake


@pytest.fixture
def link(db_session, test_user):
    def make(code: str, original: str = ARTICLE, **extra) -> URL:
        url = URL(
            short_code=code,
            original_url=original,
            url_type=extra.pop("url_type", URLType.STANDARD),
            created_by=test_user.id,
            domain_id=get_or_create_default_domain(db_session).id,
            **extra,
        )
        db_session.add(url)
        db_session.commit()
        return url

    return make


def _fresh(db_session, url: URL) -> URL:
    db_session.expire_all()
    return db_session.get(URL, url.id)


class TestTheFetch:
    def test_each_destination_once_on_every_link_with_it(self, db_session, link, pages):
        imported = [link(f"shl{i}") for i in range(3)]  # from Shlink: nothing stored
        campaign = link("cmp1", url_type=URLType.CAMPAIGN)
        home = link("home", HOME)

        counts = previews.backfill(db_session, for_real=True)

        assert sorted(pages.asked) == sorted([ARTICLE, HOME])
        for url in [*imported, campaign]:
            url = _fresh(db_session, url)
            assert url.page_og_title == "The article"
            assert url.page_og_image_url == "https://example.com/img/share.png"
            assert url.page_favicon_url == "https://example.com/favicon.svg"
            assert url.page_fetched_at is not None
        home = _fresh(db_session, home)
        assert (home.page_og_title, home.page_favicon_url) == (
            None,
            "https://example.org/favicon.ico",
        )
        assert (counts["links"], counts["urls"], counts["links_done"]) == (5, 2, 5)
        assert (counts["urls_with_preview"], counts["urls_with_icon"]) == (1, 2)

    def test_a_few_at_a_time(self, db_session, link, pages):
        pages.pages = {f"https://site{i}.example.com/": OpenGraphMetadata() for i in range(10)}
        for i in range(10):
            link(f"l{i}", f"https://site{i}.example.com/")

        previews.backfill(db_session, concurrency=3, for_real=True)

        assert len(pages.asked) == 10
        assert pages.most_in_flight == 3

    def test_a_page_that_doesnt_answer_leaves_its_links(self, db_session, link, pages):
        down = link("down", DOWN, og_title="Kept", page_og_title="From before")

        counts = previews.backfill(db_session, for_real=True)

        down = _fresh(db_session, down)
        assert (down.page_fetched_at, down.og_title) == (None, "Kept")
        assert down.page_og_title == "From before"  # a later run refreshes it
        assert (counts["urls_failed"], counts["links_unanswered"]) == (1, 1)


class TestTheOverrides:
    def test_are_never_touched(self, db_session, link, pages):
        """Even one that equals the page's: a person typed it, and only a person clears it."""
        typed = link(
            "typed",
            og_title="The article",
            og_description="Our own words",
            og_image_url="/img/share.png",
        )

        counts = previews.backfill(db_session, for_real=True)

        typed = _fresh(db_session, typed)
        assert (typed.og_title, typed.og_description, typed.og_image_url) == (
            "The article",
            "Our own words",
            "/img/share.png",
        )
        assert typed.page_og_title == "The article"
        assert typed.has_custom_preview is True
        assert counts["links_done"] == 1


class TestRunningAgain:
    def test_refreshes_the_page(self, db_session, link, pages):
        url = link("again", og_description="Ours")
        previews.backfill(db_session, for_real=True)

        # The page changed its title, and dropped its image.
        pages.pages[ARTICLE] = OpenGraphMetadata(title="Retitled", description="New words")
        counts = previews.backfill(db_session, for_real=True)

        url = _fresh(db_session, url)
        assert (url.page_og_title, url.page_og_image_url) == ("Retitled", None)
        assert url.og_description == "Ours"
        assert counts["links_done"] == 1


class TestDryRun:
    def test_reports_and_writes_nothing(self, db_session, link, pages):
        url = link("dry", og_title="Typed")

        counts = previews.backfill(db_session)

        url = _fresh(db_session, url)
        assert (url.og_title, url.page_og_title, url.page_fetched_at) == ("Typed", None, None)
        assert counts["links_done"] == 1


class TestTheCommand:
    def test_counts_never_a_destination(self, db_session, link, pages, capsys):
        link("cmd1")
        link("cmd2", DOWN)

        assert previews.main(["backfill"]) == 0

        out = capsys.readouterr().out
        assert "2 links, 2 distinct destinations fetched" in out
        assert "1 that didn't answer" in out
        assert "Dry run: nothing was written" in out
        assert "example.com" not in out and "jane.doe" not in out
        assert (
            _fresh(
                db_session, db_session.query(URL).filter_by(short_code="cmd1").one()
            ).page_fetched_at
            is None
        )

    def test_for_real_writes(self, db_session, link, pages, capsys):
        url = link("cmd3")

        assert previews.main(["backfill", "--for-real", "--concurrency", "2"]) == 0

        assert "Dry run" not in capsys.readouterr().out
        assert _fresh(db_session, url).page_og_title == "The article"

    def test_concurrency_must_be_positive(self, pages):
        with pytest.raises(SystemExit) as exit_:
            previews.main(["backfill", "--concurrency", "0"])
        assert exit_.value.code == 2
