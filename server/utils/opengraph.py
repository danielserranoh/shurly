"""Open Graph metadata fetching utilities."""

import httpx
from bs4 import BeautifulSoup
from typing import Optional
import logging

logger = logging.getLogger(__name__)


class OpenGraphMetadata:
    """Open Graph metadata container."""

    def __init__(
        self,
        title: Optional[str] = None,
        description: Optional[str] = None,
        image_url: Optional[str] = None,
        url: Optional[str] = None,
    ):
        self.title = title
        self.description = description
        self.image_url = image_url
        self.url = url

    def to_dict(self) -> dict[str, Optional[str]]:
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

            # Parse HTML
            soup = BeautifulSoup(response.text, "html.parser")

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


def _extract_og_tag(soup: BeautifulSoup, property_name: str) -> Optional[str]:
    """Extract Open Graph meta tag content."""
    tag = soup.find("meta", property=property_name)
    if tag and tag.get("content"):
        return tag["content"].strip()
    return None


def _extract_meta_tag(soup: BeautifulSoup, name: str) -> Optional[str]:
    """Extract standard meta tag content."""
    tag = soup.find("meta", attrs={"name": name})
    if tag and tag.get("content"):
        return tag["content"].strip()
    return None


def _extract_title_tag(soup: BeautifulSoup) -> Optional[str]:
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
