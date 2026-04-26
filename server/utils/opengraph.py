"""Open Graph metadata fetching utilities."""

import logging
import re

import httpx
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)


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


async def fetch_opengraph_metadata(url: str, timeout: int = 5) -> OpenGraphMetadata:
    """
    Fetch Open Graph metadata from a URL.

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
        async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as client:
            response = await client.get(
                url,
                headers={
                    "User-Agent": "Shurly/1.0 (+https://shurl.griddo.io; Link Preview Bot)"
                },
            )

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

    except httpx.TimeoutException:
        logger.warning(f"Timeout fetching metadata from {url}")
        return OpenGraphMetadata()

    except Exception as e:
        logger.error(f"Error fetching metadata from {url}: {str(e)}")
        return OpenGraphMetadata()


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
