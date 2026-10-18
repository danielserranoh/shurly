"""
The four list settings read from the environment: CORS_ORIGINS, TRUSTED_PROXIES,
MCP_OAUTH_ALLOWED_REDIRECT_URIS and CLOUDFRONT_ORIGIN_SECRETS take JSON, comma-separated
values, a single value or nothing.

Through the real path, environment variables, never keyword arguments: pydantic-settings
JSON-decodes a list from the environment before any validator runs, so a plain value used to
raise SettingsError at import and the app wouldn't start. Keyword arguments skip that step,
which is how the older tests missed it.
"""

import pytest
from pydantic import SecretStr, ValidationError

from server.core.config import Settings

SECRET_A = "a" * 32
SECRET_B = "b" * 40

# Two valid values per field, and the field's environment variable.
FIELDS = {
    "cors_origins": ("CORS_ORIGINS", "https://one.example", "https://two.example"),
    "trusted_proxies": ("TRUSTED_PROXIES", "10.0.0.0/8", "172.31.0.0/16"),
    "mcp_oauth_allowed_redirect_uris": (
        "MCP_OAUTH_ALLOWED_REDIRECT_URIS",
        "https://claude.ai/api/mcp/auth_callback",
        "http://localhost:*",
    ),
    "cloudfront_origin_secrets": ("CLOUDFRONT_ORIGIN_SECRETS", SECRET_A, SECRET_B),
}


def _load(monkeypatch, variable: str, value: str) -> Settings:
    monkeypatch.setenv(variable, value)
    return Settings(_env_file=None)


def _values(settings: Settings, field: str) -> list[str]:
    return [
        item.get_secret_value() if isinstance(item, SecretStr) else item
        for item in getattr(settings, field)
    ]


@pytest.mark.parametrize("field", FIELDS)
class TestEachListSetting:
    def test_json(self, monkeypatch, field):
        variable, a, b = FIELDS[field]
        settings = _load(monkeypatch, variable, f'["{a}","{b}"]')
        assert _values(settings, field) == [a, b]

    def test_comma_separated_with_spaces(self, monkeypatch, field):
        variable, a, b = FIELDS[field]
        settings = _load(monkeypatch, variable, f"  {a} , {b}  ")
        assert _values(settings, field) == [a, b]

    def test_single_value(self, monkeypatch, field):
        variable, a, _ = FIELDS[field]
        settings = _load(monkeypatch, variable, a)
        assert _values(settings, field) == [a]

    def test_empty(self, monkeypatch, field):
        variable, _, _ = FIELDS[field]
        assert _values(_load(monkeypatch, variable, ""), field) == []

    def test_empty_json_array(self, monkeypatch, field):
        variable, _, _ = FIELDS[field]
        assert _values(_load(monkeypatch, variable, "[]"), field) == []

    def test_blank_items_are_dropped(self, monkeypatch, field):
        variable, a, b = FIELDS[field]
        settings = _load(monkeypatch, variable, f"{a},, ,{b},")
        assert _values(settings, field) == [a, b]

    @pytest.mark.parametrize("quote", ["'", '"'])
    def test_a_quoted_json_array_is_refused(self, monkeypatch, field, quote):
        """The array kept in its shell quotes (an env file read literally) would otherwise be one
        value, quotes and brackets included, and a secret that long passes the length check."""
        variable, a, b = FIELDS[field]
        monkeypatch.setenv(variable, f'{quote}["{a}","{b}"]{quote}')
        with pytest.raises(ValidationError, match="quotes"):
            Settings(_env_file=None)

    def test_broken_json_is_refused(self, monkeypatch, field):
        """A value that starts like a JSON array must be one, not split on its commas."""
        variable, a, b = FIELDS[field]
        monkeypatch.setenv(variable, f'["{a}", "{b}"')
        with pytest.raises(ValidationError):
            Settings(_env_file=None)


class TestProductionValues:
    """What production sets today must keep loading."""

    def test_trusted_proxies_json(self, monkeypatch):
        settings = _load(monkeypatch, "TRUSTED_PROXIES", '["172.31.0.0/16"]')
        assert settings.trusted_proxies == ["172.31.0.0/16"]

    def test_cors_origins_empty_json(self, monkeypatch):
        assert _load(monkeypatch, "CORS_ORIGINS", "[]").cors_origins == []


class TestRegression:
    """Each of these raised SettingsError before the fields were marked NoDecode."""

    def test_bare_cidr(self, monkeypatch):
        assert _load(monkeypatch, "TRUSTED_PROXIES", "172.31.0.0/16").trusted_proxies == [
            "172.31.0.0/16"
        ]

    def test_empty_trusted_proxies(self, monkeypatch):
        assert _load(monkeypatch, "TRUSTED_PROXIES", "").trusted_proxies == []

    def test_comma_separated_origins(self, monkeypatch):
        settings = _load(monkeypatch, "CORS_ORIGINS", "https://a.example,https://b.example")
        assert settings.cors_origins == ["https://a.example", "https://b.example"]


class TestCloudFrontOriginSecrets:
    def test_short_secret_is_refused_from_json(self, monkeypatch):
        monkeypatch.setenv("CLOUDFRONT_ORIGIN_SECRETS", f'["{SECRET_A}","too-short"]')
        with pytest.raises(ValidationError, match="at least 32 characters"):
            Settings(_env_file=None)

    def test_short_secret_is_refused_from_commas(self, monkeypatch):
        monkeypatch.setenv("CLOUDFRONT_ORIGIN_SECRETS", f"{SECRET_A},too-short")
        with pytest.raises(ValidationError, match="at least 32 characters"):
            Settings(_env_file=None)

    def test_short_single_secret_is_refused(self, monkeypatch):
        monkeypatch.setenv("CLOUDFRONT_ORIGIN_SECRETS", "a" * 31)
        with pytest.raises(ValidationError, match="at least 32 characters"):
            Settings(_env_file=None)

    def test_secrets_stay_hidden(self, monkeypatch):
        settings = _load(monkeypatch, "CLOUDFRONT_ORIGIN_SECRETS", f"{SECRET_A},{SECRET_B}")
        assert all(isinstance(s, SecretStr) for s in settings.cloudfront_origin_secrets)
        assert SECRET_A not in repr(settings)
        assert SECRET_B not in repr(settings)
        assert SECRET_A not in str(settings.cloudfront_origin_secrets)
