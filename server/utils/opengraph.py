"""Open Graph metadata fetching utilities."""

import asyncio
import ipaddress
import logging
import re
import socket

import httpx
from bs4 import BeautifulSoup

from server.core.config import settings

logger = logging.getLogger(__name__)

_USER_AGENT = "Shurly/1.0 (+https://shurl.griddo.io; Link Preview Bot)"

# SSRF guard. Destination URLs are user-supplied, so the fetcher only requests http(s)
# URLs whose host resolves exclusively to public addresses, connects to an address that
# passed that check, and follows redirects by hand so every hop is checked the same way.
_ALLOWED_SCHEMES = ("http", "https")
_MAX_REDIRECTS = 5


class OpenGraphMetadata:
    """Open Graph metadata container."""

    def __init__(
        self,
        title: str | None = None,
        description: str | None = None,
        image_url: str | None = None,
        url: str | None = None,
    ):
        self.title = title
        self.description = description
        self.image_url = image_url
        self.url = url

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


class _FetchRefusedError(Exception):
    """The URL (or one of its redirect hops) must not be requested; see the SSRF guard."""


async def fetch_opengraph_metadata(url: str, timeout: int = 5) -> OpenGraphMetadata:
    """
    Fetch Open Graph metadata from a URL.

    The URL is user-supplied, so the request goes through the SSRF guard (see
    `_guarded_get`). A refused URL yields empty metadata, like any other fetch failure,
    so URL creation never breaks.

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
        response = await _guarded_get(url, timeout)

        # Only parse successful responses
        if response.status_code != 200:
            logger.warning(f"Failed to fetch {url}: HTTP {response.status_code}")
            return OpenGraphMetadata()

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
            logger.info(f"Could not decode OG body for {url}; skipping metadata")
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
            image_url=og_image,
            url=og_url or url,
        )

    except _FetchRefusedError as e:
        logger.warning(f"Refused to fetch metadata from {url}: {e}")
        return OpenGraphMetadata()

    except (httpx.TimeoutException, asyncio.TimeoutError):
        logger.warning(f"Timeout fetching metadata from {url}")
        return OpenGraphMetadata()

    except Exception as e:
        logger.error(f"Error fetching metadata from {url}: {str(e)}")
        return OpenGraphMetadata()


async def _guarded_get(url: str, timeout: int) -> httpx.Response:
    """GET `url`, following up to `_MAX_REDIRECTS` redirects by hand so each hop is checked."""
    target = httpx.URL(url)
    # No keep-alive: pooled connections are keyed by IP, so one reused for another
    # hostname on the same IP would skip that hostname's TLS certificate check.
    limits = httpx.Limits(max_keepalive_connections=0)
    async with httpx.AsyncClient(timeout=timeout, follow_redirects=False, limits=limits) as client:
        for _ in range(_MAX_REDIRECTS + 1):
            response = await _get_pinned(client, target)
            if not response.is_redirect:
                return response
            target = target.join(response.headers["location"])
    raise _FetchRefusedError(f"more than {_MAX_REDIRECTS} redirects")


async def _get_pinned(client: httpx.AsyncClient, url: httpx.URL) -> httpx.Response:
    """GET `url` from one of its host's checked addresses.

    Connecting to the checked IP, instead of letting httpx resolve the name again, is
    what defeats DNS rebinding (a second lookup could return an internal address). The
    Host header and TLS (SNI and certificate verification) keep the real hostname.
    """
    *fallbacks, last = await _resolve_checked_addresses(url, timeout=client.timeout.connect)
    headers = {"Host": url.netloc.decode("ascii"), "User-Agent": _USER_AGENT}
    extensions = {"sni_hostname": url.raw_host.decode("ascii")}
    for address in fallbacks:
        try:
            return await client.get(
                url.copy_with(host=address), headers=headers, extensions=extensions
            )
        except httpx.ConnectError:
            continue  # e.g. an IPv6 address on a host without IPv6 connectivity
    return await client.get(url.copy_with(host=last), headers=headers, extensions=extensions)


async def _resolve_checked_addresses(url: httpx.URL, timeout: float | None) -> list[str]:
    """Resolve the URL's host, refusing it unless every address it resolves to is public."""
    if url.scheme not in _ALLOWED_SCHEMES or not url.host:
        raise _FetchRefusedError(f"{url} is not an http(s) URL with a host")
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
            raise _FetchRefusedError(f"{host} resolves to non-public {', '.join(blocked)}")
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
