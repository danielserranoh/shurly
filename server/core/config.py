import json
from typing import Any
from urllib.parse import urlsplit

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

    # CORS settings (4232 = frontend dev server, see docker-compose.yml). Phase 6.3:
    # in production the frontend and the API share an origin (shurly.griddo.io, once
    # the frontend is hosted, 4.10), so CORS_ORIGINS needs no entry there; this is for
    # the dev server on another port. The frontend sends a bearer token, never cookies,
    # so no credentials, and only the methods and request headers the API uses.
    cors_origins: list[str] = [
        "http://localhost:4321",
        "http://localhost:4232",
        "http://localhost:3000",
    ]
    cors_allow_credentials: bool = False
    cors_allow_methods: list[str] = ["GET", "POST", "PUT", "PATCH", "DELETE"]
    cors_allow_headers: list[str] = ["Authorization", "Content-Type", "X-Request-Id"]
    # Readable by the frontend: when to retry after a 429, and the id to report.
    cors_expose_headers: list[str] = ["Retry-After", "X-Request-Id"]

    # Phase 3.9.5 — GDPR. Truncate visitor IPs at insert time:
    # IPv4 → /24 (zero last octet), IPv6 → /64. Default ON; disable explicitly via env
    # only if a downstream legal review approves storing full addresses.
    anonymize_remote_addr: bool = True

    # Phase 8.4 — the geolocation database a visit's country and city come from
    # (server/utils/geo.py), fetched into the image by scripts/fetch_geoip.py: MaxMind's GeoLite2
    # City, else DB-IP's IP to Country Lite (CC BY 4.0), the fallback, countries only. Empty turns
    # lookups off; neither file means no country, never a failed redirect.
    geoip_database: str = "data/GeoLite2-City.mmdb"
    geoip_fallback_database: str = "data/dbip-country-lite.mmdb"

    # Phase 3.9.6 — Trust boundaries for X-Forwarded-For. Empty list (default) = never
    # trust X-F-F. Set this to the ALB's CIDR in prod; CloudFront isn't listed here, see
    # cloudfront_origin_secrets below.
    trusted_proxies: list[str] = []

    # Phase 6.3 — behind CloudFront (shurly.griddo.io, 4.10) the client IP comes from
    # CloudFront-Viewer-Address, believed only on a request that carries one of these
    # values in CLOUDFRONT_ORIGIN_HEADER, a custom origin header the distribution adds.
    # Two values while the secret rotates, each at least 32 characters. Empty (the
    # default): X-Forwarded-For, as before (`client_ip`, server/utils/network.py).
    cloudfront_origin_secrets: list[SecretStr] = []
    cloudfront_origin_header: str = "X-Origin-Verify"

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
    # Phase 8.4 — without `mcp_public_url`, its host is the app's (`app_host`).
    frontend_url: str = ""
    # POST /auth/register. Accounts come from Google, so it's off; turn it on only
    # for local development and tests, never in production.
    allow_password_signup: bool = False

    # Phase 5.8 — MCP clients sign in with Google through fastmcp's OAuth proxy,
    # alongside API keys. Off until these two, the Google client above and
    # `organization_domain` are set; the MCP then takes API keys and JWTs only.
    # The MCP endpoint as clients reach it, without the trailing slash, e.g.
    # https://shurly.griddo.io/mcp. People connect to it with the slash.
    # Phase 8.4 — its host is the app's (server/utils/domain.py, `app_host`): the
    # MCP, its OAuth metadata and the docs answer there only, and on any other host
    # `/mcp`, `/docs` and `/redoc` are short links. Else FRONTEND_URL's host; with
    # neither, every host is the app's.
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

    # Phase 6.3 — rate limits on what anyone can call (server/utils/rate_limit.py),
    # per minute unless said otherwise; 0 turns one off. Per client IP, so behind the
    # ALB TRUSTED_PROXIES must name it: otherwise every request seems to come from
    # the ALB and each per-IP limit becomes one limit for everybody.
    # POST /auth/login: every attempt runs a bcrypt check.
    rate_limit_login_per_ip: int = 20
    # Failed password checks per address, per 15 minutes: logins, and the current password
    # given to change or set one. The right password counts for nothing. Anyone can lock
    # an address's password login for the window; signing in with Google stays open.
    rate_limit_login_failures_per_account: int = 10
    # Google's and the MCP's sign-in pages and endpoints: each writes a row.
    rate_limit_sign_in_per_ip: int = 30
    # /mcp/register and /mcp/token: claude.ai calls them from Anthropic's addresses,
    # shared by everybody, so this one is generous.
    rate_limit_mcp_clients_per_ip: int = 60
    # Browser error reports (POST /api/v1/client-errors): anyone may send them, signed in
    # or not. The web app sends 5 at most per page it loads.
    rate_limit_client_errors_per_ip: int = 30

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

    # Shlink's "invalid short URL" redirect: where a short link that doesn't lead anywhere (no
    # such code, not live yet, expired or used up) sends everyone, as a 302 that isn't cached.
    # Empty (default): people get a page, anything else the JSON, with its 404 or 410.
    invalid_short_url_redirect: str = ""

    @field_validator("invalid_short_url_redirect")
    @classmethod
    def _validate_invalid_short_url_redirect(cls, v: str) -> str:
        if v:
            parts = urlsplit(v)
            if parts.scheme not in ("http", "https") or not parts.netloc:
                raise ValueError("invalid_short_url_redirect must be an absolute http(s) URL")
        return v

    # SSRF guard for the Open Graph fetcher. Destination URLs are user-supplied, so link
    # previews refuse any host that resolves to a loopback, private, link-local (cloud
    # metadata) or otherwise non-public address. Set true ONLY in local development to
    # preview pages served from localhost — never in production.
    og_fetch_allow_private: bool = False

    # Database connections, per task
    db_pool_size: int = 10  # Connections kept open
    db_max_overflow: int = 20  # Opened beyond the pool, under load
    db_pool_recycle: int = 3600  # Recycle connections after 1 hour
    db_ssl_mode: str = "prefer"  # Use "require" for RDS SSL

    @field_validator(
        "cors_origins",
        "trusted_proxies",
        "mcp_oauth_allowed_redirect_uris",
        "cloudfront_origin_secrets",
        mode="before",
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

    @field_validator("cloudfront_origin_secrets")
    @classmethod
    def long_enough(cls, secrets: list[SecretStr]) -> list[SecretStr]:
        """Whoever guesses one chooses the address they're counted and logged under."""
        if any(len(secret.get_secret_value()) < 32 for secret in secrets):
            raise ValueError("each CLOUDFRONT_ORIGIN_SECRETS value needs at least 32 characters")
        return secrets

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
