"""
Phase 8.3 — the cutover's default domain (ROADMAP 8.5). `python -m server.tools.domains promote
go.griddo.io` makes go.griddo.io the domain new links go on, and s.griddo.io stops being it. In
production it runs as a one-off ECS task, scripts/run_promote_domain.sh
(tests/test_run_promote_domain.py).

- A dry run unless --for-real. It makes the domain's row when it's missing; a second run does nothing.
- What the default decides changes at once, without a restart: the domain of new links (the API's, a
  campaign's, the MCP's), the link a code names when the API isn't told the domain (`find_url`), and
  where a request on a host Shurly doesn't know looks.
- What it doesn't change: a link keeps its domain, so s.griddo.io's keep resolving there. A restart
  with the old DEFAULT_DOMAIN keeps the new default. BASE_URL moves only DEFAULT_DOMAIN's links, before
  DEFAULT_DOMAIN moves too and after.
"""

import pytest

from server.app import urls as urls_module
from server.core.config import settings
from server.core.models import URL, Domain, URLType
from server.tools import domains
from server.utils.domain import backfill_campaign_url_domains, get_or_create_default_domain
from server.utils.opengraph import OpenGraphMetadata
from tests.conftest import TestingSessionLocal

S, GO = "s.griddo.io", "go.griddo.io"


@pytest.fixture(autouse=True)
def production(monkeypatch):
    """As production is before the cutover: DEFAULT_DOMAIN is s.griddo.io, and no BASE_URL."""
    monkeypatch.setattr(settings, "default_domain", S)
    monkeypatch.setattr(settings, "base_url", "")
    monkeypatch.setattr(domains, "session_factory", TestingSessionLocal)


def _link(db, user, domain: Domain | None, code: str) -> URL:
    url = URL(
        short_code=code,
        original_url=f"https://example.com/{domain.hostname if domain else 'legacy'}/{code}",
        url_type=URLType.STANDARD,
        created_by=user.id,
        domain_id=domain.id if domain else None,
    )
    db.add(url)
    db.commit()
    return url


@pytest.fixture
def before(db_session, test_user) -> dict[str, URL]:
    """s.griddo.io the default, with a test link. go.griddo.io as the Shlink import leaves it: not
    the default, with its links, their codes' case kept."""
    s = get_or_create_default_domain(db_session)
    go = Domain(hostname=GO, is_default=False)
    db_session.add(go)
    db_session.commit()
    return {
        S: _link(db_session, test_user, s, "test01"),
        GO: _link(db_session, test_user, go, "Promo"),
    }


@pytest.fixture
def promote(db_session):
    """Runs the tool, then reads the database afresh, as the app's next request does."""

    def run(*args: str) -> int:
        exit_code = domains.main(["promote", *args])
        db_session.expire_all()
        return exit_code

    return run


def _defaults(db) -> list[str]:
    return sorted(host for (host,) in db.query(Domain.hostname).filter(Domain.is_default.is_(True)))


def _hostnames(db) -> list[str]:
    return sorted(host for (host,) in db.query(Domain.hostname))


class TestPromote:
    def test_a_dry_run_by_default(self, db_session, before, promote, capsys):
        assert promote(GO) == 0

        assert _defaults(db_session) == [S]
        assert "Dry run: nothing was written." in capsys.readouterr().out

    def test_for_real_go_is_the_default_and_s_is_not(self, db_session, before, promote, capsys):
        assert promote(GO, "--for-real") == 0

        assert _defaults(db_session) == [GO]
        assert f"{GO} is the default domain now, and {S} isn't." in capsys.readouterr().out

    def test_every_link_keeps_its_domain(self, db_session, before, promote):
        promote(GO, "--for-real")

        assert {url.short_code: url.domain.hostname for url in db_session.query(URL)} == {
            "test01": S,
            "Promo": GO,
        }

    def test_a_second_run_does_nothing(self, db_session, before, promote, capsys):
        promote(GO, "--for-real")
        capsys.readouterr()

        assert promote(GO, "--for-real") == 0

        assert _defaults(db_session) == [GO]
        assert f"{GO} is the default domain already: nothing to do." in capsys.readouterr().out

    def test_it_makes_the_domain_when_its_missing(self, db_session, promote, capsys):
        get_or_create_default_domain(db_session)  # s.griddo.io, and nothing imported

        assert promote(GO, "--for-real") == 0

        assert (_hostnames(db_session), _defaults(db_session)) == ([GO, S], [GO])
        assert f"{GO} isn't a domain here yet" in capsys.readouterr().out

    def test_a_dry_run_doesnt_make_it(self, db_session, promote, capsys):
        get_or_create_default_domain(db_session)

        promote(GO)

        assert _hostnames(db_session) == [S]
        assert f"{GO} isn't a domain here yet" in capsys.readouterr().out

    @pytest.mark.parametrize("written", ["GO.Griddo.IO", "go.griddo.io.", "go.griddo.io:443"])
    def test_the_domain_is_read_as_a_requests_host_is(self, db_session, before, promote, written):
        assert promote(written, "--for-real") == 0

        assert (_hostnames(db_session), _defaults(db_session)) == ([GO, S], [GO])

    @pytest.mark.parametrize(
        "written",
        [
            "https://go.griddo.io",
            "go.griddo.io/x",
            "go griddo.io",
            "go-.griddo.io",
            "localhost",
            "",
        ],
    )
    def test_what_isnt_a_domain_is_refused(self, db_session, before, promote, written, capsys):
        with pytest.raises(SystemExit) as exited:
            promote(written, "--for-real")

        assert exited.value.code == 2
        assert "isn't a domain" in capsys.readouterr().err
        assert (_hostnames(db_session), _defaults(db_session)) == ([GO, S], [S])

    def test_two_defaults_are_mended(self, db_session, before, promote):
        """Nothing in the schema stops two rows marked default. After a promotion, one is."""
        db_session.add(Domain(hostname="old.griddo.io", is_default=True))
        db_session.commit()

        promote(GO, "--for-real")

        assert _defaults(db_session) == [GO]


class TestWhatItSays:
    def test_the_domains_their_links_and_what_changes(self, before, promote, capsys):
        promote(GO)

        output = capsys.readouterr().out
        assert f"{S}: the default, 1 link" in output
        assert f"{GO}: 1 link" in output
        assert f"{GO} becomes the default domain, and {S} stops being it." in output
        assert f"{S}'s keep resolving there" in output

    def test_it_says_to_move_default_domain_too(self, before, promote, capsys, monkeypatch):
        promote(GO)
        assert f"DEFAULT_DOMAIN is {S} here: set it to {GO}" in capsys.readouterr().out

        monkeypatch.setattr(settings, "default_domain", GO)
        promote(GO)
        assert "DEFAULT_DOMAIN" not in capsys.readouterr().out

    def test_links_from_before_domains_are_counted(
        self, db_session, test_user, before, promote, capsys
    ):
        """They count as the default domain's (`find_url`), and so move with it."""
        _link(db_session, test_user, None, "old001")

        promote(GO)

        assert f"1 link from before domains counts as {GO}'s" in capsys.readouterr().out


@pytest.fixture
def no_og_fetch(monkeypatch):
    """Creating a link fetches its preview: never over the network in tests."""

    async def _empty(*_args, **_kwargs):
        return OpenGraphMetadata()

    monkeypatch.setattr(urls_module, "fetch_opengraph_metadata", _empty)


class TestWhatTheDefaultDecides:
    """From the next request on, without a restart."""

    def test_new_links_go_on_go(self, client, auth_headers, before, promote, no_og_fetch):
        promote(GO, "--for-real")

        standard = client.post(
            "/api/v1/urls", json={"url": "https://example.com/new"}, headers=auth_headers
        )
        custom = client.post(
            "/api/v1/urls/custom",
            json={"url": "https://example.com/new", "custom_code": "spring"},
            headers=auth_headers,
        )

        for response in (standard, custom):
            assert response.status_code == 201, response.text
            link = response.json()
            assert (link["domain"], link["short_url"]) == (GO, f"https://{GO}/{link['short_code']}")

    def test_a_campaigns_links_too(self, client, auth_headers, db_session, before, promote):
        promote(GO, "--for-real")

        response = client.post(
            "/api/v1/campaigns",
            json={
                "name": "Q4",
                "original_url": "https://example.com/",
                "csv_data": "email\na@b.co",
            },
            headers=auth_headers,
        )

        assert response.status_code == 201, response.text
        (link,) = db_session.query(URL).filter(URL.url_type == URLType.CAMPAIGN)
        assert link.domain.hostname == GO

    def test_the_mcps_campaigns_too(self, db_session, test_user, before, promote):
        pytest.importorskip("fastmcp")
        from mcp_server import curated

        promote(GO, "--for-real")
        curated.create_campaign_from_rows(
            db_session,
            test_user,
            name="Rows",
            original_url="https://example.com",
            rows=[{"a": "1"}],
        )

        (link,) = db_session.query(URL).filter(URL.url_type == URLType.CAMPAIGN)
        assert link.domain.hostname == GO

    def test_a_code_on_both_domains_names_gos_link_unless_told(
        self, client, auth_headers, db_session, test_user, before, promote
    ):
        s, go = (db_session.query(Domain).filter(Domain.hostname == host).one() for host in (S, GO))
        _link(db_session, test_user, s, "both01")
        _link(db_session, test_user, go, "both01")
        assert client.get("/api/v1/urls/both01", headers=auth_headers).json()["domain"] == S

        promote(GO, "--for-real")

        plain = client.get("/api/v1/urls/both01", headers=auth_headers).json()
        named = client.get(f"/api/v1/urls/both01?domain={S}", headers=auth_headers).json()
        assert (plain["domain"], named["domain"]) == (GO, S)

    def test_s_links_keep_resolving_on_s(self, client, before, promote):
        promote(GO, "--for-real")

        on_s = client.get("/test01", headers={"Host": S}, follow_redirects=False)
        on_go = client.get("/Promo", headers={"Host": GO}, follow_redirects=False)
        pixel = client.get("/test01/track", headers={"Host": S})

        assert (on_s.status_code, on_s.headers["location"]) == (302, before[S].original_url)
        assert (on_go.status_code, on_go.headers["location"]) == (302, before[GO].original_url)
        assert pixel.status_code == 200

    def test_a_host_shurly_doesnt_know_looks_on_go(self, client, before, promote):
        """An unknown host falls back to the default domain (3.10.1): go.griddo.io's links, now."""
        unknown = {"Host": "unknown.example"}
        assert client.get("/Promo", headers=unknown, follow_redirects=False).status_code == 404

        promote(GO, "--for-real")

        response = client.get("/Promo", headers=unknown, follow_redirects=False)
        assert (response.status_code, response.headers["location"]) == (
            302,
            before[GO].original_url,
        )


class TestWhatStays:
    def test_a_restart_with_the_old_default_domain_keeps_go(self, db_session, before, promote):
        """What startup does with domains (`main._seed_database`), DEFAULT_DOMAIN still s.griddo.io:
        the row marked default wins."""
        promote(GO, "--for-real")

        assert get_or_create_default_domain(db_session).hostname == GO
        backfill_campaign_url_domains(db_session)
        assert _defaults(db_session) == [GO]

    def test_base_url_moves_default_domains_links_before_it_moves_and_after(
        self, client, auth_headers, before, promote, monkeypatch
    ):
        """Every short URL is on its link's own domain. BASE_URL moves DEFAULT_DOMAIN's: s.griddo.io's
        until DEFAULT_DOMAIN moves too, then go.griddo.io's."""
        monkeypatch.setattr(settings, "base_url", "http://localhost:8000")
        promote(GO, "--for-real")

        def short_urls() -> dict[str, str]:
            items = client.get("/api/v1/urls", headers=auth_headers).json()["urls"]
            return {item["short_code"]: item["short_url"] for item in items}

        assert short_urls() == {
            "test01": "http://localhost:8000/test01",
            "Promo": f"https://{GO}/Promo",
        }
        monkeypatch.setattr(settings, "default_domain", GO)
        assert short_urls() == {
            "test01": f"https://{S}/test01",
            "Promo": "http://localhost:8000/Promo",
        }
        monkeypatch.setattr(settings, "base_url", "")
        assert short_urls() == {"test01": f"https://{S}/test01", "Promo": f"https://{GO}/Promo"}
