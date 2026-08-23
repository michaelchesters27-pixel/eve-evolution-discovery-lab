from __future__ import annotations

from datetime import datetime, timezone

from app.services import live_trader as core
from app.services import live_trader_historical_runtime_v30 as runtime
from app.services import live_trader_red_folder_news_confirmation_v36 as confirm
from app.services import live_trader_trade_lock_v28 as lock


def utc(year: int, month: int, day: int, hour: int = 0, minute: int = 0) -> datetime:
    return datetime(year, month, day, hour, minute, tzinfo=timezone.utc)


def test_forex_factory_week_is_sunday_to_saturday_in_uk_time() -> None:
    assert confirm._week_start(utc(2026, 8, 23, 8)) .isoformat() == "2026-08-23"
    assert confirm._week_start(utc(2026, 8, 24, 12)).isoformat() == "2026-08-23"
    assert confirm._week_start(utc(2026, 8, 29, 12)).isoformat() == "2026-08-23"
    assert confirm._week_start(utc(2026, 8, 30, 12)).isoformat() == "2026-08-30"


def test_unconfirmed_week_forces_closed_safe_even_with_empty_calendar() -> None:
    base = {
        "status": "clear",
        "available": True,
        "new_trade_blocked": False,
        "forward_learning_blocked": False,
        "events": [],
    }
    result = confirm._apply_confirmation(base, None, utc(2026, 8, 23, 8))

    assert result["status"] == "week_unconfirmed"
    assert result["week_confirmed"] is False
    assert result["new_trade_blocked"] is True
    assert result["forward_learning_blocked"] is True
    assert result["week_start"] == "2026-08-23"
    assert result["week_end"] == "2026-08-29"


def test_confirmed_week_preserves_real_calendar_status() -> None:
    base = {
        "status": "armed",
        "available": True,
        "new_trade_blocked": False,
        "forward_learning_blocked": False,
    }
    row = {"week_start": "2026-08-23", "confirmed_at": "2026-08-23T08:00:00+00:00"}
    result = confirm._apply_confirmation(base, row, utc(2026, 8, 23, 8))

    assert result["status"] == "armed"
    assert result["week_confirmed"] is True
    assert result["new_trade_blocked"] is False


def test_unconfirmed_week_blocks_forward_learning_horizon() -> None:
    class Dummy:
        _news_status_v35 = {"available": True, "week_confirmed": False, "events": []}

    assert confirm._window_intersects_v36(Dummy(), utc(2026, 8, 24, 9), 60) is True


def test_latest_runtime_aliases_remain_compatible() -> None:
    assert core.LiveTrader._trade_idea is lock._trade_idea_v28
    assert core.LiveTrader.refresh_state is lock._refresh_state_v28
    assert core.LiveTrader.refresh_state is runtime._refresh_state_v30
