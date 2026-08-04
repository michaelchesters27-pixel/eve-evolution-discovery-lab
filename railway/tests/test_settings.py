import pytest
from pydantic import ValidationError

from app.settings import Settings


def settings(**overrides):
    values={
        "source_supabase_url":"https://source.example.supabase.co",
        "source_supabase_read_only_key":"r"*32,
        "discovery_supabase_url":"https://discovery.example.supabase.co",
        "discovery_supabase_service_role_key":"d"*32,
        "admin_token":"a"*20,
    }
    values.update(overrides)
    return Settings(**values)


def test_timeframe_must_match_source_feature_interval():
    configured=settings(research_timeframe="M5",source_candle_interval="5min")
    assert configured.research_timeframe=="M5"
    with pytest.raises(ValidationError):
        settings(research_timeframe="M1",source_candle_interval="5min")


def test_matching_m1_configuration_is_accepted():
    configured=settings(research_timeframe="M1",source_candle_interval="1min")
    assert configured.research_timeframe=="M1"
