from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # Database
    database_url: str = "postgresql+psycopg://apexai:apexai_dev@localhost:5433/apexai"

    # Vault
    vault_url: str = "http://localhost:8200"
    vault_token: str = "apexai_dev_token"
    vault_mount_point: str = "secret"

    # Redis
    redis_url: str = "redis://localhost:6380/0"

    # JWT
    jwt_secret: str = "dev-secret-change-me-in-production-please-use-32-bytes-min"
    jwt_algorithm: str = "HS256"
    jwt_access_ttl_minutes: int = 15
    jwt_refresh_ttl_days: int = 30

    # App
    app_env: str = "development"
    cors_origins: list[str] = [
        "http://localhost:3000",
        "http://localhost:5173",
        "http://localhost:8000",
    ]
    cookie_secure: bool = False  # True in prod (HTTPS only)

    # Invite / tokens TTL
    invite_ttl_days: int = 7
    password_reset_ttl_minutes: int = 30
    email_verification_ttl_hours: int = 24


@lru_cache
def get_settings() -> Settings:
    return Settings()
