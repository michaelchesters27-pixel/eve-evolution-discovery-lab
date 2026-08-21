from __future__ import annotations

from datetime import timedelta
from types import SimpleNamespace

from app.services.live_trader import LiveTrader, utc_now
from app.services.live_trader_feed_guard import FEED_FRESHNESS_SECONDS


def trader() -> LiveTrader:
    settings = SimpleNamespace(
        live_trader_symbol="XAU/USD",
        live_trader_enabled=True,
        twelve_data_api_key="secret",
    )
    return LiveTrader(settings, SimpleNamespace())


def test_minute_stamped_feed_remains_fresh_between_updates() -> None:
    live = trader()
    live.connected = True
    live.last_tick_at = (utc_now() - timedelta(seconds=59)).isoformat()
    assert FEED_FRESHNESS_SECONDS == 90.0
    assert live._feed_is_fresh() is True


def test_feed_becomes_stale_after_tolerance_window() -> None:
    live = trader()
    live.connected = True
    live.last_tick_at = (utc_now() - timedelta(seconds=95)).isoformat()
    assert live._feed_is_fresh() is False


def test_disconnected_socket_is_never_reported_fresh() -> None:
    live = trader()
    live.connected = False
    live.last_tick_at = utc_now().isoformat()
    assert live._feed_is_fresh() is False


def test_runtime_exposes_freshness_policy() -> None:
    live = trader()
    status = live.runtime_status()
    assert status["feed_freshness_seconds"] == 90.0
    assert "minute-stamped" in status["feed_freshness_policy"]
