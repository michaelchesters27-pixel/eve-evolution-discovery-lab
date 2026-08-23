from __future__ import annotations

from datetime import datetime, timezone

from app.services import live_trader as core
from app.services import live_trader_audit_hardening_v26 as hardening
from app.services import live_trader_historical_runtime_v30 as runtime
from app.services import live_trader_red_folder_news_v35 as news
from app.services import live_trader_trade_lock_v28 as lock


def utc(year: int, month: int, day: int, hour: int, minute: int = 0) -> datetime:
    return datetime(year, month, day, hour, minute, tzinfo=timezone.utc)


def test_forex_factory_summer_time_is_converted_from_uk_bst_to_utc() -> None:
    row = news.build_manual_event(
        "XAU/USD",
        "2026-08-26",
        "13:30",
        "Core PCE Price Index m/m",
    )

    assert row["scheduled_local"].startswith("2026-08-26T13:30:00+01:00")
    assert row["scheduled_at"] == "2026-08-26T12:30:00+00:00"
    assert row["event_class"] == "major"
    assert row["pre_minutes"] == 45
    assert row["post_minutes"] == 30


def test_forex_factory_winter_time_uses_gmt() -> None:
    row = news.build_manual_event(
        "XAU/USD",
        "2026-12-02",
        "13:30",
        "Non-Farm Employment Change",
    )

    assert row["scheduled_local"].startswith("2026-12-02T13:30:00+00:00")
    assert row["scheduled_at"] == "2026-12-02T13:30:00+00:00"
    assert row["event_class"] == "major"


def test_non_major_red_folder_event_gets_standard_window() -> None:
    row = news.build_manual_event(
        "XAU/USD",
        "2026-08-26",
        "13:30",
        "Prelim GDP q/q",
    )

    assert row["event_class"] == "high"
    assert row["pre_minutes"] == 30
    assert row["post_minutes"] == 15


def test_news_status_blocks_only_inside_event_blackout() -> None:
    row = news.build_manual_event(
        "XAU/USD",
        "2026-08-26",
        "13:30",
        "Core PCE Price Index m/m",
    )

    before = news.news_status_from_rows([row], utc(2026, 8, 26, 11, 44))
    active = news.news_status_from_rows([row], utc(2026, 8, 26, 11, 45))
    after = news.news_status_from_rows([row], utc(2026, 8, 26, 13, 1))

    assert before["status"] == "armed"
    assert before["new_trade_blocked"] is False
    assert active["status"] == "blackout"
    assert active["new_trade_blocked"] is True
    assert active["active_window_end"] == "2026-08-26T13:00:00+00:00"
    assert after["status"] == "clear"
    assert after["new_trade_blocked"] is False


class Dummy:
    _live_campaign_dirty = False


def pending_campaign() -> dict:
    return {
        "status": "pending",
        "expires_at": "2026-08-26T14:00:00+00:00",
    }


def test_pending_campaign_pause_preserves_validity_clock(monkeypatch) -> None:
    engine = Dummy()
    item = pending_campaign()
    blackout = {
        "active_window_end": "2026-08-26T13:00:00+00:00",
        "active_event_ids": ["event-1"],
    }

    monkeypatch.setattr(news.core, "utc_now", lambda: utc(2026, 8, 26, 11, 45))
    news._pause_pending_campaign(engine, item, blackout)
    assert item["news_suspended"] is True
    assert item["expires_at"] == "2026-08-26T14:00:00+00:00"

    monkeypatch.setattr(news.core, "utc_now", lambda: utc(2026, 8, 26, 13, 0))
    news._resume_pending_campaign(engine, item)
    assert item["expires_at"] == "2026-08-26T15:15:00+00:00"
    assert "news_suspended" not in item


def test_forward_learning_horizon_overlapping_news_is_rejected() -> None:
    engine = Dummy()
    event = news.build_manual_event(
        "XAU/USD",
        "2026-08-26",
        "13:30",
        "Prelim GDP q/q",
    )
    engine._news_status_v35 = news.news_status_from_rows([event], utc(2026, 8, 26, 11, 0))

    # Event is 12:30 UTC, standard blackout begins 12:00. A 60m horizon
    # beginning 11:30 overlaps that blackout and must not become normal-market evidence.
    assert news._window_intersects_known_news(engine, utc(2026, 8, 26, 11, 30), 60) is True
    assert news._window_intersects_known_news(engine, utc(2026, 8, 26, 10, 30), 60) is False


def test_missing_calendar_fails_closed_for_new_trades_and_learning() -> None:
    status = news._unavailable_status("database unavailable")
    assert status["new_trade_blocked"] is True
    assert status["forward_learning_blocked"] is True
    assert status["available"] is False


def test_legacy_runtime_aliases_point_to_latest_news_wrappers() -> None:
    assert core.LiveTrader._trade_idea is lock._trade_idea_v28
    assert core.LiveTrader.refresh_state is lock._refresh_state_v28
    assert core.LiveTrader.refresh_state is runtime._refresh_state_v30
    assert core.LiveTrader._maybe_record_opinion is hardening._record_v26
