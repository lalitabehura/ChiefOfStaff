"""Application settings, loaded from environment variables (or a .env file).

Production refuses to start with insecure defaults.
"""
from functools import lru_cache

from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

_DEV_SECRET = "dev-insecure-secret-change-me-0000000000000000"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_name: str = "Chief of Staff"
    environment: str = "development"  # development | test | production

    # --- secrets -----------------------------------------------------------
    secret_key: str = _DEV_SECRET  # signs JWT access tokens
    # 32-byte url-safe base64 key for AES-256-GCM encryption at rest.
    # Generate: python -c "import os,base64;print(base64.urlsafe_b64encode(os.urandom(32)).decode())"
    encryption_key: str = ""

    # --- infrastructure ----------------------------------------------------
    database_url: str = "sqlite:///./dev.db"
    redis_url: str | None = None
    auto_create_tables: bool = True  # dev convenience; production uses Alembic
    frontend_url: str = "http://localhost:5173"
    cors_origins: list[str] = ["http://localhost:5173"]
    allowed_hosts: list[str] = ["*"]
    max_request_bytes: int = 1_000_000
    global_rate_limit_per_minute: int = 300

    # --- auth ----------------------------------------------------------------
    access_token_ttl_minutes: int = 15
    refresh_token_ttl_days: int = 14
    jwt_issuer: str = "chief-of-staff"
    jwt_audience: str = "chief-of-staff-web"
    max_failed_logins: int = 5
    lockout_minutes: int = 15
    password_reset_ttl_minutes: int = 30

    # --- AI ------------------------------------------------------------------
    anthropic_api_key: str | None = None
    anthropic_model: str = "claude-sonnet-5-5"
    ai_daily_request_limit: int = 200
    ai_timeout_seconds: float = 30.0

    # --- Google integration -----------------------------------------------
    google_client_id: str | None = None
    google_client_secret: str | None = None
    google_redirect_uri: str = "http://localhost:5173/api/v1/integrations/google/callback"

    # --- outbound mail (password resets) -----------------------------------
    smtp_host: str | None = None
    smtp_port: int = 587
    smtp_user: str | None = None
    smtp_password: str | None = None
    smtp_from: str = "no-reply@example.com"

    @property
    def is_production(self) -> bool:
        return self.environment == "production"

    @model_validator(mode="after")
    def _check_production(self) -> "Settings":
        if self.is_production:
            problems = []
            if self.secret_key == _DEV_SECRET or len(self.secret_key) < 32:
                problems.append("SECRET_KEY must be a random value of at least 32 characters")
            if not self.encryption_key:
                problems.append("ENCRYPTION_KEY is required")
            if "*" in self.allowed_hosts:
                problems.append("ALLOWED_HOSTS must list your real hostnames")
            if self.database_url.startswith("sqlite"):
                problems.append("Use PostgreSQL in production")
            if not self.frontend_url.startswith("https://"):
                problems.append("FRONTEND_URL must be https in production")
            if problems:
                raise ValueError("Insecure production configuration: " + "; ".join(problems))
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()
