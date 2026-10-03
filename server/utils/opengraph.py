"""Open Graph metadata fetching utilities."""

import asyncio
import ipaddress
import logging
import re
import socket
from urllib.parse import urljoin, urlsplit

import httpx
from bs4 import BeautifulSoup

from server.core.config import settings
from server.utils.url import url_origin

logger = logging.getLogger(__name__)

_USER_AGENT = "Shurly/1.0 (+https://shurly.griddo.io; Link Preview Bot)"

# SSRF guard. Destination URLs are user-supplied, so the fetcher only requests http(s)
# URLs whose host resolves exclusively to public addresses, connects to an address that
# passed that check, and follows redirects by hand so every hop is checked the same way.
_ALLOWED_SCHEMES = ("http", "https")
_MAX_REDIRECTS = 5
# Phase 8.7 — a link on the page (its icon, its og:image) longer than this isn't kept.
_MAX_LINKED_URL = 2048


class OpenGraphMetadata:
    """What a page declares for its preview, and its icon (Phase 8.7).

    `fetched` says whether the page answered: any status below 500, a 404 included (the page
    has no preview, then). False when the fetch was refused, timed out, failed or got a 5xx,
    so a refresh doesn't wipe what a link already knows over a passing failure.
    """

    def __init__(
        self,
        title: str | None = None,
        description: str | None = None,
        image_url: str | None = None,
        url: str | None = None,
        favicon_url: str | None = None,
        fetched: bool = True,
    ):
        self.title = title
        self.description = description
        self.image_url = image_url
        self.url = url
        self.favicon_url = favicon_url
        self.fetched = fetched

    @classmethod
    def failed(cls) -> "OpenGraphMetadata":
        """Nothing, because the page didn't answer."""
        return cls(fetched=False)

    def to_dict(self) -> dict[str, str | None]:
        return {
            "og_title": self.title,
            "og_description": self.description,
            "og_image_url": self.image_url,
            "og_url": self.url,
        }

    def has_metadata(self) -> bool:
        """Check if any metadata was found."""
        return any([self.title, self.description, self.image_url])


class FetchRefusedError(Exception):
    """The URL (or one of its redirect hops) must not be requested; see the SSRF guard."""


async def fetch_opengraph_metadata(url: str, timeout: int = 5) -> OpenGraphMetadata:
    """
    Fetch Open Graph metadata from a URL, and the page's icon (Phase 8.7).

    The URL is user-supplied, so the request goes through the SSRF guard (see
    `guarded_request`). A refused URL yields empty metadata, like any other fetch failure,
    so URL creation never breaks. Log lines keep the URL's origin only (`url_origin`):
    its path and query string can carry personal data.

    The icon is the best one the page declares (`_pick_favicon`), or else an origin's
    `/favicon.ico`, when one request there answers 200 with an image: the link's own origin,
    then the one the redirects ended on, if they left it. Relative links, the icon's and
    og:image's, resolve against the URL the redirects ended on.

    Args:
        url: Destination URL to fetch metadata from
        timeout: Request timeout in seconds (default: 5)

    Returns:
        OpenGraphMetadata object with parsed data

    Example:
        >>> metadata = await fetch_opengraph_metadata("https://example.com")
        >>> print(metadata.title)  # "Example Domain"
    """
    try:
        response, final_url = await _guarded_fetch("GET", url, timeout)

    except FetchRefusedError as e:
        logger.warning("Refused to fetch metadata from %s: %s", url_origin(url), e)
        return OpenGraphMetadata.failed()

    except (httpx.TimeoutException, asyncio.TimeoutError):
        logger.warning("Timeout fetching metadata from %s", url_origin(url))
        return OpenGraphMetadata.failed()

    except Exception as e:
        # The type only: a library's message can repeat the URL.
        logger.error("Error fetching metadata from %s: %s", url_origin(url), type(e).__name__)
        return OpenGraphMetadata.failed()

    base = str(final_url)
    try:
        metadata = _parse_page(response, url, base)
    except Exception as e:
        logger.error("Error reading metadata from %s: %s", url_origin(url), type(e).__name__)
        metadata = OpenGraphMetadata(fetched=response.status_code < 500)

    # Phase 8.7 — no icon declared: the origin's /favicon.ico, if it's there. The link's own
    # origin first, when the redirects left it: a sign-in wall (drive.google.com sends a stranger
    # to accounts.google.com, whose page declares none) isn't what the link is.
    for origin in dict.fromkeys(url_origin(u) for u in (url, base)):
        if metadata.favicon_url:
            break
        metadata.favicon_url = await _origin_favicon(origin, timeout)
    return metadata


def _parse_page(response: httpx.Response, url: str, base: str) -> OpenGraphMetadata:
    """The preview and the icon a page's answer declares: nothing unless a 200 in HTML."""
    # Only parse successful responses
    if response.status_code != 200:
        logger.warning("Failed to fetch %s: HTTP %s", url_origin(url), response.status_code)
        return OpenGraphMetadata(fetched=response.status_code < 500)

    # Only parse HTML content
    content_type = response.headers.get("content-type", "")
    if "text/html" not in content_type:
        logger.info(f"Skipping non-HTML content: {content_type}")
        return OpenGraphMetadata()

    # Phase 3.9.6 (Shlink #2564) — charset fallback. response.text uses the
    # Content-Type charset; if absent or wrong it produces mojibake. Decode
    # explicitly via the meta-tag charset, falling back to utf-8 with errors
    # ignored. We never raise from here — a bad charset must not break URL
    # creation, so on irrecoverable decode errors we simply skip OG.
    html_text = _decode_response_body(response)
    if html_text is None:
        logger.info("Could not decode OG body for %s; skipping metadata", url_origin(url))
        return OpenGraphMetadata()

    # Parse HTML
    soup = BeautifulSoup(html_text, "html.parser")

    # Extract Open Graph tags
    og_title = _extract_og_tag(soup, "og:title")
    og_description = _extract_og_tag(soup, "og:description")
    og_image = _extract_og_tag(soup, "og:image")
    og_url = _extract_og_tag(soup, "og:url")

    # Fallback to standard meta tags if OG tags missing
    if not og_title:
        og_title = _extract_meta_tag(soup, "title") or _extract_title_tag(soup)

    if not og_description:
        og_description = _extract_meta_tag(soup, "description")

    return OpenGraphMetadata(
        title=og_title,
        description=og_description,
        # Phase 8.7 — a relative og:image is the page's: resolved, so a thumbnail can load it.
        image_url=_absolute_http_url(og_image, base) if og_image else None,
        url=og_url or url,
        favicon_url=_pick_favicon(soup, base),
    )


# Phase 8.7 — the rel values that name a page's icon. "shortcut icon" is two tokens, one of
# them "icon"; Safari's "mask-icon" is a one-colour silhouette, not an icon to show.
_ICON_RELS = {"icon", "apple-touch-icon", "apple-touch-icon-precomposed"}
_SIZE = re.compile(r"^(\d+)[xX](\d+)$")


def _pick_favicon(soup: BeautifulSoup, base: str) -> str | None:
    """
    The page's best declared icon: an SVG, else the PNG with the largest declared `sizes`,
    else the first icon it declares. Only http(s), resolved against `base`.
    """
    best: str | None = None
    best_rank: tuple[int, int] | None = None
    for link in soup.find_all("link", href=True):
        rels = link.get("rel") or []
        if isinstance(rels, str):
            rels = rels.split()
        if not _ICON_RELS & {rel.lower() for rel in rels}:
            continue
        href = _absolute_http_url(link["href"], base)
        if href is None:
            continue
        kind = (link.get("type") or "").strip().lower()
        path = urlsplit(href).path.lower()
        size = _largest_size(link.get("sizes"))
        if kind == "image/svg+xml" or path.endswith(".svg"):
            rank = (2, 0)
        elif (kind == "image/png" or path.endswith(".png")) and size:
            rank = (1, size)
        else:
            rank = (0, 0)
        if best_rank is None or rank > best_rank:  # a tie keeps the first
            best, best_rank = href, rank
    return best


def _largest_size(sizes: str | list | None) -> int:
    """The largest side `sizes` declares ("16x16 32x32" gives 32); 0 for none or "any"."""
    if not sizes:
        return 0
    tokens = sizes if isinstance(sizes, list) else sizes.split()
    sides = [max(int(m[1]), int(m[2])) for m in map(_SIZE.match, tokens) if m]
    return max(sides, default=0)


def _absolute_http_url(href: str, base: str) -> str | None:
    """`href` resolved against `base`, when that makes an http(s) URL with a host; else None."""
    href = href.strip()
    if not href or len(href) > _MAX_LINKED_URL:
        return None
    try:
        absolute = urljoin(base, href)
        parts = urlsplit(absolute)
        host = parts.hostname
    except ValueError:
        return None
    if parts.scheme not in _ALLOWED_SCHEMES or not host or len(absolute) > _MAX_LINKED_URL:
        return None
    return absolute


async def _origin_favicon(base: str, timeout: float) -> str | None:
    """
    `/favicon.ico` on `base`'s origin, when one request there, through the SSRF guard,
    answers 200 with an image content type. Its body is closed unread.
    """
    origin = url_origin(base)
    if not origin.startswith(("http://", "https://")):
        return None
    candidate = f"{origin}/favicon.ico"
    try:
        response, _ = await _guarded_fetch("GET", candidate, timeout, read_body=False)
    except Exception as e:  # refused, timed out, failed: no icon, and the preview stands
        logger.info("No /favicon.ico from %s: %s", origin, type(e).__name__)
        return None
    content_type = response.headers.get("content-type", "").lower()
    if response.status_code == 200 and content_type.startswith("image/"):
        return candidate
    return None


async def guarded_request(method: str, url: str, timeout: float) -> httpx.Response:
    """
    `method` `url` through the SSRF guard, following up to `_MAX_REDIRECTS` redirects by
    hand so each hop is checked; FetchRefusedError when a hop mustn't be requested. The
    link previews GET; the Shlink review (server/tools/shlink) checks destinations with
    HEAD.
    """
    response, _ = await _guarded_fetch(method, url, timeout)
    return response


async def _guarded_fetch(
    method: str, url: str, timeout: float, *, read_body: bool = True
) -> tuple[httpx.Response, httpx.URL]:
    """`guarded_request`, and the URL the redirects ended on: Phase 8.7 resolves the page's
    relative links against it. Without `read_body`, the answer's status and headers only, its
    body closed unread (the favicon check)."""
    target = httpx.URL(url)
    # No keep-alive: pooled connections are keyed by IP, so one reused for another
    # hostname on the same IP would skip that hostname's TLS certificate check.
    limits = httpx.Limits(max_keepalive_connections=0)
    async with httpx.AsyncClient(timeout=timeout, follow_redirects=False, limits=limits) as client:
        for _ in range(_MAX_REDIRECTS + 1):
            response = await _request_pinned(client, method, target, read_body=read_body)
            if not response.is_redirect:
                return response, target
            target = target.join(response.headers["location"])
    raise FetchRefusedError(f"more than {_MAX_REDIRECTS} redirects")


async def _request_pinned(
    client: httpx.AsyncClient, method: str, url: httpx.URL, *, read_body: bool = True
) -> httpx.Response:
    """`method` `url` from one of its host's checked addresses.

    Connecting to the checked IP, instead of letting httpx resolve the name again, is
    what defeats DNS rebinding (a second lookup could return an internal address). The
    Host header and TLS (SNI and certificate verification) keep the real hostname.
    """
    *fallbacks, last = await _resolve_checked_addresses(url, timeout=client.timeout.connect)
    headers = {"Host": url.netloc.decode("ascii"), "User-Agent": _USER_AGENT}
    extensions = {"sni_hostname": url.raw_host.decode("ascii")}

    async def send(address: str) -> httpx.Response:
        request = client.build_request(
            method, url.copy_with(host=address), headers=headers, extensions=extensions
        )
        response = await client.send(request, stream=not read_body)
        if not read_body:
            await response.aclose()
        return response

    for address in fallbacks:
        try:
            return await send(address)
        except httpx.ConnectError:
            continue  # e.g. an IPv6 address on a host without IPv6 connectivity
    return await send(last)


async def _resolve_checked_addresses(url: httpx.URL, timeout: float | None) -> list[str]:
    """Resolve the URL's host, refusing it unless every address it resolves to is public."""
    if url.scheme not in _ALLOWED_SCHEMES or not url.host:
        raise FetchRefusedError(f"not an http(s) URL with a host (scheme {url.scheme!r})")
    host = url.raw_host.decode("ascii")
    # getaddrinfo blocks, so it runs in a thread. The lookup counts against the connect
    # timeout, as it did when httpx resolved the name itself.
    infos = await asyncio.wait_for(
        asyncio.to_thread(socket.getaddrinfo, host, url.port, type=socket.SOCK_STREAM),
        timeout,
    )
    addresses = list(dict.fromkeys(info[4][0] for info in infos))
    if not settings.og_fetch_allow_private:
        blocked = [a for a in addresses if not _is_public_ip(ipaddress.ip_address(a))]
        if blocked:
            raise FetchRefusedError(f"{host} resolves to non-public {', '.join(blocked)}")
    return addresses


def _is_public_ip(ip: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    """True only for globally routable unicast addresses.

    `is_global` alone lets multicast through, and the explicit flags alone miss
    100.64.0.0/10 (shared/CGNAT space, sometimes used inside VPCs), so both are checked.
    An IPv4 address embedded in IPv6 (IPv4-mapped, 6to4) must pass too: older Pythons
    count 6to4 addresses such as 2002:a9fe:a9fe:: (169.254.169.254) as global.
    """
    if isinstance(ip, ipaddress.IPv6Address):
        embedded = ip.ipv4_mapped or ip.sixtofour
        if embedded is not None and not _is_public_ip(embedded):
            return False
    return ip.is_global and not (
        ip.is_private
        or ip.is_loopback
        or ip.is_link_local
        or ip.is_reserved
        or ip.is_multicast
        or ip.is_unspecified
    )


_META_CHARSET_RE = re.compile(
    rb"""<meta[^>]+charset\s*=\s*['"]?([\w\-]+)""",
    re.IGNORECASE,
)


def _decode_response_body(response: httpx.Response) -> str | None:
    """Best-effort decode that respects an HTML <meta charset>."""
    raw = response.content
    # Try the response's declared encoding first (from Content-Type)
    encoding = response.encoding or response.charset_encoding
    if encoding and encoding.lower() != "iso-8859-1":
        try:
            return raw.decode(encoding)
        except (LookupError, UnicodeDecodeError):
            pass
    # Otherwise sniff <meta charset=...> from the head bytes
    match = _META_CHARSET_RE.search(raw[:2048])
    if match:
        meta_enc = match.group(1).decode("ascii", errors="ignore")
        try:
            return raw.decode(meta_enc)
        except (LookupError, UnicodeDecodeError):
            pass
    # Last resort: utf-8 with replacement so malformed pages still parse for OG tags
    try:
        return raw.decode("utf-8", errors="replace")
    except Exception:
        return None


def _extract_og_tag(soup: BeautifulSoup, property_name: str) -> str | None:
    """Extract Open Graph meta tag content."""
    tag = soup.find("meta", property=property_name)
    if tag and tag.get("content"):
        return tag["content"].strip()
    return None


def _extract_meta_tag(soup: BeautifulSoup, name: str) -> str | None:
    """Extract standard meta tag content."""
    tag = soup.find("meta", attrs={"name": name})
    if tag and tag.get("content"):
        return tag["content"].strip()
    return None


def _extract_title_tag(soup: BeautifulSoup) -> str | None:
    """Extract <title> tag content as fallback."""
    title_tag = soup.find("title")
    if title_tag and title_tag.string:
        return title_tag.string.strip()
    return None


def is_social_media_crawler(user_agent: str) -> bool:
    """
    Detect if User-Agent is a social media crawler.

    Social media crawlers need to see the preview page with OG tags,
    while regular browsers should get direct redirects.

    Args:
        user_agent: User-Agent header string

    Returns:
        True if social media crawler, False otherwise
    """
    if not user_agent:
        return False

    ua_lower = user_agent.lower()

    # Social media crawler identifiers
    crawlers = [
        "twitterbot",  # Twitter/X
        "facebookexternalhit",  # Facebook
        "linkedinbot",  # LinkedIn
        "whatsapp",  # WhatsApp
        "slackbot",  # Slack
        "discordbot",  # Discord
        "telegrambot",  # Telegram
        "skypeuripreview",  # Skype
        "pinterest",  # Pinterest
        "redditbot",  # Reddit
        "slurp",  # Yahoo (sometimes used by messaging apps)
    ]

    return any(crawler in ua_lower for crawler in crawlers)
