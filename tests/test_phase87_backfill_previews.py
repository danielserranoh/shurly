"""
Phase 8.7 — `python -m server.tools.previews backfill`: the page's own preview and icon for the
links made before 8.7 (the ones imported from Shlink had none), and their old og_* values separated.

- Each distinct destination is fetched once, a few at a time, and its page cached on every link
  with that URL.
- A link whose og_fetched_at is set had its og_* copied from the page: each value that equals the
  page's now is cleared; one that differs stays, an override. Without og_fetched_at they all stay.
- A page that doesn't answer leaves its links as they were.
- Re-runnable: a second run refreshes the page's values and clears nothing new.
- A dry run unless --for-real. What it prints are counts, never a destination.
"""

import asyncio
from datetime import datetime, timedelta, timezone

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


COPIED = datetime.now(timezone.utc) - timedelta(days=30)  # og_fetched_at: copied at create


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
        down = link("down", DOWN, og_title="Kept", og_fetched_at=COPIED)

        counts = previews.backfill(db_session, for_real=True)

        down = _fresh(db_session, down)
        assert (down.page_fetched_at, down.og_title) == (None, "Kept")
        assert down.og_fetched_at is not None  # a later run separates it
        assert (counts["urls_failed"], counts["links_unanswered"]) == (1, 1)


class TestSeparatingTheOldValues:
    def test_a_copy_of_the_pages_is_cleared(self, db_session, link, pages):
        copied = link(
            "old",
            og_title="The article",
            og_description="What it's about",
            og_image_url="https://example.com/img/share.png",
            og_fetched_at=COPIED,
        )

        counts = previews.backfill(db_session, for_real=True)

        copied = _fresh(db_session, copied)
        assert (copied.og_title, copied.og_description, copied.og_image_url) == (None,) * 3
        assert copied.has_custom_preview is False
        assert copied.og_fetched_at is None
        assert (counts["overrides_cleared"], counts["overrides_kept"]) == (3, 0)

    def test_one_that_differs_stays_an_override(self, db_session, link, pages):
        """The page changed its description since, or a person edited it: nobody's text is lost."""
        edited = link(
            "edited",
            og_title="The article",
            og_description="Our own words",
            og_fetched_at=COPIED,
        )

        counts = previews.backfill(db_session, for_real=True)

        edited = _fresh(db_session, edited)
        assert (edited.og_title, edited.og_description) == (None, "Our own words")
        assert (counts["overrides_cleared"], counts["overrides_kept"]) == (1, 1)

    def test_a_relative_image_copied_as_written(self, db_session, link, pages):
        copied = link("rel", og_image_url="/img/share.png", og_fetched_at=COPIED)

        previews.backfill(db_session, for_real=True)

        assert _fresh(db_session, copied).og_image_url is None

    def test_without_og_fetched_at_a_person_typed_them(self, db_session, link, pages):
        typed = link("typed", og_title="The article", og_description="Ours")

        counts = previews.backfill(db_session, for_real=True)

        typed = _fresh(db_session, typed)
        assert (typed.og_title, typed.og_description) == ("The article", "Ours")
        assert (counts["overrides_cleared"], counts["overrides_kept"]) == (0, 2)


class TestRunningAgain:
    def test_refreshes_the_page_and_clears_nothing_new(self, db_session, link, pages):
        url = link("again", og_title="The article", og_description="Ours", og_fetched_at=COPIED)
        previews.backfill(db_session, for_real=True)

        # The page's title is now the one the override kept... and it changed its image.
        pages.pages[ARTICLE] = OpenGraphMetadata(title="Ours", description="Ours")
        counts = previews.backfill(db_session, for_real=True)

        url = _fresh(db_session, url)
        assert url.og_description == "Ours"  # kept: no longer a candidate copy
        assert (url.page_og_title, url.page_og_image_url) == ("Ours", None)
        assert (counts["overrides_cleared"], counts["overrides_kept"]) == (0, 1)


class TestDryRun:
    def test_reports_and_writes_nothing(self, db_session, link, pages):
        url = link("dry", og_title="The article", og_fetched_at=COPIED)

        counts = previews.backfill(db_session)

        url = _fresh(db_session, url)
        assert (url.og_title, url.page_fetched_at) == ("The article", None)
        assert url.og_fetched_at is not None
        assert (counts["links_done"], counts["overrides_cleared"]) == (1, 1)


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
