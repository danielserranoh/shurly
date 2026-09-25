"""Utility functions for URL shortening."""

import random
import re
import string
from urllib.parse import urlparse

from server.core.config import settings

# Matches the `URL.short_code` column (String(20)).
MAX_SHORT_CODE_LENGTH = 20

# Single-segment paths the app serves itself, ahead of `/{short_code}`: a short
# link with one of these codes could never be reached. Custom codes that hit
# one are treated as taken. `test_reserved_codes_cover_the_app_routes` checks
# this set against the app's routes.
RESERVED_SHORT_CODES = frozenset(
    {
        "mcp",  # MCP endpoint: the bare /mcp 308s to the /mcp/ mount (main.py)
        "docs",  # FastAPI Swagger UI
        "redoc",  # FastAPI ReDoc
    }
)


def build_short_url(short_code: str) -> str:
    """Build the full short URL from a short code.

    Single source of truth for every absolute short URL the API emits (URL
    responses, OG previews, analytics overview, campaign detail + CSV export).

    Resolution order:
        1. settings.base_url if set (overrides everything; useful for staging
           that runs on a non-default host).
        2. https://<default_domain> in production-style deploys.
        3. http://localhost:8000 as the local-dev fallback so unit tests and
           docker-compose work without extra config.
    """
    if getattr(settings, "base_url", "") and settings.base_url:
        base_url = settings.base_url.rstrip("/")
    elif settings.is_lambda or settings.default_domain not in ("", "localhost"):
        # Production-shaped: default_domain is set to the public hostname.
        base_url = f"https://{settings.default_domain}"
    else:
        base_url = "http://localhost:8000"
    return f"{base_url}/{short_code}"


def generate_short_code(length: int = 6) -> str:
    """
    Generate a random alphanumeric short code.

    In `loose` mode (default, Phase 3.9.6) only lowercase + digits are used so that
    `Abc` and `abc` cannot collide and so users do not get bitten by case-sensitive
    URL handling on copy/paste. `strict` mode preserves the original mixed case.
    """
    if settings.short_url_mode == "loose":
        characters = string.ascii_lowercase + string.digits
    else:
        characters = string.ascii_letters + string.digits
    return "".join(random.choices(characters, k=length))


def normalize_short_code(code: str) -> str:
    """Normalize a user-supplied custom slug according to SHORT_URL_MODE."""
    return code.lower() if settings.short_url_mode == "loose" else code


def is_reserved_short_code(code: str) -> bool:
    """
    True if `code` is a path the app serves itself (see RESERVED_SHORT_CODES).

    Compared after SHORT_URL_MODE normalization: routes are case-sensitive, so
    in strict mode only the exact lowercase path collides.
    """
    return normalize_short_code(code) in RESERVED_SHORT_CODES


def make_code_unique(code: str, append_length: int = 3) -> str:
    """
    Make a code unique by appending random characters.

    The base is trimmed so the result still fits MAX_SHORT_CODE_LENGTH.

    Args:
        code: Original code
        append_length: Number of random characters to append (default: 3)

    Returns:
        Modified code with random characters appended
    """
    random_suffix = generate_short_code(length=append_length)
    return f"{code[: MAX_SHORT_CODE_LENGTH - append_length]}{random_suffix}"


def is_valid_custom_code(code: str) -> bool:
    """
    Validate a custom short code.

    Rules:
    - Length between 3 and 20 characters
    - Only alphanumeric, hyphens, and underscores allowed
    - No spaces or special characters

    Args:
        code: Custom code to validate

    Returns:
        True if valid, False otherwise
    """
    if not code:
        return False

    if len(code) < 3 or len(code) > MAX_SHORT_CODE_LENGTH:
        return False

    # Allow only alphanumeric, hyphens, and underscores
    pattern = r"^[a-zA-Z0-9_-]+$"
    return bool(re.match(pattern, code))


def is_valid_url(url: str, max_length: int = 2048) -> bool:
    """
    Validate a URL.

    Rules:
    - Must have http or https scheme
    - Must have a valid domain
    - Maximum length 2048 characters (reasonable limit)
    - No dangerous schemes (javascript:, data:, etc.)

    Args:
        url: URL to validate
        max_length: Maximum allowed URL length (default: 2048)

    Returns:
        True if valid, False otherwise
    """
    if not url or len(url) > max_length:
        return False

    try:
        result = urlparse(url)

        # Must have scheme and netloc (domain)
        if not all([result.scheme, result.netloc]):
            return False

        # Only allow http and https
        if result.scheme not in ["http", "https"]:
            return False

        return True

    except Exception:
        return False
