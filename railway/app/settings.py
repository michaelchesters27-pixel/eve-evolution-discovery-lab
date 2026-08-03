from __future__ import annotations

from functools import lru_cache
from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Runtime configuration for the separate Discovery Lab.

    SOURCE_* points at the existing EVE project. SourceRepository only issues
    GET requests. DISCOVERY_* points at this project's own Supabase database.
    """

    model_config = SettingsConfigDict(env_file=".env", extra="ignore", case_sensitive=False)

    app_name: str = "EVE Evolution Discovery Lab"
    environment: str = "production"
    log_level: str = "INFO"

    source_supabase_url: str = Field(min_length=10)
    source_supabase_service_role_key: str = Field(min_length=20)
    discovery_supabase_url: str = Field(min_length=10)
    discovery_supabase_service_role_key: str = Field(min_length=20)

    admin_token: str = Field(min_length=12)
    cors_origins: str = "*"

    source_symbol: str = "XAU/USD"
    source_snapshot_interval: str = "15min"
    source_page_size: int = Field(default=1000, ge=100, le=5000)
    bridge_batch_limit: int = Field(default=10000, ge=1000, le=50000)

    autonomous_enabled: bool = True
    startup_delay_seconds: int = Field(default=90, ge=10, le=3600)
    cycle_seconds: int = Field(default=45, ge=10, le=3600)
    idle_seconds: int = Field(default=90, ge=10, le=3600)
    candidate_queue_floor: int = Field(default=30, ge=5, le=500)
    lineage_queue_floor: int = Field(default=20, ge=5, le=500)
    candidates_per_seed: int = Field(default=50, ge=5, le=500)
    row_cache_minutes: int = Field(default=45, ge=5, le=720)

    minimum_locked_trades: int = Field(default=80, ge=30, le=5000)
    minimum_validation_trades: int = Field(default=60, ge=20, le=5000)
    mt5_generation_enabled: bool = True

    @field_validator("source_supabase_url", "discovery_supabase_url")
    @classmethod
    def strip_slash(cls, value: str) -> str:
        return value.rstrip("/")

    @property
    def cors_origin_list(self) -> list[str]:
        if self.cors_origins.strip() == "*":
            return ["*"]
        return [item.strip() for item in self.cors_origins.split(",") if item.strip()]


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
