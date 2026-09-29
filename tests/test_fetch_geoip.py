"""
Phase 8.4 — scripts/fetch_geoip.py, which the image build runs:
- DB-IP's IP to Country Lite, this month's or last month's, installed only once it opens and
  knows that 8.8.8.8 is in the US;
- MaxMind's GeoLite2 City, with its account ID and licence key (sent to MaxMind only, never
  printed), installed only once it matches MaxMind's SHA-256, knows 8.8.8.8 and is less than
  25 days old.
It never fails: without GeoLite2 the app falls back to DB-IP; without either, no country.
Both are asked with the script's own User-Agent: download.db-ip.com answers Python's default
with a 403.
"""

import base64
import gzip
import hashlib
import importlib.util
import io
import tarfile
import threading
import time
from datetime import date
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import ProxyHandler, build_opener

import pytest

from tests.test_geolocation import write_database

_spec = importlib.util.spec_from_file_location(
    "fetch_geoip", Path(__file__).parents[1] / "scripts" / "fetch_geoip.py"
)
fetch_geoip = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(fetch_geoip)

TODAY = date(2026, 9, 28)
SEPTEMBER = "https://download.db-ip.com/free/dbip-country-lite-2026-09.mmdb.gz"
AUGUST = "https://download.db-ip.com/free/dbip-country-lite-2026-08.mmdb.gz"


class FakeDBIP:
    """download.db-ip.com: the months it has, gzipped; a 404 for the others; a 403 for
    Python's default User-Agent, which urllib sends when the request names none."""

    def __init__(self, files: dict[str, bytes]):
        self.files = files
        self.asked: list[str] = []

    def __call__(self, request, timeout=None):
        url = request.full_url
        self.asked.append(url)
        agent = request.get_header("User-agent") or "Python-urllib/3"
        if agent.startswith("Python-urllib"):
            raise HTTPError(url, 403, "Forbidden", {}, None)
        if url not in self.files:
            raise HTTPError(url, 404, "Not Found", {}, None)
        return io.BytesIO(gzip.compress(self.files[url]))


def database(tmp_path, networks) -> bytes:
    return write_database(tmp_path / f"{len(networks)}.mmdb", networks).read_bytes()


def good(tmp_path) -> bytes:
    return database(tmp_path, {"8.8.8.0/24": "US", "203.0.113.0/24": "ES"})


def test_this_months_file(tmp_path):
    dbip = FakeDBIP({SEPTEMBER: good(tmp_path)})

    installed = fetch_geoip.fetch(tmp_path / "data", TODAY, opener=dbip)

    assert installed == tmp_path / "data" / "dbip-country-lite.mmdb"
    assert dbip.asked == [SEPTEMBER]


def test_last_months_while_this_months_isnt_out(tmp_path):
    dbip = FakeDBIP({AUGUST: good(tmp_path)})

    assert fetch_geoip.fetch(tmp_path / "data", TODAY, opener=dbip) is not None
    assert dbip.asked == [SEPTEMBER, AUGUST]


def test_january_falls_back_to_december():
    assert fetch_geoip.months(date(2027, 1, 3)) == ["2027-01", "2026-12"]


def test_a_file_that_doesnt_know_8_8_8_8_isnt_installed(tmp_path, capsys):
    wrong = database(tmp_path, {"8.8.8.0/24": "DE"})  # a wrong country, not just a missing one
    dbip = FakeDBIP({SEPTEMBER: wrong, AUGUST: b"not a database"})

    assert fetch_geoip.fetch(tmp_path / "data", TODAY, opener=dbip) is None

    assert not (tmp_path / "data" / "dbip-country-lite.mmdb").exists()
    output = capsys.readouterr().out
    assert "8.8.8.8" in output and "doesn't open" in output


def test_never_a_failure_and_a_file_already_there_stays(tmp_path, monkeypatch, capsys):
    installed = tmp_path / "data" / "dbip-country-lite.mmdb"
    installed.parent.mkdir()
    installed.write_bytes(b"last month's")
    monkeypatch.setattr(fetch_geoip, "urlopen", FakeDBIP({}))

    assert fetch_geoip.main([str(tmp_path / "data")]) == 0

    assert installed.read_bytes() == b"last month's"
    assert "visits will have no country" in capsys.readouterr().out


# ---------------------------------------------------------------------------
# MaxMind's GeoLite2 City
# ---------------------------------------------------------------------------

ACCOUNT, KEY = "123456", "marker-licence-key-XYZ"
ARCHIVE_URL = fetch_geoip.GEOLITE_URL.format(suffix="tar.gz")
CHECKSUM_URL = fetch_geoip.GEOLITE_URL.format(suffix="tar.gz.sha256")


def geolite_archive(
    tmp_path, networks=None, name="GeoLite2-City_20260929/GeoLite2-City.mmdb"
) -> bytes:
    """MaxMind's download: a gzipped tar with the database in a dated folder."""
    mmdb = write_database(
        tmp_path / "geolite.mmdb", networks or {"8.8.8.0/24": "US"}, "GeoLite2-City"
    ).read_bytes()
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w:gz") as tar:
        info = tarfile.TarInfo(name)
        info.size = len(mmdb)
        tar.addfile(info, io.BytesIO(mmdb))
    return buffer.getvalue()


class FakeMaxMind:
    """download.maxmind.com: the archive and its SHA-256, behind Basic auth."""

    def __init__(self, archive: bytes, status: int | None = None, checksum: str | None = None):
        self.archive, self.status = archive, status
        self.checksum = checksum or hashlib.sha256(archive).hexdigest()
        self.authorization: list[str | None] = []

    def __call__(self, request, timeout=None):
        self.authorization.append(request.get_header("Authorization"))
        if self.status:
            raise HTTPError(request.full_url, self.status, "No", {}, None)
        if request.full_url == CHECKSUM_URL:
            return io.BytesIO(f"{self.checksum}  GeoLite2-City_20260929.tar.gz\n".encode())
        assert request.full_url == ARCHIVE_URL
        return io.BytesIO(self.archive)


def test_geolite2_city_installed(tmp_path, capsys):
    maxmind = FakeMaxMind(geolite_archive(tmp_path))

    installed = fetch_geoip.fetch_geolite(tmp_path / "data", (ACCOUNT, KEY), opener=maxmind)

    assert installed == tmp_path / "data" / "GeoLite2-City.mmdb"
    assert "MaxMind GeoLite2 City, built" in capsys.readouterr().out


def test_the_credentials_go_to_maxmind_and_nowhere_else(tmp_path, capsys):
    maxmind = FakeMaxMind(geolite_archive(tmp_path))

    fetch_geoip.fetch_geolite(tmp_path / "data", (ACCOUNT, KEY), opener=maxmind)

    basic = "Basic " + base64.b64encode(f"{ACCOUNT}:{KEY}".encode()).decode()
    assert maxmind.authorization == [basic, basic]
    assert KEY not in capsys.readouterr().out


@pytest.mark.parametrize(
    "status, said", [(401, "refused the account ID or licence key"), (429, "too many downloads")]
)
def test_maxmind_refusing_says_why_and_installs_nothing(tmp_path, capsys, status, said):
    maxmind = FakeMaxMind(geolite_archive(tmp_path), status=status)

    assert fetch_geoip.fetch_geolite(tmp_path / "data", (ACCOUNT, KEY), opener=maxmind) is None

    output = capsys.readouterr().out
    assert said in output and KEY not in output
    assert not (tmp_path / "data" / "GeoLite2-City.mmdb").exists()


def test_a_checksum_that_isnt_maxminds_installs_nothing(tmp_path, capsys):
    maxmind = FakeMaxMind(geolite_archive(tmp_path), checksum="0" * 64)

    assert fetch_geoip.fetch_geolite(tmp_path / "data", (ACCOUNT, KEY), opener=maxmind) is None
    assert "SHA-256" in capsys.readouterr().out


def test_an_archive_without_the_database_installs_nothing(tmp_path, capsys):
    maxmind = FakeMaxMind(geolite_archive(tmp_path, name="GeoLite2-City_20260929/README.txt"))

    assert fetch_geoip.fetch_geolite(tmp_path / "data", (ACCOUNT, KEY), opener=maxmind) is None
    assert "no GeoLite2-City.mmdb" in capsys.readouterr().out


def test_a_copy_older_than_25_days_installs_nothing(tmp_path, capsys):
    maxmind = FakeMaxMind(geolite_archive(tmp_path))
    in_26_days = time.time() + 26 * 86400

    assert (
        fetch_geoip.fetch_geolite(tmp_path / "data", (ACCOUNT, KEY), opener=maxmind, now=in_26_days)
        is None
    )
    assert "more than 25" in capsys.readouterr().out


def test_one_that_doesnt_know_8_8_8_8_installs_nothing(tmp_path):
    maxmind = FakeMaxMind(geolite_archive(tmp_path, {"8.8.8.0/24": "DE"}))

    assert fetch_geoip.fetch_geolite(tmp_path / "data", (ACCOUNT, KEY), opener=maxmind) is None


def test_the_credentials_from_the_environment_or_the_builds_secrets(tmp_path, monkeypatch):
    secrets = tmp_path / "secrets"
    secrets.mkdir()
    monkeypatch.setattr(fetch_geoip, "SECRETS", secrets)
    monkeypatch.setenv("MAXMIND_ACCOUNT_ID", ACCOUNT)
    monkeypatch.setenv("MAXMIND_LICENSE_KEY", KEY)
    assert fetch_geoip.credentials() == (ACCOUNT, KEY)

    monkeypatch.delenv("MAXMIND_LICENSE_KEY")
    assert fetch_geoip.credentials() is None  # both, or neither
    monkeypatch.delenv("MAXMIND_ACCOUNT_ID")
    assert fetch_geoip.credentials() is None

    # The image build's: BuildKit mounts them as files, and an unset GitHub secret as an empty one.
    (secrets / "maxmind_account_id").write_text(ACCOUNT + "\n")
    (secrets / "maxmind_license_key").write_text("")
    assert fetch_geoip.credentials() is None
    (secrets / "maxmind_license_key").write_text(KEY + "\n")
    assert fetch_geoip.credentials() == (ACCOUNT, KEY)


def test_main_fetches_both_and_never_fails(tmp_path, monkeypatch, capsys):
    dbip = FakeDBIP(
        {
            f"https://download.db-ip.com/free/dbip-country-lite-{date.today():%Y-%m}.mmdb.gz": good(
                tmp_path
            )
        }
    )
    maxmind = FakeMaxMind(geolite_archive(tmp_path))
    monkeypatch.setattr(
        fetch_geoip,
        "urlopen",
        lambda request, timeout=None: (dbip if "db-ip.com" in request.full_url else maxmind)(
            request
        ),
    )
    monkeypatch.setenv("MAXMIND_ACCOUNT_ID", ACCOUNT)
    monkeypatch.setenv("MAXMIND_LICENSE_KEY", KEY)

    assert fetch_geoip.main([str(tmp_path / "data")]) == 0

    assert sorted(p.name for p in (tmp_path / "data").iterdir()) == [
        "GeoLite2-City.mmdb",
        "dbip-country-lite.mmdb",
    ]
    assert KEY not in capsys.readouterr().out


def test_without_credentials_countries_from_dbip(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(fetch_geoip, "urlopen", FakeDBIP({}))
    monkeypatch.delenv("MAXMIND_ACCOUNT_ID", raising=False)
    monkeypatch.delenv("MAXMIND_LICENSE_KEY", raising=False)
    monkeypatch.setattr(fetch_geoip, "SECRETS", tmp_path / "no-secrets")

    assert fetch_geoip.main([str(tmp_path / "data")]) == 0
    assert "No MaxMind credentials" in capsys.readouterr().out


# ---------------------------------------------------------------------------
# The real urllib, against a local stand-in for MaxMind's download
# ---------------------------------------------------------------------------


@pytest.fixture
def maxmind_server(tmp_path):
    """download.maxmind.com as it behaves: Basic auth, then a redirect to presigned storage,
    which answers a request that also carries an Authorization header with a 400."""
    archive = geolite_archive(tmp_path)
    files = {
        "tar.gz": archive,
        "tar.gz.sha256": f"{hashlib.sha256(archive).hexdigest()}  GeoLite2-City.tar.gz".encode(),
    }
    basic = "Basic " + base64.b64encode(f"{ACCOUNT}:{KEY}".encode()).decode()
    storage_saw: list[str | None] = []

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            path, _, suffix = self.path.partition("?suffix=")
            if path.endswith("/download"):
                if self.headers.get("Authorization") != basic:
                    return self._answer(401)
                self.send_response(302)
                self.send_header("Location", f"/storage/{suffix}")
                return self.end_headers()
            storage_saw.append(self.headers.get("Authorization"))
            if self.headers.get("Authorization"):
                return self._answer(400)
            self._answer(200, files[path.removeprefix("/storage/")])

        def _answer(self, status, body=b""):
            self.send_response(status)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}", storage_saw
    finally:
        server.shutdown()
        server.server_close()


def test_the_credentials_arent_forwarded_to_the_storage_maxmind_redirects_to(
    tmp_path, monkeypatch, maxmind_server
):
    base, storage_saw = maxmind_server
    monkeypatch.setattr(
        fetch_geoip, "GEOLITE_URL", base + "/geoip/databases/GeoLite2-City/download?suffix={suffix}"
    )
    urllib_itself = build_opener(ProxyHandler({})).open  # urlopen's handlers, minus any proxy

    installed = fetch_geoip.fetch_geolite(tmp_path / "data", (ACCOUNT, KEY), opener=urllib_itself)

    assert installed == tmp_path / "data" / "GeoLite2-City.mmdb"
    assert storage_saw == [None, None]


def test_dbip_is_asked_with_the_scripts_own_user_agent(tmp_path):
    dbip = FakeDBIP({SEPTEMBER: good(tmp_path)})

    assert fetch_geoip.fetch(tmp_path / "data", TODAY, opener=dbip) is not None
    assert not fetch_geoip.USER_AGENT.startswith("Python-urllib")
