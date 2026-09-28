"""
Phase 3.16 — what the per-link analytics show of a visit: its kind, and its facets (OS and
browser families, device class, referrer host, country), each with a label when it's missing.

Worked out at query time from what `visits` stores (the user agent, the referrer, the
country): nothing here is written to the database, so the labels always follow the parser.
"""

from dataclasses import dataclass
from functools import lru_cache
from urllib.parse import urlsplit

from server.utils.user_agent import parse_user_agent

UNKNOWN = "Unknown"
DIRECT = "Direct"  # no referrer

# The parser names versions ("macOS 10.15.7", "Android 14", "iOS (iPad)"): charts show families.
_OS_FAMILIES = ("Windows", "macOS", "iOS", "Android", "Linux", "Chrome OS")
# The parser's device types, as the analytics name them: a bot's is "other".
_DEVICES = {"desktop": "desktop", "mobile": "mobile", "tablet": "tablet", "bot": "other"}


def kind_of(is_pixel: bool, is_bot: bool) -> str:
    """Every visit is exactly one kind: a bot's, else an email open (a pixel hit), else a click.
    The SQL filters (`type=` in server/app/analytics.py) draw the same lines."""
    if is_bot:
        return "bot"
    return "open" if is_pixel else "click"


@dataclass(frozen=True)
class Families:
    os: str
    browser: str
    device: str


@lru_cache(maxsize=4096)
def families(user_agent: str | None) -> Families:
    """A user agent's OS and browser families and its device class, "Unknown" where the parser
    can't tell. Cached: a link's visits share few distinct user agents."""
    parsed = parse_user_agent(user_agent)
    os_name = parsed["os"]
    os_family = next((family for family in _OS_FAMILIES if os_name.startswith(family)), os_name)
    return Families(
        os=os_family,
        browser=parsed["browser"],
        device=_DEVICES.get(parsed["device_type"], UNKNOWN),
    )


def referrer_host(referer: str | None) -> str:
    """A referrer as the analytics show it: its host, lowercased, and never its path or query.
    "Direct" without one; "Unknown" for one that names no host."""
    if not referer or not referer.strip():
        return DIRECT
    try:
        host = urlsplit(referer.strip()).hostname
    except ValueError:  # e.g. an unclosed IPv6 bracket
        host = None
    return host or UNKNOWN


def country_label(country: str | None) -> str:
    """A visit's country: its ISO code, or "Unknown" (no database yet, or not found in it)."""
    return country or UNKNOWN
