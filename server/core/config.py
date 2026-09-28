import json
from typing import Any

from pydantic import SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings using Pydantic v2 settings management."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # Database settings
    db_host: str = "localhost"
    db_port: int = 5432
    db_user: str = "postgres"
    db_password: str = ""
    db_name: str = "shurly"

    @property
    def database_url(self) -> str:
        """Construct PostgreSQL database URL."""
        return f"postgresql+psycopg2://{self.db_user}:{self.db_password}@{self.db_host}:{self.db_port}/{self.db_name}"

    # JWT Settings
    jwt_secret_key: str = "your-secret-key-change-in-production"
    jwt_algorithm: str = "HS256"
    jwt_access_token_expire_minutes: int = 60 * 24 * 7  # 7 days

    # API settings
    api_title: str = "Shurly API"
    api_version: str = "0.1.0"
    api_description: str = "A modern URL shortener API"

    # CORS settings (4232 = frontend dev server, see docker-compose.yml)
    cors_origins: list[str] = [
        "http://localhost:4321",
        "http://localhost:4232",
        "http://localhost:3000",
    ]
    cors_allow_credentials: bool = True
    cors_allow_methods: list[str] = ["*"]
    cors_allow_headers: list[str] = ["*"]

    # Phase 3.9.5 — GDPR. Truncate visitor IPs at insert time:
    # IPv4 → /24 (zero last octet), IPv6 → /64. Default ON; disable explicitly via env
    # only if a downstream legal review approves storing full addresses.
    anonymize_remote_addr: bool = True

    # Phase 3.9.6 — Trust boundaries for X-Forwarded-For. Empty list (default) = never
    # trust X-F-F. Set this to your ALB/CloudFront/API-GW source CIDR list in prod.
    trusted_proxies: list[str] = []

    # Phase 3.9.6 — Visit-suppression query param ("nostat" by default). When the
    # redirect handler sees this param it skips Visitor logging entirely. Useful for QA.
    disable_track_param: str = "nostat"

    # Phase 3.9.6 — Short-code casing mode. "loose" (default, Shlink behavior) lowercases
    # generated codes and custom slugs at insert; "strict" preserves case.
    short_url_mode: str = "loose"

    # Phase 3.10.1 — Default short-link host. Seeded on startup; URLs without an
    # explicit domain_id are bound to this row so the composite UNIQUE works.
    default_domain: str = "shurl.griddo.io"

    # Optional override for the absolute URL emitted in API responses
    # (URLResponse.short_url, campaign exports, OG previews). When empty,
    # build_short_url() derives it from `default_domain` in production-style
    # deploys, or falls back to http://localhost:8000 locally. Set this if the
    # short-link host differs from the API host (rare).
    base_url: str = ""

    # Phase 3.14.2 — the organization every account belongs to (one at launch).
    # Seeded on startup. `organization_domain` is the Google Workspace domain whose
    # accounts may sign in (3.13).
    organization_name: str = "Griddo"
    organization_domain: str = "griddo.io"
    # The first owner. This account becomes owner when it joins an organization
    # that has none, and at startup it restores one if none is left (break-glass).
    # Empty = no bootstrap owner.
    bootstrap_owner_email: str = ""

    # Phase 3.13.2 — sign in with Google (OpenID Connect). Until these four and
    # `organization_domain` are set, the Google endpoints answer 503 and the rest
    # of the app works as before. An empty domain would let any Google account in.
    google_client_id: str = ""
    google_client_secret: SecretStr = SecretStr("")
    # This API's /api/v1/auth/google/callback, as registered with the Google client.
    google_redirect_uri: str = ""
    # The static frontend. After Google, the browser goes to {frontend_url}/login/
    # with a one-time code in the fragment (server/app/google_auth.py).
    frontend_url: str = ""
    # POST /auth/register. Accounts come from Google, so it's off; turn it on only
    # for local development and tests, never in production.
    allow_password_signup: bool = False

    # Phase 5.8 — MCP clients sign in with Google through fastmcp's OAuth proxy,
    # alongside API keys. Off until these two, the Google client above and
    # `organization_domain` are set; the MCP then takes API keys and JWTs only.
    # The MCP endpoint as clients reach it, without the trailing slash, e.g.
    # https://shurly.griddo.io/mcp. People connect to it with the slash.
    mcp_public_url: str = ""
    # Signs the MCP's OAuth tokens and, derived, encrypts what it stores. The same
    # value on every task; changing it signs every MCP client out.
    mcp_oauth_signing_key: SecretStr = SecretStr("")
    # The redirect URIs an MCP client may register (DCR or a Client ID Metadata
    # Document): claude.ai's callback (and claude.com's, where Anthropic says it may
    # move) and Claude Code's loopback on any port. Anything else can't register, so
    # a stranger's app can't ask a Griddo person to consent (consent phishing).
    mcp_oauth_allowed_redirect_uris: list[str] = [
        "https://claude.ai/api/mcp/auth_callback",
        "https://claude.com/api/mcp/auth_callback",
        "http://localhost:*",
        "http://127.0.0.1:*",
    ]

    @property
    def mcp_oauth_configured(self) -> bool:
        return all(
            (
                self.google_client_id,
                self.google_client_secret.get_secret_value(),
                self.organization_domain.strip(),
                self.mcp_public_url,
                self.mcp_oauth_signing_key.get_secret_value(),
            )
        )

    @property
    def google_sign_in_configured(self) -> bool:
        return all(
            (
                self.google_client_id,
                self.google_client_secret.get_secret_value(),
                self.google_redirect_uri,
                self.frontend_url,
                self.organization_domain.strip(),
            )
        )

    # Phase 3.10.6 — Configurable redirect behavior.
    # `redirect_status_code`: 302 (default) keeps every hit hitting the backend so
    # analytics stay accurate. 301 is SEO-friendly but cached aggressively by
    # browsers and intermediaries — use only when SEO outweighs analytics fidelity.
    # 307 / 308 preserve the request method (POST stays POST), useful for API
    # gateways but rare for short URLs.
    redirect_status_code: int = 302
    # `redirect_cache_lifetime`: seconds to allow caching the redirect response.
    # 0 (default) → `Cache-Control: private, max-age=0` so analytics see every hit.
    redirect_cache_lifetime: int = 0

    @field_validator("redirect_status_code")
    @classmethod
    def _validate_redirect_status(cls, v: int) -> int:
        if v not in (301, 302, 307, 308):
            raise ValueError("redirect_status_code must be one of 301, 302, 307, 308")
        return v

    # SSRF guard for the Open Graph fetcher. Destination URLs are user-supplied, so link
    # previews refuse any host that resolves to a loopback, private, link-local (cloud
    # metadata) or otherwise non-public address. Set true ONLY in local development to
    # preview pages served from localhost — never in production.
    og_fetch_allow_private: bool = False

    # Lambda/AWS settings
    is_lambda: bool = False  # Set to True when running in Lambda
    db_pool_size: int = 10  # Smaller for Lambda (2-5), larger for local (10)
    db_max_overflow: int = 20  # Smaller for Lambda (5), larger for local (20)
    db_pool_recycle: int = 3600  # Recycle connections after 1 hour
    db_ssl_mode: str = "prefer"  # Use "require" for RDS SSL

    @field_validator(
        "cors_origins", "trusted_proxies", "mcp_oauth_allowed_redirect_uris", mode="before"
    )
    @classmethod
    def parse_string_list(cls, v: Any) -> list[str]:
        """Parse a list-typed setting from a JSON string, comma-separated string, or list."""
        if v is None or v == "":
            return []
        if isinstance(v, str):
            try:
                return json.loads(v)
            except json.JSONDecodeError:
                # Fall back to comma-separated for trusted_proxies; single item for origins
                if "," in v:
                    return [item.strip() for item in v.split(",") if item.strip()]
                return [v]
        return v

    # Tags configuration
    predefined_tags: dict[str, dict] = {
        "channels": {
            "color": "blue-500",
            "tags": ["email", "social", "sms", "push", "direct-mail"],
        },
        "intent": {
            "color": "green-500",
            "tags": ["awareness", "consideration", "conversion", "retention"],
        },
        "content-type": {
            "color": "purple-500",
            "tags": ["blog", "landing-page", "product", "promotion", "event"],
        },
        "audience": {
            "color": "orange-500",
            "tags": ["b2b", "b2c", "enterprise", "smb", "consumer"],
        },
        "lifecycle": {
            "color": "pink-500",
            "tags": ["onboarding", "nurture", "upsell", "reactivation", "churn"],
        },
    }
    user_tag_color: str = "gray-500"  # Default color for user-created tags


# Global settings instance
settings = Settings()

# Backwards compatibility
MYSQL_DB_URL = settings.database_url  # Name kept for compatibility, but uses PostgreSQL now
