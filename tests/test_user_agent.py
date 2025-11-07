"""Tests for user agent parsing utilities."""

import pytest

from server.utils.user_agent import (
    get_browser_name,
    get_os_name,
    is_bot,
    is_mobile,
    parse_user_agent,
)


@pytest.mark.unit
class TestUserAgentParsing:
    """Tests for user agent string parsing."""

    def test_parse_chrome_windows(self):
        """Test parsing Chrome on Windows."""
        ua = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        result = parse_user_agent(ua)

        assert result["browser"] == "Chrome"
        assert result["browser_version"].startswith("120")
        assert "Windows" in result["os"]
        assert result["device_type"] == "desktop"

    def test_parse_firefox_macos(self):
        """Test parsing Firefox on macOS."""
        ua = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10.15; rv:121.0) Gecko/20100101 Firefox/121.0"
        result = parse_user_agent(ua)

        assert result["browser"] == "Firefox"
        assert result["browser_version"].startswith("121")
        assert "macOS" in result["os"]
        assert result["device_type"] == "desktop"

    def test_parse_safari_macos(self):
        """Test parsing Safari on macOS."""
        ua = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.1 Safari/605.1.15"
        result = parse_user_agent(ua)

        assert result["browser"] == "Safari"
        assert result["browser_version"].startswith("17")
        assert "macOS" in result["os"]
        assert result["device_type"] == "desktop"

    def test_parse_edge(self):
        """Test parsing Microsoft Edge."""
        ua = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36 Edg/120.0.0.0"
        result = parse_user_agent(ua)

        assert result["browser"] == "Edge"
        assert "Windows" in result["os"]

    def test_parse_mobile_chrome_android(self):
        """Test parsing Chrome on Android mobile."""
        ua = "Mozilla/5.0 (Linux; Android 13; SM-S901B) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Mobile Safari/537.36"
        result = parse_user_agent(ua)

        assert result["browser"] == "Chrome"
        assert "Android" in result["os"]
        assert result["device_type"] == "mobile"

    def test_parse_safari_iphone(self):
        """Test parsing Safari on iPhone."""
        ua = "Mozilla/5.0 (iPhone; CPU iPhone OS 17_1_1 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.1 Mobile/15E148 Safari/604.1"
        result = parse_user_agent(ua)

        assert result["browser"] == "Safari"
        assert "iOS" in result["os"]
        assert result["device_type"] == "mobile"

    def test_parse_safari_ipad(self):
        """Test parsing Safari on iPad."""
        ua = "Mozilla/5.0 (iPad; CPU OS 17_1 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.1 Mobile/15E148 Safari/604.1"
        result = parse_user_agent(ua)

        assert "iOS" in result["os"]
        assert result["device_type"] == "tablet"

    def test_parse_bot_googlebot(self):
        """Test detecting Googlebot."""
        ua = "Mozilla/5.0 (compatible; Googlebot/2.1; +http://www.google.com/bot.html)"
        result = parse_user_agent(ua)

        assert result["browser"] == "Bot"
        assert result["device_type"] == "bot"

    def test_parse_bot_curl(self):
        """Test detecting curl."""
        ua = "curl/7.68.0"
        result = parse_user_agent(ua)

        assert result["browser"] == "Bot"
        assert result["device_type"] == "bot"

    def test_parse_none_user_agent(self):
        """Test parsing None/empty user agent."""
        result = parse_user_agent(None)

        assert result["browser"] == "Unknown"
        assert result["os"] == "Unknown"
        assert result["device_type"] == "unknown"

    def test_get_browser_name(self):
        """Test get_browser_name helper."""
        ua = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        assert get_browser_name(ua) == "Chrome"

    def test_get_os_name(self):
        """Test get_os_name helper."""
        ua = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.1 Safari/605.1.15"
        os_name = get_os_name(ua)
        assert "macOS" in os_name

    def test_is_mobile_true(self):
        """Test is_mobile returns True for mobile UA."""
        ua = "Mozilla/5.0 (iPhone; CPU iPhone OS 17_1_1 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.1 Mobile/15E148 Safari/604.1"
        assert is_mobile(ua) is True

    def test_is_mobile_false(self):
        """Test is_mobile returns False for desktop UA."""
        ua = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        assert is_mobile(ua) is False

    def test_is_bot_true(self):
        """Test is_bot returns True for bot UA."""
        ua = "Mozilla/5.0 (compatible; Googlebot/2.1; +http://www.google.com/bot.html)"
        assert is_bot(ua) is True

    def test_is_bot_false(self):
        """Test is_bot returns False for normal UA."""
        ua = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        assert is_bot(ua) is False

    def test_parse_opera(self):
        """Test parsing Opera browser."""
        ua = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36 OPR/106.0.0.0"
        result = parse_user_agent(ua)

        assert result["browser"] == "Opera"

    def test_parse_linux(self):
        """Test parsing Linux OS."""
        ua = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        result = parse_user_agent(ua)

        assert result["os"] == "Linux"
        assert result["device_type"] == "desktop"
