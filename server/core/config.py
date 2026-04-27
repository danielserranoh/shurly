import json
from typing import Any

from pydantic import field_validator
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

    # CORS settings
    cors_origins: list[str] = ["http://localhost:4321", "http://localhost:3000"]
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
            raise ValueError(
                "redirect_status_code must be one of 301, 302, 307, 308"
            )
        return v

    # Lambda/AWS settings
    is_lambda: bool = False  # Set to True when running in Lambda
    db_pool_size: int = 10  # Smaller for Lambda (2-5), larger for local (10)
    db_max_overflow: int = 20  # Smaller for Lambda (5), larger for local (20)
    db_pool_recycle: int = 3600  # Recycle connections after 1 hour
    db_ssl_mode: str = "prefer"  # Use "require" for RDS SSL

    @field_validator("cors_origins", "trusted_proxies", mode="before")
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
            "tags": ["email", "social", "sms", "push", "direct-mail"]
        },
        "intent": {
            "color": "green-500",
            "tags": ["awareness", "consideration", "conversion", "retention"]
        },
        "content-type": {
            "color": "purple-500",
            "tags": ["blog", "landing-page", "product", "promotion", "event"]
        },
        "audience": {
            "color": "orange-500",
            "tags": ["b2b", "b2c", "enterprise", "smb", "consumer"]
        },
        "lifecycle": {
            "color": "pink-500",
            "tags": ["onboarding", "nurture", "upsell", "reactivation", "churn"]
        }
    }
    user_tag_color: str = "gray-500"  # Default color for user-created tags


# Global settings instance
settings = Settings()

# Backwards compatibility
MYSQL_DB_URL = settings.database_url  # Name kept for compatibility, but uses PostgreSQL now
