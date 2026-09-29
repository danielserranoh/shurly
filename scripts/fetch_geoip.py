"""
Phase 8.4 — fetch DB-IP's IP to Country Lite database (CC BY 4.0, https://db-ip.com) for
server/utils/geo.py: this month's file, or last month's while this month's isn't out yet.
A file is installed only once it opens and knows that 8.8.8.8 is in the US.

It never fails. Without a database, visits simply have no country, and the app logs
`geo.database_missing`. The image build runs it; so can a developer:

    uv run python scripts/fetch_geoip.py [out_dir]    # default: data/
"""

import gzip
import sys
from datetime import date
from pathlib import Path
from urllib.request import Request, urlopen

import maxminddb

FILENAME = "dbip-country-lite.mmdb"
URL = "https://download.db-ip.com/free/dbip-country-lite-{month}.mmdb.gz"
KNOWN = ("8.8.8.8", "US")  # every file must know it before it's installed
USER_AGENT = "shurly-fetch-geoip/1"  # download.db-ip.com answers Python's default with a 403


def months(today: date) -> list[str]:
    """This month and the one before: a new file appears a few days into the month."""
    previous = (
        date(today.year - 1, 12, 1) if today.month == 1 else date(today.year, today.month - 1, 1)
    )
    return [f"{today:%Y-%m}", f"{previous:%Y-%m}"]


def fetch(out_dir: Path, today: date | None = None, opener=urlopen) -> Path | None:
    """The installed database, or None when no month's file could be fetched and checked."""
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


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    out_dir = Path(args[0] if args else "data")
    if fetch(out_dir, opener=urlopen) is None:
        print("No geolocation database: visits will have no country.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
