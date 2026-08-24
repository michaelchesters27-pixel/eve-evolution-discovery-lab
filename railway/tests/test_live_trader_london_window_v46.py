from __future__ import annotations

from datetime import datetime, timezone

from app.services import live_trader as core
from app.services import live_trader_london_window_v46 as v46


def utc(year: int, month: int, day: int, hour: int, minute: int) -> datetime:
    return datetime(year, month, day, hour, minute, tzinfo=timezone.utc)


def pending(created_at: str) -> dict:
    return {
        "version": "eve-live-trade-lock-v1",
        "id": "window-test",
        "symbol": "XAU/USD",
        "status": "pending",
        "side": "BUY",
        "order_type": "buy_limit",
        "entry": 4600.0,
        "stop": 4590.0,
        "target": 4620.0,
        "risk_reward": 2.0,
        "confidence": 70,
        "reason": "test",
        "invalidation": "Cancel below 4590",
        "invalidation_price": 4590.0,
        "created_at": created_at,
        "expires_at": "2026-08-24T18:00:00+00:00",
        "triggered_at": None,
        "completed_at": None,
        "result": None,
        "last_price": 4605.0,
        "last_checked_at": created_at,
        "published_trade": {
            "action": "BUY LIMIT",
            "side": "BUY",
            "order_type": "buy_limit",
            "entry": 4600.0,
            "stop": 4590.0,
            "target": 4620.0,
        },
    }


def test_london_window_is_dst_aware() -> None:
    # 24 Aug 2026 is BST: 07:20 UTC == 08:20 London.
    assert v46._window_assessment(utc(2026, 8, 24, 7, 19))["open"] is False
    assert v46._window_assessment(utc(2026, 8, 24, 7, 20))["open"] is True
    assert v46._window_assessment(utc(2026, 8, 24, 15, 59))["open"] is True
    assert v46._window_assessment(utc(2026, 8, 24, 16, 0))["open"] is False

    # 1 Dec 2026 is GMT: UTC and London clocks match.
    assert v46._window_assessment(utc(2026, 12, 1, 8, 19))["open"] is False
    assert v46._window_assessment(utc(2026, 12, 1, 8, 20))["open"] is True
    assert v46._window_assessment(utc(2026, 12, 1, 17, 0))["open"] is False


def test_weekend_is_never_inside_trade_idea_window() -> None:
    # Saturday lunchtime in London.
    assert v46._window_assessment(utc(2026, 8, 29, 11, 0))["open"] is False


def test_no_new_trade_is_published_before_0820(monkeypatch) -> None:
    trader = core.LiveTrader.__new__(core.LiveTrader)
    trader._live_campaign = None
    monkeypatch.setattr(v46, "_window_assessment", lambda now_utc=None: {
        "version": v46.WINDOW_VERSION,
        "timezone": "Europe/London",
        "start": "08:20",
        "end": "17:00",
        "open": False,
        "london_time": "2026-08-24T08:19:00+01:00",
        "weekday": 0,
    })
    monkeypatch.setattr(v46, "_original_trade_idea", lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("must not publish")))

    setup, trade = v46._trade_idea_v46(trader, 4600.0, 8.0, {}, {}, {})

    assert setup["status"] == "SESSION WAIT"
    assert trade["action"] == "WAIT"
    assert trade["order_type"] == "none"
    assert trade["trade_window_blocked"] is True


def test_new_trade_reaches_existing_chain_inside_window(monkeypatch) -> None:
    trader = core.LiveTrader.__new__(core.LiveTrader)
    trader._live_campaign = None
    assessment = {
        "version": v46.WINDOW_VERSION,
        "timezone": "Europe/London",
        "start": "08:20",
        "end": "17:00",
        "open": True,
        "london_time": "2026-08-24T10:00:00+01:00",
        "weekday": 0,
    }
    monkeypatch.setattr(v46, "_window_assessment", lambda now_utc=None: dict(assessment))
    monkeypatch.setattr(
        v46,
        "_original_trade_idea",
        lambda *args, **kwargs: ({"status": "ARMED"}, {"action": "BUY LIMIT", "order_type": "buy_limit"}),
    )

    setup, trade = v46._trade_idea_v46(trader, 4600.0, 8.0, {}, {}, {})

    assert setup["status"] == "ARMED"
    assert trade["action"] == "BUY LIMIT"
    assert trade["trade_window"]["open"] is True


def test_pending_idea_published_outside_window_is_cancelled_even_after_window_opens(monkeypatch) -> None:
    trader = core.LiveTrader.__new__(core.LiveTrader)
    # 06:52 UTC is 07:52 BST: before the 08:20 London start.
    trader._live_campaign = pending("2026-08-24T06:52:00+00:00")
    trader._live_campaign_dirty = False
    assessment = {
        "version": v46.WINDOW_VERSION,
        "timezone": "Europe/London",
        "start": "08:20",
        "end": "17:00",
        "open": True,
        "london_time": "2026-08-24T08:35:00+01:00",
        "weekday": 0,
    }
    real_assessment = v46._window_assessment
    monkeypatch.setattr(
        v46,
        "_window_assessment",
        lambda now_utc=None: real_assessment(now_utc) if now_utc is not None else dict(assessment),
    )

    setup, trade = v46._trade_idea_v46(trader, 4605.0, 8.0, {}, {}, {})

    assert trader._live_campaign["status"] == "expired"
    assert trader._live_campaign["triggered_at"] is None
    assert trader._live_campaign["trade_window_expiry"]["reason"] == "published_outside_window"
    assert trader._live_campaign_dirty is True
    assert setup["status"] == "SESSION WAIT"
    assert trade["action"] == "CANCEL — OUTSIDE TRADE WINDOW"
    assert trade["order_type"] == "none"


def test_pending_idea_is_cancelled_when_1700_arrives(monkeypatch) -> None:
    trader = core.LiveTrader.__new__(core.LiveTrader)
    # 08:30 UTC is 09:30 BST, so this was a valid publication time.
    trader._live_campaign = pending("2026-08-24T08:30:00+00:00")
    trader._live_campaign_dirty = False
    assessment = {
        "version": v46.WINDOW_VERSION,
        "timezone": "Europe/London",
        "start": "08:20",
        "end": "17:00",
        "open": False,
        "london_time": "2026-08-24T17:00:00+01:00",
        "weekday": 0,
    }
    real_assessment = v46._window_assessment
    monkeypatch.setattr(
        v46,
        "_window_assessment",
        lambda now_utc=None: real_assessment(now_utc) if now_utc is not None else dict(assessment),
    )

    _, trade = v46._trade_idea_v46(trader, 4605.0, 8.0, {}, {}, {})

    assert trader._live_campaign["status"] == "expired"
    assert trader._live_campaign["trade_window_expiry"]["reason"] == "window_closed_before_entry"
    assert trade["action"] == "CANCEL — OUTSIDE TRADE WINDOW"


def test_active_trade_is_preserved_after_1700(monkeypatch) -> None:
    trader = core.LiveTrader.__new__(core.LiveTrader)
    trader._live_campaign = pending("2026-08-24T08:30:00+00:00")
    trader._live_campaign["status"] = "active"
    trader._live_campaign["triggered_at"] = "2026-08-24T09:00:00+00:00"
    assessment = {
        "version": v46.WINDOW_VERSION,
        "timezone": "Europe/London",
        "start": "08:20",
        "end": "17:00",
        "open": False,
        "london_time": "2026-08-24T17:30:00+01:00",
        "weekday": 0,
    }
    monkeypatch.setattr(v46, "_window_assessment", lambda now_utc=None: dict(assessment))
    monkeypatch.setattr(
        v46,
        "_original_trade_idea",
        lambda *args, **kwargs: (
            {"status": "TRADE ACTIVE", "reason": "locked"},
            {"action": "BUY ACTIVE", "order_type": "buy_limit", "entry": 4600.0, "stop": 4590.0, "target": 4620.0},
        ),
    )

    setup, trade = v46._trade_idea_v46(trader, 4605.0, 8.0, {}, {}, {})

    assert trader._live_campaign["status"] == "active"
    assert trade["action"] == "BUY ACTIVE"
    assert trade["stop"] == 4590.0
    assert trade["target"] == 4620.0
    assert "original stop and target remain locked" in trade["trade_window_warning"]
    assert setup["trade_window"]["open"] is False
