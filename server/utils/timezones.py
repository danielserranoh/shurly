"""
Phase 3.12 — the countries and time zones a profile may name, from the `tzdata` package.

The package, not the system's database: the production image's (Debian) has 486 zones and
none of the legacy names browsers still report ("Asia/Calcutta", Chrome's for India), where
macOS has 598. The package is the same everywhere, and `zoneinfo` falls back to it for a
name the system lacks.

- A time zone is stored under its IANA name, never an offset: offsets change with DST.
- The names zone.tab gives a country are kept as they are, links included:
  "Europe/Stockholm" has been a link to Europe/Berlin since 2022, and it's still Sweden's.
- Any other link is a legacy name, stored as its target: "Asia/Calcutta" → "Asia/Kolkata".

The frontend's picker reads the same lists from frontend/src/data/timezones.json, made by
scripts/generate_timezones.py; a test fails when the two differ.
"""

from functools import cache
from importlib import resources

# Offered whatever the country, for those who keep their clock on UTC.
ANY_COUNTRY = ("Etc/UTC",)


def _lines(name: str) -> list[str]:
    """The data lines of one of tzdata's files, comments left out."""
    text = resources.files("tzdata").joinpath("zoneinfo", name).read_text(encoding="utf-8")
    return [line for line in text.splitlines() if line and not line.startswith("#")]


@cache
def countries() -> dict[str, str]:
    """ISO 3166-1 alpha-2 code → English name ("ES" → "Spain"), from iso3166.tab."""
    return dict(line.split("\t")[:2] for line in _lines("iso3166.tab"))


@cache
def zones_by_country() -> dict[str, list[str]]:
    """Country → the zones zone.tab gives it ("ES" → Africa/Ceuta, Atlantic/Canary, Europe/Madrid)."""
    zones: dict[str, list[str]] = {}
    for line in _lines("zone.tab"):
        code, _coordinates, zone = line.split("\t")[:3]
        zones.setdefault(code, []).append(zone)
    return {code: sorted(names) for code, names in sorted(zones.items())}


@cache
def _zones_and_links() -> tuple[frozenset[str], dict[str, str]]:
    """tzdata.zi's zones (`Z name …`), and its links (`L target name`) as name → target."""
    zones, links = set(), {}
    for line in _lines("tzdata.zi"):
        kind, *rest = line.split()
        if kind == "Z":
            zones.add(rest[0])
        elif kind == "L":
            links[rest[1]] = rest[0]
    return frozenset(zones), links


@cache
def picker_zones() -> tuple[str, ...]:
    """Every zone the picker offers: the names zone.tab gives the countries, and UTC."""
    listed = {zone for zones in zones_by_country().values() for zone in zones}
    return tuple(sorted(listed | set(ANY_COUNTRY)))


@cache
def aliases() -> dict[str, str]:
    """Legacy name → the name stored for it: every link the picker doesn't offer."""
    offered = set(picker_zones())
    _zones, links = _zones_and_links()
    return {name: target for name, target in sorted(links.items()) if name not in offered}


@cache
def _by_lowercase() -> dict[str, str]:
    zones, links = _zones_and_links()
    return {name.lower(): name for name in (*zones, *links)}


def preferred_timezone(name: str) -> str | None:
    """The name stored for `name`, in any capitals; None when it isn't an IANA time zone."""
    exact = _by_lowercase().get(name.strip().lower())
    if exact is None:
        return None
    return aliases().get(exact, exact)


def picker_data() -> dict:
    """What the frontend's picker reads (frontend/src/data/timezones.json)."""
    return {
        "countries": sorted(countries()),
        "zones": zones_by_country(),
        "anyCountry": list(ANY_COUNTRY),
        "aliases": aliases(),
    }
