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

    # Cost-safe autonomous research runs in a short-lived child process. The
    # child may use the full research dataset for exact semantics, but exits
    # after one bounded cycle so its heap is returned to the OS.
    bounded_research_enabled: bool = False
    bounded_research_startup_seconds: int = Field(default=30, ge=0, le=3600)
    bounded_research_interval_minutes: int = Field(default=360, ge=60, le=1440)
    bounded_research_timeout_seconds: int = Field(default=2700, ge=300, le=7200)
    bounded_research_stage_timeout_seconds: int = Field(default=1500, ge=300, le=3600)
    bounded_research_memory_mb: int = Field(default=1536, ge=512, le=4096)
    bounded_research_overlap_retry_seconds: int = Field(default=60, ge=15, le=600)
    bounded_research_lease_seconds: int = Field(default=180, ge=90, le=600)
    bounded_research_lease_renew_seconds: int = Field(default=45, ge=15, le=120)

    # Discovery-only every-M5 observation fabric.
    fabric_enabled: bool = True
    fabric_batch_days: int = Field(default=21, ge=2, le=60)
    fabric_cycle_seconds: int = Field(default=20, ge=5, le=3600)
    fabric_startup_delay_seconds: int = Field(default=30, ge=0, le=3600)

    # Manual/paper Live Trader. TWELVE_DATA_API_KEY is server-side only and is
    # never exposed through the API or browser payloads.
    live_trader_enabled: bool = True
    twelve_data_api_key: str | None = Field(default=None, min_length=8)
    twelve_data_ws_url: str = "wss://ws.twelvedata.com/v1/quotes/price"
    live_trader_symbol: str = "XAU/USD"
    live_trader_learning_horizon_minutes: int = Field(default=60, ge=15, le=1440)
    # Predeclared manual-execution stress assumptions for XAU/USD. These are
    # raw price-unit deductions converted to R by each trade's original risk.
    # They are not presented as actual broker fills; actual fills live separately.
    live_trader_manual_delay_seconds: int = Field(default=15, ge=0, le=300)
    live_trader_cost_spread_price: float = Field(default=0.30, ge=0.0, le=10.0)
    live_trader_cost_entry_slippage_price: float = Field(default=0.10, ge=0.0, le=10.0)
    live_trader_cost_exit_slippage_price: float = Field(default=0.10, ge=0.0, le=10.0)
    live_trader_cost_commission_price_equivalent: float = Field(default=0.07, ge=0.0, le=10.0)
    # Heavy six-year historical/replay workers are opt-in. Live Trader remains
    # available without retaining/replaying the archive continuously in Railway RAM.
    live_trader_historical_workers_enabled: bool = False

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

        # Exactly one heavy-research execution mode may own historical work.
        # Bounded mode already runs discovery, fabric and Live Trader historical
        # stages in disposable children, so resident copies must stay off.
        if self.bounded_research_enabled:
            if self.bounded_research_lease_renew_seconds >= self.bounded_research_lease_seconds:
                raise ValueError(
                    "BOUNDED_RESEARCH_LEASE_RENEW_SECONDS must be shorter than BOUNDED_RESEARCH_LEASE_SECONDS."
                )
            conflicts: list[str] = []
            if self.autonomous_enabled:
                conflicts.append("AUTONOMOUS_ENABLED")
            if self.fabric_enabled:
                conflicts.append("FABRIC_ENABLED")
            if self.live_trader_historical_workers_enabled:
                conflicts.append("LIVE_TRADER_HISTORICAL_WORKERS_ENABLED")
            if conflicts:
                raise ValueError(
                    "BOUNDED_RESEARCH_ENABLED=true is mutually exclusive with resident heavy workers: "
                    + ", ".join(conflicts)
                )
        return self

    @property
    def source_read_key(self) -> str:
        value = self.source_supabase_read_only_key or self.source_supabase_service_role_key
        if not value:
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
