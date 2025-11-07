"""User agent parsing utilities."""

import re


def parse_user_agent(user_agent_string: str | None) -> dict:
    """
    Parse user agent string to extract browser and OS information.

    Returns a dict with:
        - browser: str (Chrome, Firefox, Safari, Edge, etc.)
        - browser_version: str
        - os: str (Windows, macOS, Linux, iOS, Android, etc.)
        - device_type: str (desktop, mobile, tablet, bot)
    """
    if not user_agent_string:
        return {
            "browser": "Unknown",
            "browser_version": "",
            "os": "Unknown",
            "device_type": "unknown",
        }

    ua = user_agent_string.lower()

    # Detect bots
    bot_patterns = [
        "bot",
        "crawler",
        "spider",
        "scraper",
        "curl",
        "wget",
        "python-requests",
        "java",
        "go-http-client",
    ]
    if any(pattern in ua for pattern in bot_patterns):
        return {
            "browser": "Bot",
            "browser_version": "",
            "os": "Unknown",
            "device_type": "bot",
        }

    # Detect OS (order matters - check iOS before macOS)
    os_name = "Unknown"
    if "windows nt 10" in ua or "windows nt 11" in ua:
        os_name = "Windows 10/11"
    elif "windows nt 6.3" in ua:
        os_name = "Windows 8.1"
    elif "windows nt 6.2" in ua:
        os_name = "Windows 8"
    elif "windows nt 6.1" in ua:
        os_name = "Windows 7"
    elif "windows" in ua:
        os_name = "Windows"
    elif "iphone" in ua:
        os_name = "iOS (iPhone)"
    elif "ipad" in ua:
        os_name = "iOS (iPad)"
    elif "mac os x" in ua or "macos" in ua:
        # Extract macOS version if possible
        mac_version_match = re.search(r"mac os x ([\d_]+)", ua)
        if mac_version_match:
            version = mac_version_match.group(1).replace("_", ".")
            os_name = f"macOS {version}"
        else:
            os_name = "macOS"
    elif "android" in ua:
        # Extract Android version if possible
        android_version_match = re.search(r"android ([\d.]+)", ua)
        if android_version_match:
            version = android_version_match.group(1)
            os_name = f"Android {version}"
        else:
            os_name = "Android"
    elif "linux" in ua:
        os_name = "Linux"
    elif "cros" in ua:
        os_name = "Chrome OS"

    # Detect device type (check tablets before mobile since iPad UA contains "Mobile")
    device_type = "desktop"
    if "ipad" in ua or ("tablet" in ua) or ("android" in ua and "mobile" not in ua):
        device_type = "tablet"
    elif "mobile" in ua or "iphone" in ua or "ipod" in ua or ("android" in ua and "mobile" in ua):
        device_type = "mobile"

    # Detect browser (order matters - check more specific first)
    browser = "Unknown"
    browser_version = ""

    # Opera (check before Chrome/Edge)
    if "opr/" in ua or "opera/" in ua:
        browser = "Opera"
        opera_match = re.search(r"(?:opr|opera)/([\d.]+)", ua)
        if opera_match:
            browser_version = opera_match.group(1)

    # Edge
    elif "edg/" in ua or "edge/" in ua:
        browser = "Edge"
        edge_match = re.search(r"(?:edg|edge)/([\d.]+)", ua)
        if edge_match:
            browser_version = edge_match.group(1)

    # Chrome (check after Edge/Opera since they use Chromium)
    elif "chrome/" in ua:
        browser = "Chrome"
        chrome_match = re.search(r"chrome/([\d.]+)", ua)
        if chrome_match:
            browser_version = chrome_match.group(1)

    # Firefox
    elif "firefox/" in ua:
        browser = "Firefox"
        firefox_match = re.search(r"firefox/([\d.]+)", ua)
        if firefox_match:
            browser_version = firefox_match.group(1)

    # Safari (check after Chrome/Edge/Opera since they include Safari in UA)
    elif "safari/" in ua:
        browser = "Safari"
        safari_match = re.search(r"version/([\d.]+)", ua)
        if safari_match:
            browser_version = safari_match.group(1)

    # Internet Explorer
    elif "msie" in ua or "trident/" in ua:
        browser = "Internet Explorer"
        ie_match = re.search(r"(?:msie |rv:)([\d.]+)", ua)
        if ie_match:
            browser_version = ie_match.group(1)

    return {
        "browser": browser,
        "browser_version": browser_version,
        "os": os_name,
        "device_type": device_type,
    }


def get_browser_name(user_agent_string: str | None) -> str:
    """Extract just the browser name from user agent string."""
    parsed = parse_user_agent(user_agent_string)
    return parsed["browser"]


def get_os_name(user_agent_string: str | None) -> str:
    """Extract just the OS name from user agent string."""
    parsed = parse_user_agent(user_agent_string)
    return parsed["os"]


def is_mobile(user_agent_string: str | None) -> bool:
    """Check if the user agent represents a mobile device."""
    parsed = parse_user_agent(user_agent_string)
    return parsed["device_type"] in ("mobile", "tablet")


def is_bot(user_agent_string: str | None) -> bool:
    """Check if the user agent represents a bot/crawler."""
    parsed = parse_user_agent(user_agent_string)
    return parsed["device_type"] == "bot"
