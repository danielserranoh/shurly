"""Unit tests for utility functions."""

import pytest

from server.utils.url import (
    generate_short_code,
    is_valid_custom_code,
    is_valid_url,
    make_code_unique,
)


@pytest.mark.unit
class TestShortCodeGeneration:
    """Test short code generation utilities."""

    def test_generate_short_code_default_length(self):
        """Test that generated code has default length of 6."""
        code = generate_short_code()
        assert len(code) == 6

    def test_generate_short_code_custom_length(self):
        """Test that generated code respects custom length."""
        code = generate_short_code(length=8)
        assert len(code) == 8

    def test_generate_short_code_is_alphanumeric(self):
        """Test that generated code contains only alphanumeric characters."""
        code = generate_short_code()
        assert code.isalnum()

    def test_generate_short_code_uniqueness(self):
        """Test that generated codes are different (probabilistically)."""
        codes = [generate_short_code() for _ in range(100)]
        # Should have at least 99 unique codes out of 100
        assert len(set(codes)) >= 99

    def test_make_code_unique_appends_random_chars(self):
        """Test that make_code_unique adds random characters."""
        original = "test"
        modified = make_code_unique(original, append_length=3)

        assert modified.startswith(original)
        assert len(modified) == len(original) + 3
        assert modified != original


@pytest.mark.unit
class TestCustomCodeValidation:
    """Test custom code validation."""

    def test_valid_custom_code(self):
        """Test that valid custom codes pass validation."""
        valid_codes = ["abc123", "my-url", "test_url", "URL2023"]
        for code in valid_codes:
            assert is_valid_custom_code(code)

    def test_invalid_custom_code_too_short(self):
        """Test that codes shorter than 3 chars are invalid."""
        assert not is_valid_custom_code("ab")
        assert not is_valid_custom_code("a")

    def test_invalid_custom_code_too_long(self):
        """Test that codes longer than 20 chars are invalid."""
        assert not is_valid_custom_code("a" * 21)

    def test_invalid_custom_code_special_chars(self):
        """Test that codes with special characters (except - and _) are invalid."""
        invalid_codes = ["test!url", "my@code", "url#123", "test url"]
        for code in invalid_codes:
            assert not is_valid_custom_code(code)

    def test_valid_custom_code_with_hyphens_underscores(self):
        """Test that hyphens and underscores are allowed."""
        assert is_valid_custom_code("my-url")
        assert is_valid_custom_code("my_url")
        assert is_valid_custom_code("my-url_2023")


@pytest.mark.unit
class TestURLValidation:
    """Test URL validation."""

    def test_valid_urls(self):
        """Test that valid URLs pass validation."""
        valid_urls = [
            "https://example.com",
            "http://test.org/path",
            "https://subdomain.example.com/path?query=1",
            "https://example.com:8080/path",
        ]
        for url in valid_urls:
            assert is_valid_url(url)

    def test_invalid_urls(self):
        """Test that invalid URLs fail validation."""
        invalid_urls = [
            "not-a-url",
            "ftp://example.com",  # FTP not supported
            "example.com",  # Missing scheme
            "http://",  # Incomplete
            "",
            "javascript:alert(1)",  # XSS attempt
        ]
        for url in invalid_urls:
            assert not is_valid_url(url)

    def test_url_max_length(self):
        """Test that extremely long URLs are rejected."""
        long_url = "https://example.com/" + "a" * 3000
        assert not is_valid_url(long_url)
