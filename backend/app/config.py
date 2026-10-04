from functools import lru_cache

from pydantic import field_validator
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

    # "development" | "production" — gates secret checks and admin fallbacks
    environment: str = "development"
    # Comma-separated emails allowed to hit admin endpoints (empty = dev only)
    admin_emails: str = ""

    # Reverse proxies in front of the app (Railway/Render/Fly add one). The
    # client IP for rate limiting is read from that many hops back in
    # X-Forwarded-For. Unset: 1 in production, 0 (direct connections) in dev.
    trusted_proxy_count: int | None = None

    # Key for encrypting stored ESPN cookies (a Fernet key). Unset: derived from
    # JWT_SECRET, so rotating that secret means ESPN leagues must reconnect.
    credentials_key: str = ""

    # Daily caps on Claude calls, so a public demo or a scripted account can't
    # run up the API bill. The demo account is shared, so it gets a per-IP cap
    # plus a ceiling across every demo visitor.
    ai_daily_limit_per_user: int = 100
    ai_daily_limit_demo_per_ip: int = 20
    ai_daily_limit_demo_total: int = 300

    @field_validator("trusted_proxy_count", mode="before")
    @classmethod
    def _blank_means_unset(cls, value):
        return None if value == "" else value

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    @property
    def proxy_hops(self) -> int:
        if self.trusted_proxy_count is not None:
            return max(self.trusted_proxy_count, 0)
        return 1 if self.is_production else 0

    @property
    def admin_email_list(self) -> list[str]:
        return [e.strip().lower() for e in self.admin_emails.split(",") if e.strip()]

    @property
    def is_production(self) -> bool:
        return self.environment.lower() == "production"


@lru_cache
def get_settings() -> Settings:
    return Settings()
