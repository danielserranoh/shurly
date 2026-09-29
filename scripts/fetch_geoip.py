"""
Phase 8.4 — the geolocation databases the image carries, for server/utils/geo.py:

- MaxMind's GeoLite2 City: countries and cities. Its licence (the GeoLite EULA, §6.3) wants a
  copy replaced within 30 days of an update, so the image is rebuilt every week
  (DEPLOYMENT.md § Geolocation data). It needs MaxMind's account ID and licence key: from
  MAXMIND_ACCOUNT_ID and MAXMIND_LICENSE_KEY, or the build's secrets (/run/secrets/
  maxmind_account_id and maxmind_license_key). They're sent to MaxMind only, never printed.
- DB-IP's IP to Country Lite (CC BY 4.0, https://db-ip.com): countries only, and no account.
  Always fetched: the app falls back to it when there's no GeoLite2 file.

Each is installed only once it opens and knows that 8.8.8.8 is in the US. GeoLite2's also has to
match MaxMind's SHA-256, and to be less than 25 days old. It never fails: without GeoLite2 the
app falls back to DB-IP, and without either, visits have no country. The image build runs it;
so can a developer (who deletes the GeoLite2 copy within 30 days, as the EULA wants):

    uv run python scripts/fetch_geoip.py [out_dir]    # default: data/
"""

import base64
import gzip
import hashlib
import io
import os
import sys
import tarfile
import time
from datetime import date
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import maxminddb

FILENAME = "dbip-country-lite.mmdb"
URL = "https://download.db-ip.com/free/dbip-country-lite-{month}.mmdb.gz"
KNOWN = ("8.8.8.8", "US")  # every file must know it before it's installed
USER_AGENT = "shurly-fetch-geoip/1"  # download.db-ip.com answers Python's default with a 403

GEOLITE = "GeoLite2-City.mmdb"
GEOLITE_URL = "https://download.maxmind.com/geoip/databases/GeoLite2-City/download?suffix={suffix}"
GEOLITE_MAX_AGE_DAYS = 25  # MaxMind's EULA gives 30 from an update: this leaves a margin
SECRETS = Path("/run/secrets")


def months(today: date) -> list[str]:
    """This month and the one before: a new file appears a few days into the month."""
    previous = (
        date(today.year - 1, 12, 1) if today.month == 1 else date(today.year, today.month - 1, 1)
    )
    return [f"{today:%Y-%m}", f"{previous:%Y-%m}"]


def fetch(out_dir: Path, today: date | None = None, opener=urlopen) -> Path | None:
    """DB-IP's database, installed; None when no month's file could be fetched and checked."""
    out_dir.mkdir(parents=True, exist_ok=True)
    candidate = out_dir / f".{FILENAME}.download"
    for month in months(today or date.today()):
        url = URL.format(month=month)
        try:
            with opener(Request(url, headers={"User-Agent": USER_AGENT}), timeout=60) as response:
                candidate.write_bytes(gzip.decompress(response.read()))
        except Exception as error:  # a 404 until the month's file is out, a network error…
            print(f"{url}: {type(error).__name__}: {error}")
            continue
        problem = _problem(candidate)
        if problem:
            print(f"{url}: {problem}")
            candidate.unlink()
            continue
        installed = out_dir / FILENAME
        candidate.replace(installed)
        print(f"{installed}: DB-IP IP to Country Lite, {month}")
        return installed
    return None


def credentials() -> tuple[str, str] | None:
    """MaxMind's account ID and licence key: from the environment, else the build's secrets."""
    account = os.environ.get("MAXMIND_ACCOUNT_ID") or _secret(SECRETS / "maxmind_account_id")
    key = os.environ.get("MAXMIND_LICENSE_KEY") or _secret(SECRETS / "maxmind_license_key")
    return (account, key) if account and key else None


def fetch_geolite(
    out_dir: Path, account_key: tuple[str, str], opener=urlopen, now: float | None = None
) -> Path | None:
    """MaxMind's GeoLite2 City, installed; None when it couldn't be fetched and checked. What's
    printed names the problem, never the credentials."""
    out_dir.mkdir(parents=True, exist_ok=True)
    token = base64.b64encode(":".join(account_key).encode()).decode()

    def get(suffix: str) -> bytes:
        request = Request(GEOLITE_URL.format(suffix=suffix), headers={"User-Agent": USER_AGENT})
        # Not forwarded when MaxMind redirects to its storage's presigned URL: the storage
        # refuses a second credential with a 400, and the key is MaxMind's only.
        request.add_unredirected_header("Authorization", f"Basic {token}")
        with opener(request, timeout=120) as response:
            return response.read()

    try:
        expected = get("tar.gz.sha256").split()[0].decode()
        archive = get("tar.gz")
    except HTTPError as error:
        reason = {401: "refused the account ID or licence key", 429: "said: too many downloads"}
        print(f"MaxMind GeoLite2 City: {reason.get(error.code, f'HTTP {error.code}')}")
        return None
    except Exception as error:
        print(f"MaxMind GeoLite2 City: {type(error).__name__}")
        return None
    if hashlib.sha256(archive).hexdigest() != expected:
        print("MaxMind GeoLite2 City: its SHA-256 isn't MaxMind's")
        return None

    candidate = out_dir / f".{GEOLITE}.download"
    try:
        with tarfile.open(fileobj=io.BytesIO(archive), mode="r:gz") as tar:
            member = next(
                m for m in tar.getmembers() if m.isfile() and m.name.endswith(f"/{GEOLITE}")
            )
            candidate.write_bytes(tar.extractfile(member).read())
    except (tarfile.TarError, StopIteration, OSError) as error:
        print(f"MaxMind GeoLite2 City: no {GEOLITE} in the archive ({type(error).__name__})")
        return None
    problem = _problem(candidate) or _too_old(candidate, now or time.time())
    if problem:
        print(f"MaxMind GeoLite2 City: {problem}")
        candidate.unlink()
        return None
    installed = out_dir / GEOLITE
    candidate.replace(installed)
    print(f"{installed}: MaxMind GeoLite2 City, built {_built(installed)}")
    return installed


def _secret(path: Path) -> str | None:
    try:
        return path.read_text().strip() or None
    except OSError:
        return None


def _problem(path: Path) -> str | None:
    try:
        reader = maxminddb.open_database(str(path))
    except Exception as error:
        return f"doesn't open ({type(error).__name__})"
    try:
        record = reader.get(KNOWN[0]) or {}
    finally:
        reader.close()
    code = (record.get("country") or {}).get("iso_code")
    return None if code == KNOWN[1] else f"doesn't place {KNOWN[0]} in {KNOWN[1]} ({code})"


def _too_old(path: Path, now: float) -> str | None:
    with maxminddb.open_database(str(path)) as reader:
        age_days = (now - reader.metadata().build_epoch) / 86400
    if age_days > GEOLITE_MAX_AGE_DAYS:
        return f"built {age_days:.0f} days ago: more than {GEOLITE_MAX_AGE_DAYS}"
    return None


def _built(path: Path) -> str:
    with maxminddb.open_database(str(path)) as reader:
        return time.strftime("%Y-%m-%d", time.gmtime(reader.metadata().build_epoch))


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    out_dir = Path(args[0] if args else "data")
    if fetch(out_dir, opener=urlopen) is None:
        print("No DB-IP database: without GeoLite2 either, visits will have no country.")
    account_key = credentials()
    if account_key is None:
        print("No MaxMind credentials: countries only, from DB-IP.")
    elif fetch_geolite(out_dir, account_key, opener=urlopen) is None:
        print("No GeoLite2 City: countries only, from DB-IP.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
