from __future__ import annotations

from functools import lru_cache
from pydantic import Field, field_validator, model_validator
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
    source_supabase_service_role_key: str | None = Field(default=None, min_length=20)
    source_supabase_read_only_key: str | None = Field(default=None, min_length=20)
    discovery_supabase_url: str = Field(min_length=10)
    discovery_supabase_service_role_key: str = Field(min_length=20)

    admin_token: str = Field(min_length=12)
    cors_origins: str = "*"

    source_symbol: str = "XAU/USD"
    source_snapshot_interval: str = "15min"
    source_candle_interval: str = "5min"
    research_timeframe: str = "M5"
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

    # Discovery-only every-M5 observation fabric. This runs alongside the
    # existing 15-minute scientist until the new foundation is complete/audited.
    fabric_enabled: bool = True
    fabric_batch_days: int = Field(default=21, ge=2, le=60)
    fabric_cycle_seconds: int = Field(default=20, ge=5, le=3600)
    fabric_startup_delay_seconds: int = Field(default=30, ge=0, le=3600)

    minimum_locked_trades: int = Field(default=80, ge=30, le=5000)
    minimum_validation_trades: int = Field(default=60, ge=20, le=5000)
    mt5_generation_enabled: bool = True
    m1_replay_enabled: bool = True
    minimum_generations_before_final: int = Field(default=3, ge=1, le=50)
    package_downloads_require_admin: bool = True
    research_api_requires_admin: bool = True
    legacy_profile_max_attempts: int = Field(default=3, ge=1, le=20)

    @field_validator("source_supabase_url", "discovery_supabase_url")
    @classmethod
    def strip_slash(cls, value: str) -> str:
        return value.rstrip("/")

    @model_validator(mode="after")
    def require_source_read_credential(self) -> "Settings":
        if not self.source_supabase_read_only_key and not self.source_supabase_service_role_key:
            raise ValueError(
                "Configure SOURCE_SUPABASE_READ_ONLY_KEY (preferred) or "
                "SOURCE_SUPABASE_SERVICE_ROLE_KEY (legacy migration fallback)."
            )
        aliases = {
            "M1": {"1MIN", "1M"},
            "M5": {"5MIN", "5M"},
            "M15": {"15MIN", "15M"},
            "M30": {"30MIN", "30M"},
            "H1": {"1H", "60MIN", "60M"},
            "H4": {"4H", "240MIN", "240M"},
        }
        timeframe = self.research_timeframe.strip().upper().replace("PERIOD_", "")
        interval = self.source_candle_interval.strip().upper()
        expected = aliases.get(timeframe)
        if expected is None:
            raise ValueError(f"Unsupported RESEARCH_TIMEFRAME: {self.research_timeframe}")
        if interval not in expected:
            raise ValueError(
                f"RESEARCH_TIMEFRAME={timeframe} does not match "
                f"SOURCE_CANDLE_INTERVAL={self.source_candle_interval}. "
                "A strategy may only be labelled with the timeframe used to build its source features."
            )
        self.research_timeframe = timeframe
        return self

    @property
    def source_read_key(self) -> str:
        value = self.source_supabase_read_only_key or self.source_supabase_service_role_key
        if not value:  # guarded by model validation; keeps type checkers honest
            raise RuntimeError("Source read credential is not configured")
        return value

    @property
    def source_credential_mode(self) -> str:
        return "read_only_key" if self.source_supabase_read_only_key else "legacy_service_role_key"

    @property
    def cors_origin_list(self) -> list[str]:
        if self.cors_origins.strip() == "*":
            return ["*"]
        return [item.strip() for item in self.cors_origins.split(",") if item.strip()]


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
