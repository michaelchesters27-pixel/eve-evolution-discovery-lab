from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from types import SimpleNamespace

from app.services import live_trader as core
from app.services import live_trader_audit_hardening_v26 as hardening
from app.services import live_trader_execution_integrity_v39 as integrity
from app.services import live_trader_historical_learning_v29 as academy
from app.services import live_trader_historical_runtime_v30 as runtime
from app.services import live_trader_learning_v2 as v2
from app.services import live_trader_trade_lock_v28 as lock


def bar(open_: float, high: float, low: float, close: float) -> dict:
    return {"open": open_, "high": high, "low": low, "close": close}


def test_buy_stop_cancels_when_invalidation_trades_before_later_entry() -> None:
    trade = {"side": "BUY", "order_type": "buy_stop", "entry": 105, "stop": 100, "target": 115, "risk_reward": 2}
    result = integrity._trade_path_result_v39(
        trade,
        [bar(103, 104, 99, 101), bar(101, 106, 101, 105)],
        106,
    )
    assert result == {
        "entry_triggered": False,
        "trade_outcome": "invalidated_before_entry",
        "realised_r": 0.0,
        "learning_success": None,
    }


def test_sell_stop_cancels_when_invalidation_trades_before_later_entry() -> None:
    trade = {"side": "SELL", "order_type": "sell_stop", "entry": 95, "stop": 100, "target": 85, "risk_reward": 2}
    result = integrity._trade_path_result_v39(
        trade,
        [bar(97, 101, 96, 99), bar(99, 99, 94, 95)],
        94,
    )
    assert result["entry_triggered"] is False
    assert result["trade_outcome"] == "invalidated_before_entry"
    assert result["learning_success"] is None


def test_stop_order_same_bar_entry_and_invalidation_assumes_adverse_loss() -> None:
    trade = {"side": "BUY", "order_type": "buy_stop", "entry": 105, "stop": 100, "target": 115, "risk_reward": 2}
    result = integrity._trade_path_result_v39(trade, [bar(103, 106, 99, 102)], 102)
    assert result["entry_triggered"] is True
    assert result["trade_outcome"] == "stop_same_bar_ambiguous"
    assert result["realised_r"] == -1.0
    assert result["learning_success"] is False


def test_limit_order_crossing_entry_then_stop_is_a_loss_not_preentry_cancel() -> None:
    trade = {"side": "BUY", "order_type": "buy_limit", "entry": 100, "stop": 98, "target": 104, "risk_reward": 2}
    result = integrity._trade_path_result_v39(trade, [bar(102, 102.5, 97.5, 99)], 99)
    assert result["entry_triggered"] is True
    assert result["trade_outcome"] == "stop"
    assert result["realised_r"] == -1.0


def test_limit_order_gap_beyond_stop_is_preentry_invalidation() -> None:
    trade = {"side": "BUY", "order_type": "buy_limit", "entry": 100, "stop": 98, "target": 104, "risk_reward": 2}
    result = integrity._trade_path_result_v39(trade, [bar(97, 98, 96, 97)], 97)
    assert result["entry_triggered"] is False
    assert result["trade_outcome"] == "invalidated_before_entry"


def test_market_order_semantics_remain_stop_first() -> None:
    trade = {"side": "BUY", "order_type": "market", "entry": 100, "stop": 98, "target": 104, "risk_reward": 2}
    result = integrity._trade_path_result_v39(trade, [bar(100, 105, 97, 104)], 104)
    assert result["trade_outcome"] == "stop"
    assert result["realised_r"] == -1.0


def test_shared_v2_scorer_is_the_v39_scorer() -> None:
    assert v2._trade_path_result is integrity._trade_path_result_v39


def test_publication_window_uses_market_observation_time(monkeypatch) -> None:
    campaign = {"created_at": "2026-08-24T08:00:30+00:00"}
    monkeypatch.setattr(hardening, "_market_observation_time", lambda _state: datetime(2026, 8, 24, 8, 0, tzinfo=timezone.utc))
    assert integrity._campaign_publication_is_current(campaign, {}) is True
    campaign["created_at"] = "2026-08-24T07:55:00+00:00"
    assert integrity._campaign_publication_is_current(campaign, {}) is False


def test_old_active_campaign_followthrough_is_not_recorded(monkeypatch) -> None:
    calls: list[dict] = []

    async def fake_record(_self, state):
        calls.append(state)

    monkeypatch.setattr(integrity, "_current_record", fake_record)
    monkeypatch.setattr(integrity, "_campaign_publication_is_current", lambda _campaign, _state: False)
    trader = SimpleNamespace(_execution_regrade_ready_v39=True, _live_campaign={"status": "active"})
    asyncio.run(integrity._record_v39(trader, {"trade_campaign": {"status": "active"}}))
    assert calls == []


def test_terminal_campaign_display_is_not_recorded(monkeypatch) -> None:
    calls: list[dict] = []

    async def fake_record(_self, state):
        calls.append(state)

    monkeypatch.setattr(integrity, "_current_record", fake_record)
    trader = SimpleNamespace(_execution_regrade_ready_v39=True, _live_campaign={"status": "invalidated"})
    asyncio.run(integrity._record_v39(trader, {"trade_campaign": {"status": "invalidated"}}))
    assert calls == []


def test_no_campaign_still_records_normal_forward_decision(monkeypatch) -> None:
    calls: list[dict] = []

    async def fake_record(_self, state):
        calls.append(state)

    monkeypatch.setattr(integrity, "_current_record", fake_record)
    trader = SimpleNamespace(_execution_regrade_ready_v39=True, _live_campaign=None)
    state = {"trade": {"action": "WAIT", "order_type": "none"}}
    asyncio.run(integrity._record_v39(trader, state))
    assert calls == [state]


def test_new_trade_is_blocked_until_execution_regrade_is_ready(monkeypatch) -> None:
    monkeypatch.setattr(academy, "broker_market_open", lambda _at: True)
    trader = SimpleNamespace(_execution_regrade_ready_v39=False, _live_campaign=None)
    setup, trade = integrity._trade_idea_v39(trader, 100, 1, {}, {}, {})
    assert "REVALIDATION" in setup["status"]
    assert trade["action"] == "WAIT"
    assert trade["execution_revalidation_block"] is True


def test_open_campaign_management_continues_during_regrade(monkeypatch) -> None:
    monkeypatch.setattr(academy, "broker_market_open", lambda _at: True)
    monkeypatch.setattr(integrity, "_current_trade_idea", lambda *_args: ({"status": "TRADE ACTIVE"}, {"action": "SELL ACTIVE"}))
    trader = SimpleNamespace(_execution_regrade_ready_v39=False, _live_campaign={"status": "active"})
    setup, trade = integrity._trade_idea_v39(trader, 100, 1, {}, {}, {})
    assert setup["status"] == "TRADE ACTIVE"
    assert trade["action"] == "SELL ACTIVE"


def test_latest_runtime_aliases_point_to_v39() -> None:
    assert core.LiveTrader._trade_idea is integrity._trade_idea_v39
    assert core.LiveTrader._trade_idea is lock._trade_idea_v28
    assert core.LiveTrader._maybe_record_opinion is integrity._record_v39
    assert hardening._record_v26 is integrity._record_v39
    assert academy._record_v29 is integrity._record_v39
    assert core.LiveTrader.run_forever is integrity._run_forever_v39
    assert runtime._run_forever_v30 is integrity._run_forever_v39
