"""Utility functions for URL shortening."""

import random
import re
import string
from urllib.parse import urlparse

from server.core.config import settings


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


def make_code_unique(code: str, append_length: int = 3) -> str:
    """
    Make a code unique by appending random characters.

    Args:
        code: Original code
        append_length: Number of random characters to append (default: 3)

    Returns:
        Modified code with random characters appended
    """
    random_suffix = generate_short_code(length=append_length)
    return f"{code}{random_suffix}"


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

    if len(code) < 3 or len(code) > 20:
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
