"""
Phase 8.5 — retiring a domain (ROADMAP 8.5): `python -m server.tools.domains retire HOST` deletes a
domain's row and its links, with everything that hangs off them, in one transaction. The interim
short domain went this way after the cutover, with no redirects kept. In production it runs as a
one-off ECS task, scripts/run_retire_domain.sh (tests/test_run_retire_domain.py).

- A dry run unless --for-real: the deletes run and roll back, so a dry run checks them too.
- It refuses the default domain (the row marked so, or DEFAULT_DOMAIN's) and a domain it doesn't
  know: nothing is written then, and it exits 1.
- What goes: the links on the domain, their visits, redirect rules and tag associations, campaign
  links among them. What stays: every other domain's links, links from before domains (they count
  as the default's), the tags and campaigns themselves, and orphan visits, which record no domain.
- The report names the links by code, with their counts, and what's deleted with them.
"""

import pytest

from server.core.config import settings
from server.core.models import (
    URL,
    Campaign,
    Domain,
    OrphanVisit,
    RedirectRule,
    Tag,
    URLType,
    Visitor,
    url_tags,
)
from server.tools import domains
from server.utils.domain import get_or_create_default_domain
from tests.conftest import TestingSessionLocal

GO, OLD = "go.griddo.io", "old.example.com"


@pytest.fixture(autouse=True)
def production(monkeypatch):
    """As production is after the cutover: go.griddo.io the default, in the database and in
    DEFAULT_DOMAIN."""
    monkeypatch.setattr(settings, "default_domain", GO)
    monkeypatch.setattr(settings, "base_url", "")
    monkeypatch.setattr(domains, "session_factory", TestingSessionLocal)


def _link(db, user, domain: Domain | None, code: str, campaign: Campaign | None = None) -> URL:
    url = URL(
        short_code=code,
        original_url=f"https://example.com/{domain.hostname if domain else 'legacy'}/{code}",
        url_type=URLType.CAMPAIGN if campaign else URLType.STANDARD,
        campaign_id=campaign.id if campaign else None,
        created_by=user.id,
        domain_id=domain.id if domain else None,
    )
    db.add(url)
    db.commit()
    return url


def _visit(db, url: URL, **flags) -> None:
    db.add(Visitor(url_id=url.id, short_code=url.short_code, ip="203.0.113.0", **flags))
    db.commit()


def _rule(db, url: URL) -> None:
    db.add(
        RedirectRule(
            url_id=url.id,
            priority=1,
            conditions=[{"type": "device", "value": "ios"}],
            target_url="https://example.com/ios",
        )
    )
    db.commit()


@pytest.fixture
def tag(db_session) -> Tag:
    tag = Tag(name="spring", display_name="Spring", color="blue-500")
    db_session.add(tag)
    db_session.commit()
    return tag


@pytest.fixture
def before(db_session, test_user, tag) -> dict[str, URL]:
    """go.griddo.io the default, with a link. old.example.com with two test links: one with
    visits, a redirect rule and a tag; the other with nothing. A link from before domains."""
    go = get_or_create_default_domain(db_session)
    old = Domain(hostname=OLD, is_default=False)
    db_session.add(old)
    db_session.commit()
    links = {
        "keep01": _link(db_session, test_user, go, "keep01"),
        "test01": _link(db_session, test_user, old, "test01"),
        "test02": _link(db_session, test_user, old, "test02"),
        "legacy": _link(db_session, test_user, None, "legacy"),
    }
    for code in ("keep01", "test01"):
        _visit(db_session, links[code])
        _rule(db_session, links[code])
        links[code].tags.append(tag)
    _visit(db_session, links["test01"], is_bot=True)
    _visit(db_session, links["test01"], is_pixel=True)
    db_session.commit()
    return links


@pytest.fixture
def retire(db_session):
    """Runs the tool, then reads the database afresh, as the app's next request does."""

    def run(*args: str) -> int:
        exit_code = domains.main(["retire", *args])
        db_session.expire_all()
        return exit_code

    return run


def _hostnames(db) -> list[str]:
    return sorted(host for (host,) in db.query(Domain.hostname))


def _codes(db) -> list[str]:
    return sorted(code for (code,) in db.query(URL.short_code))


def _visits(db) -> list[str]:
    return sorted(code for (code,) in db.query(Visitor.short_code))


def _rules(db) -> list[str]:
    return sorted(url.short_code for url in db.query(URL).join(RedirectRule))


def _tagged(db) -> list[str]:
    return sorted(code for (code,) in db.query(URL.short_code).join(url_tags))


class TestRetire:
    def test_a_dry_run_by_default(self, db_session, before, retire, capsys):
        assert retire(OLD) == 0

        assert _hostnames(db_session) == [GO, OLD]
        assert _codes(db_session) == ["keep01", "legacy", "test01", "test02"]
        assert _visits(db_session) == ["keep01", "test01", "test01", "test01"]
        assert "Dry run: nothing was written." in capsys.readouterr().out

    def test_for_real_the_domain_and_its_links_go(self, db_session, before, retire, capsys):
        assert retire(OLD, "--for-real") == 0

        assert _hostnames(db_session) == [GO]
        assert _codes(db_session) == ["keep01", "legacy"]
        assert f"{OLD} is retired" in capsys.readouterr().out

    def test_with_their_visits_rules_and_tag_associations(self, db_session, before, retire):
        retire(OLD, "--for-real")

        assert _visits(db_session) == ["keep01"]
        assert _rules(db_session) == ["keep01"]
        assert _tagged(db_session) == ["keep01"]

    def test_the_tags_themselves_stay(self, db_session, before, retire, tag):
        retire(OLD, "--for-real")

        assert [t.name for t in db_session.query(Tag).filter(Tag.id == tag.id)] == ["spring"]

    def test_its_campaign_links_go_and_the_campaign_stays(
        self, db_session, test_user, before, retire, capsys
    ):
        campaign = Campaign(
            name="Q4", original_url="https://example.com", csv_columns=[], created_by=test_user.id
        )
        db_session.add(campaign)
        db_session.commit()
        go, old = (db_session.query(Domain).filter(Domain.hostname == h).one() for h in (GO, OLD))
        _link(db_session, test_user, old, "q4old1", campaign)
        _link(db_session, test_user, go, "q4go01", campaign)

        retire(OLD, "--for-real")

        assert [url.short_code for url in db_session.get(Campaign, campaign.id).urls] == ["q4go01"]
        assert "Q4: 1 of its 2 links" in capsys.readouterr().out

    def test_orphan_visits_stay(self, db_session, before, retire, capsys):
        """An orphan visit records no domain: none can be told to be the retired one's."""
        db_session.add(OrphanVisit(type="invalid_short_url", attempted_path="/test03"))
        db_session.commit()

        retire(OLD, "--for-real")

        assert db_session.query(OrphanVisit).count() == 1
        assert "Orphan visits record no domain" in capsys.readouterr().out

    def test_its_links_stop_resolving_on_its_host(self, client, before, retire):
        """A request on a host Shurly doesn't know looks on the default domain: test01 isn't
        there."""
        on_old = client.get("/test01", headers={"Host": OLD}, follow_redirects=False)
        assert on_old.status_code == 302

        retire(OLD, "--for-real")

        on_old = client.get("/test01", headers={"Host": OLD}, follow_redirects=False)
        on_go = client.get("/keep01", headers={"Host": GO}, follow_redirects=False)
        assert (on_old.status_code, on_go.status_code) == (404, 302)

    def test_a_second_run_finds_no_domain(self, db_session, before, retire, capsys):
        retire(OLD, "--for-real")
        capsys.readouterr()

        assert retire(OLD, "--for-real") == 1

        assert f"{OLD} isn't a domain here" in capsys.readouterr().err

    @pytest.mark.parametrize(
        "written", ["OLD.Example.COM", "old.example.com.", "old.example.com:443"]
    )
    def test_the_domain_is_read_as_a_requests_host_is(self, db_session, before, retire, written):
        assert retire(written, "--for-real") == 0

        assert _hostnames(db_session) == [GO]


class TestWhatItRefuses:
    def _untouched(self, db) -> None:
        assert _hostnames(db) == [GO, OLD]
        assert _codes(db) == ["keep01", "legacy", "test01", "test02"]

    def test_the_default_domain(self, db_session, before, retire, capsys):
        assert retire(GO, "--for-real") == 1

        self._untouched(db_session)
        assert f"{GO} is the default domain" in capsys.readouterr().err

    def test_default_domains_host_even_unmarked(self, db_session, before, retire, monkeypatch):
        """DEFAULT_DOMAIN names the default when no row is marked, and the links from before
        domains count as its: retiring it would orphan them."""
        monkeypatch.setattr(settings, "default_domain", OLD)

        assert retire(OLD, "--for-real") == 1

        self._untouched(db_session)

    def test_an_unknown_domain(self, db_session, before, retire, capsys):
        assert retire("nope.example.com", "--for-real") == 1

        self._untouched(db_session)
        err = capsys.readouterr().err
        assert "nope.example.com isn't a domain here" in err
        assert f"{GO}, {OLD}" in err  # the ones there are

    @pytest.mark.parametrize("written", ["https://old.example.com", "old.example.com/x", "", "x"])
    def test_what_isnt_a_domain(self, db_session, before, retire, written, capsys):
        with pytest.raises(SystemExit) as exited:
            retire(written, "--for-real")

        assert exited.value.code == 2
        assert "isn't a domain" in capsys.readouterr().err
        self._untouched(db_session)


class TestWhatItSays:
    def test_the_links_by_code_with_their_counts(self, before, retire, capsys):
        retire(OLD)

        output = capsys.readouterr().out
        assert f"{OLD}: 2 links" in output
        assert "test01: 3 visits, 1 redirect rule, 1 tag" in output
        assert "test02: 0 visits, 0 redirect rules, 0 tags" in output
        assert "keep01" not in output and "legacy" not in output

    def test_what_would_be_deleted(self, before, retire, capsys):
        retire(OLD)

        output = capsys.readouterr().out
        assert (
            f"Retiring {OLD} deletes its row and 2 links, with 3 visits, 1 redirect rule and "
            "1 tag association." in output
        )
        assert "--for-real deletes it" in output

    def test_what_was_deleted(self, before, retire, capsys):
        retire(OLD, "--for-real")

        output = capsys.readouterr().out
        assert (
            f"{OLD} is retired: its row and 2 links are deleted, with 3 visits, 1 redirect rule "
            "and 1 tag association." in output
        )
        assert "Dry run" not in output

    def test_a_domain_with_no_links(self, db_session, retire, capsys):
        get_or_create_default_domain(db_session)
        db_session.add(Domain(hostname=OLD, is_default=False))
        db_session.commit()

        assert retire(OLD, "--for-real") == 0

        output = capsys.readouterr().out
        assert f"{OLD}: no links" in output
        assert f"{OLD} is retired: its row is deleted." in output
        assert _hostnames(db_session) == [GO]

    def test_it_prints_no_destination(self, before, retire, capsys):
        """Codes and counts only: a destination can carry a recipient's details."""
        retire(OLD)

        assert "https://" not in capsys.readouterr().out
