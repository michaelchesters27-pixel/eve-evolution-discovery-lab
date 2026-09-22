from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.settings import Settings


def base() -> dict:
    return {
        "source_supabase_url": "https://source.example.invalid",
        "source_supabase_read_only_key": "x" * 30,
        "discovery_supabase_url": "https://discovery.example.invalid",
        "discovery_supabase_service_role_key": "y" * 30,
        "admin_token": "z" * 20,
        "source_candle_interval": "5min",
        "research_timeframe": "M5",
    }


def test_bounded_mode_rejects_resident_autonomous_worker() -> None:
    with pytest.raises(ValidationError, match="AUTONOMOUS_ENABLED"):
        Settings(**base(), bounded_research_enabled=True, autonomous_enabled=True, fabric_enabled=False)


def test_bounded_mode_rejects_resident_fabric_worker() -> None:
    with pytest.raises(ValidationError, match="FABRIC_ENABLED"):
        Settings(**base(), bounded_research_enabled=True, autonomous_enabled=False, fabric_enabled=True)


def test_bounded_mode_rejects_resident_live_historical_workers() -> None:
    with pytest.raises(ValidationError, match="LIVE_TRADER_HISTORICAL_WORKERS_ENABLED"):
        Settings(
            **base(),
            bounded_research_enabled=True,
            autonomous_enabled=False,
            fabric_enabled=False,
            live_trader_historical_workers_enabled=True,
        )


def test_bounded_mode_valid_when_all_duplicate_resident_workers_are_off() -> None:
    settings = Settings(
        **base(),
        bounded_research_enabled=True,
        autonomous_enabled=False,
        fabric_enabled=False,
        live_trader_historical_workers_enabled=False,
        bounded_research_memory_mb=1536,
        bounded_research_stage_timeout_seconds=1500,
    )
    assert settings.bounded_research_enabled is True
    assert settings.bounded_research_memory_mb == 1536
    assert settings.bounded_research_stage_timeout_seconds == 1500
