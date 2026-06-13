from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "sqlite+aiosqlite:///./dev.db"
    redis_url: str = "redis://localhost:6379/0"

    jwt_secret: str = "dev-secret-do-not-use-in-prod"
    jwt_algorithm: str = "HS256"
    access_token_expire_minutes: int = 60
    refresh_token_expire_days: int = 30

    anthropic_api_key: str = ""
    anthropic_model: str = "claude-sonnet-4-6"

    # Google sign-in (optional). Set to your Google OAuth Web Client ID to
    # enable "Continue with Google". No client secret is needed — we verify
    # the ID token Google hands the browser. Leave blank to disable.
    google_client_id: str = ""

    odds_api_key: str = ""

    resend_api_key: str = ""
    email_from: str = "Fantasy Football AI <onboarding@resend.dev>"

    cors_origins: str = "http://localhost:3000"
    enable_scheduler: bool = False
    current_season: int = 2026

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
