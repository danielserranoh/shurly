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
    db_port: int = 3306
    db_user: str = "root"
    db_password: str = ""
    db_name: str = "shurly"

    @property
    def mysql_db_url(self) -> str:
        """Construct MySQL database URL."""
        return f"mysql+pymysql://{self.db_user}:{self.db_password}@{self.db_host}:{self.db_port}/{self.db_name}"

    # API settings
    api_title: str = "Shurly API"
    api_version: str = "0.1.0"
    api_description: str = "A modern URL shortener API"

    # CORS settings
    cors_origins: list[str] = ["http://localhost:4321", "http://localhost:3000"]
    cors_allow_credentials: bool = True
    cors_allow_methods: list[str] = ["*"]
    cors_allow_headers: list[str] = ["*"]


# Global settings instance
settings = Settings()

# Backwards compatibility
MYSQL_DB_URL = settings.mysql_db_url
