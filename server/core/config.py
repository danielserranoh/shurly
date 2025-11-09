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

    # Lambda/AWS settings
    is_lambda: bool = False  # Set to True when running in Lambda
    db_pool_size: int = 10  # Smaller for Lambda (2-5), larger for local (10)
    db_max_overflow: int = 20  # Smaller for Lambda (5), larger for local (20)
    db_pool_recycle: int = 3600  # Recycle connections after 1 hour
    db_ssl_mode: str = "prefer"  # Use "require" for RDS SSL

    @field_validator("cors_origins", mode="before")
    @classmethod
    def parse_cors_origins(cls, v: Any) -> list[str]:
        """Parse CORS origins from JSON string or list."""
        if isinstance(v, str):
            try:
                return json.loads(v)
            except json.JSONDecodeError:
                # If it's a single origin, return as list
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
