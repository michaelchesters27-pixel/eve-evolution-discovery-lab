from datetime import datetime, timezone

from app.services import live_trader as core
from app.services import live_trader_london_session_gate_v46 as v46


def _closed_session() -> dict:
    return {
        "version": v46.SESSION_GATE_VERSION,
        "timezone": "Europe/London",
        "local_time": "2026-08-24T08:00:00+01:00",
        "session_date": "2026-08-24",
        "weekday": "Monday",
        "start": "08:20",
        "end": "17:00",
        "end_exclusive": True,
        "open": False,
        "reason": "outside London trade-idea window",
    }


def _open_session() -> dict:
    payload = _closed_session()
    payload.update({"local_time": "2026-08-24T08:20:00+01:00", "open": True, "reason": "inside London trade-idea window"})
    return payload


def _campaign(status: str) -> dict:
    return {
        "version": "eve-live-trade-lock-v1",
        "id": "session-test",
        "symbol": "XAU/USD",
        "status": status,
        "side": "BUY",
        "order_type": "buy_limit",
        "entry": 4637.426,
        "stop": 4632.965,
        "target": 4647.24,
        "risk_reward": 2.2,
        "confidence": 69,
        "reason": "Original reason",
        "invalidation": "Cancel below 4632.97",
        "invalidation_price": 4632.97,
        "created_at": "2026-08-24T06:52:42+00:00",
        "expires_at": "2026-08-24T09:52:42+00:00",
        "triggered_at": "2026-08-24T07:30:00+00:00" if status == "active" else None,
        "completed_at": None,
        "result": None,
        "last_price": 4640.0,
        "last_checked_at": "2026-08-24T07:59:00+00:00",
        "published_trade": {
            "action": "BUY LIMIT",
            "side": "BUY",
            "order_type": "buy_limit",
            "entry": 4637.426,
            "stop": 4632.965,
            "target": 4647.24,
        },
    }


def test_summer_window_uses_london_dst() -> None:
    before = v46._session_status(datetime(2026, 8, 24, 7, 19, 59, tzinfo=timezone.utc))
    at_open = v46._session_status(datetime(2026, 8, 24, 7, 20, 0, tzinfo=timezone.utc))
    before_close = v46._session_status(datetime(2026, 8, 24, 15, 59, 59, tzinfo=timezone.utc))
    at_close = v46._session_status(datetime(2026, 8, 24, 16, 0, 0, tzinfo=timezone.utc))

    assert before["local_time"].startswith("2026-08-24T08:19:59+01:00")
    assert before["open"] is False
    assert at_open["local_time"].startswith("2026-08-24T08:20:00+01:00")
    assert at_open["open"] is True
    assert before_close["open"] is True
    assert at_close["local_time"].startswith("2026-08-24T17:00:00+01:00")
    assert at_close["open"] is False


def test_winter_window_uses_gmt_automatically() -> None:
    at_open = v46._session_status(datetime(2026, 12, 1, 8, 20, tzinfo=timezone.utc))
    assert at_open["local_time"].startswith("2026-12-01T08:20:00+00:00")
    assert at_open["open"] is True


def test_weekend_is_closed_even_during_clock_window() -> None:
    saturday = v46._session_status(datetime(2026, 8, 29, 9, 0, tzinfo=timezone.utc))
    assert saturday["weekday"] == "Saturday"
    assert saturday["open"] is False


def test_no_new_trade_generator_runs_before_0820(monkeypatch) -> None:
    trader = core.LiveTrader.__new__(core.LiveTrader)
    trader._live_campaign = None
    monkeypatch.setattr(v46, "_session_status", _closed_session)

    def should_not_run(*args, **kwargs):
        raise AssertionError("downstream trade generator must not run outside the London window")

    monkeypatch.setattr(v46, "_original_trade_idea", should_not_run)
    setup, trade = v46._trade_idea_v46(trader, 4640.0, 7.0, {}, {}, {})

    assert setup["status"] == "SESSION WAIT"
    assert trade["action"] == "WAIT"
    assert trade["order_type"] == "none"
    assert trade["session_blocked"] is True


def test_pending_order_is_cancelled_when_window_is_closed(monkeypatch) -> None:
    trader = core.LiveTrader.__new__(core.LiveTrader)
    trader._live_campaign = _campaign("pending")
    trader._live_campaign_dirty = False
    monkeypatch.setattr(v46, "_session_status", _closed_session)

    setup, trade = v46._trade_idea_v46(trader, 4640.0, 7.0, {}, {}, {})

    assert trader._live_campaign["status"] == "invalidated"
    assert trader._live_campaign["result"] == v46.SESSION_CANCEL_RESULT
    assert trader._live_campaign["triggered_at"] is None
    assert trader._live_campaign["session_invalidation"]["cancelled_before_entry"] is True
    assert trader._live_campaign_dirty is True
    assert setup["status"] == "IDEA CANCELLED"
    assert trade["action"] == "CANCEL — SESSION CLOSED"
    assert trade["order_type"] == "none"
    assert trade["campaign_locked"] is False


def test_active_trade_keeps_original_risk_after_1700(monkeypatch) -> None:
    trader = core.LiveTrader.__new__(core.LiveTrader)
    trader._live_campaign = _campaign("active")
    monkeypatch.setattr(v46, "_session_status", _closed_session)

    expected_trade = {
        "action": "BUY ACTIVE",
        "order_type": "buy_limit",
        "entry": 4637.426,
        "stop": 4632.965,
        "target": 4647.24,
    }
    monkeypatch.setattr(
        v46,
        "_original_trade_idea",
        lambda self, price, atr, bias, zones, liquidity: (
            {"status": "TRADE ACTIVE", "reason": "Locked trade active."},
            dict(expected_trade),
        ),
    )

    setup, trade = v46._trade_idea_v46(trader, 4640.0, 7.0, {}, {}, {})

    assert trader._live_campaign["status"] == "active"
    assert trader._live_campaign["stop"] == 4632.965
    assert trader._live_campaign["target"] == 4647.24
    assert trade["entry"] == expected_trade["entry"]
    assert trade["stop"] == expected_trade["stop"]
    assert trade["target"] == expected_trade["target"]
    assert trade["london_session_gate"]["open"] is False
    assert setup["london_session_gate"]["open"] is False


def test_inside_window_passes_to_existing_clear_bias_chain(monkeypatch) -> None:
    trader = core.LiveTrader.__new__(core.LiveTrader)
    trader._live_campaign = None
    monkeypatch.setattr(v46, "_session_status", _open_session)

    monkeypatch.setattr(
        v46,
        "_original_trade_idea",
        lambda self, price, atr, bias, zones, liquidity: (
            {"status": "ARMED", "reason": "Clear setup."},
            {"action": "BUY STOP", "order_type": "buy_stop"},
        ),
    )

    setup, trade = v46._trade_idea_v46(trader, 4640.0, 7.0, {}, {}, {})

    assert setup["status"] == "ARMED"
    assert trade["action"] == "BUY STOP"
    assert trade["london_session_gate"]["open"] is True


def test_latest_runtime_aliases_point_to_session_gate() -> None:
    from app.services import live_trader_clear_bias_gate_v45 as clear_gate
    from app.services import live_trader_execution_integrity_v39 as integrity
    from app.services import live_trader_trade_lock_v28 as lock

    assert core.LiveTrader._trade_idea is v46._trade_idea_v46
    assert integrity._trade_idea_v39 is v46._trade_idea_v46
    assert lock._trade_idea_v28 is v46._trade_idea_v46
    assert clear_gate._trade_idea_v45 is v46._trade_idea_v46
