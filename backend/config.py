"""Backend settings, read from the environment.

Uses pydantic-settings so that a malformed value fails at start-up with a clear
message rather than at the first request that touches it.
"""

from __future__ import annotations

import re
from functools import lru_cache

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", extra="ignore"
    )

    # --- Service ----------------------------------------------------------
    app_name: str = "NEYOGI API"
    api_v1_prefix: str = "/api/v1"
    environment: str = Field(default="development")
    cors_origins: str = Field(default="http://localhost:5173,http://localhost:3000")

    # --- Database ---------------------------------------------------------
    database_url: str = Field(
        default="postgresql://neyogi:neyogi@localhost:5432/neyogi"
    )
    db_pool_min: int = 1
    db_pool_max: int = 10

    # --- Auth -------------------------------------------------------------
    jwt_secret: str = Field(default="change-me-to-a-long-random-string")
    jwt_algorithm: str = "HS256"
    jwt_ttl_minutes: int = 480
    # "username:bcrypt_hash" pairs, comma separated. Seeded into `users` at
    # start-up when the table is empty.
    officer_accounts: str = ""

    # --- AGMARKNET --------------------------------------------------------
    agmarknet_api_key: str = ""
    agmarknet_resource_id: str = "9ef84268-d588-465a-a308-a864a43d0070"
    agmarknet_base_url: str = "https://api.data.gov.in/resource"
    agmarknet_state: str = "Karnataka"
    agmarknet_timeout_seconds: float = 12.0

    # --- Twilio -----------------------------------------------------------
    twilio_account_sid: str = ""
    twilio_auth_token: str = ""
    twilio_whatsapp_from: str = "whatsapp:+14155238886"
    twilio_validate_signature: bool = True
    public_base_url: str = "http://localhost:8000"

    # --- Celery / Redis ---------------------------------------------------
    redis_url: str = "redis://localhost:6379/0"
    celery_broker_url: str = "redis://localhost:6379/0"
    celery_result_backend: str = "redis://localhost:6379/1"

    # --- Freshness policy (drives the status badges) ----------------------
    satellite_cache_max_age_days: int = 30
    market_cache_max_age_days: int = 30
    gee_seed_lookback_days: int = 60
    composite_period_days: int = 16
    supply_window_days: int = 21

    # --- Earth Engine -----------------------------------------------------
    gee_project_id: str = ""
    gee_service_account_email: str = ""
    gee_service_account_key_file: str = ""

    @field_validator("database_url")
    @classmethod
    def _normalise_database_url(cls, value: str) -> str:
        """Accept the SQLAlchemy dialect form and hand psycopg a plain URL."""
        return re.sub(r"^postgresql\+\w+://", "postgresql://", value)

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    @property
    def is_production(self) -> bool:
        return self.environment.lower() in {"production", "prod"}

    @property
    def agmarknet_configured(self) -> bool:
        return bool(self.agmarknet_api_key)

    @property
    def twilio_configured(self) -> bool:
        return bool(self.twilio_account_sid and self.twilio_auth_token)


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
