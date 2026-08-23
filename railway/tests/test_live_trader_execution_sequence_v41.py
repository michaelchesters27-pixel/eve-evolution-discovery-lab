from __future__ import annotations

import asyncio
from types import SimpleNamespace

from app.services import live_trader_execution_integrity_v39 as integrity
from app.services import live_trader_execution_sequence_v41 as sequence
from app.services import live_trader_learning_v2 as v2


def bar(open_: float, high: float, low: float, close: float) -> dict:
    return {"open": open_, "high": high, "low": low, "close": close}


def test_buy_limit_gap_through_entry_and_stop_is_live_equivalent_loss() -> None:
    trade = {"side": "BUY", "order_type": "buy_limit", "entry": 100, "stop": 98, "target": 104, "risk_reward": 2}
    result = sequence._trade_path_result_v41(trade, [bar(97, 98, 96, 97)], 97)
    assert result == {
        "entry_triggered": True,
        "trade_outcome": "stop",
        "realised_r": -1.0,
        "learning_success": False,
    }


def test_sell_limit_gap_through_entry_and_stop_is_live_equivalent_loss() -> None:
    trade = {"side": "SELL", "order_type": "sell_limit", "entry": 100, "stop": 102, "target": 96, "risk_reward": 2}
    result = sequence._trade_path_result_v41(trade, [bar(103, 104, 102, 103)], 103)
    assert result == {
        "entry_triggered": True,
        "trade_outcome": "stop",
        "realised_r": -1.0,
        "learning_success": False,
    }


def test_stop_order_still_uses_v39_preentry_invalidation() -> None:
    trade = {"side": "BUY", "order_type": "buy_stop", "entry": 105, "stop": 100, "target": 115, "risk_reward": 2}
    result = sequence._trade_path_result_v41(
        trade,
        [bar(103, 104, 99, 101), bar(101, 106, 101, 105)],
        106,
    )
    assert result["entry_triggered"] is False
    assert result["trade_outcome"] == "invalidated_before_entry"
    assert result["realised_r"] == 0.0
    assert result["learning_success"] is None


def test_regrader_old_version_state_forces_restart(monkeypatch) -> None:
    async def old_state(_self):
        return {"version": "eve-live-historical-execution-regrade-v1", "cursor_time": "2020-04-14T19:00:00+00:00"}

    monkeypatch.setattr(sequence, "_old_regrader_state", old_state)
    assert asyncio.run(sequence._state_v41(SimpleNamespace())) == {}


def test_regrader_current_version_state_resumes(monkeypatch) -> None:
    expected = {"version": sequence.REGRADER_VERSION, "cursor_time": "2021-01-01T00:00:00+00:00"}

    async def old_state(_self):
        return expected

    monkeypatch.setattr(sequence, "_old_regrader_state", old_state)
    assert asyncio.run(sequence._state_v41(SimpleNamespace())) == expected


def test_shared_execution_schema_and_scorer_are_v41() -> None:
    assert integrity.EXECUTION_SCHEMA == sequence.EXECUTION_SCHEMA
    assert integrity.REGRADER_VERSION == sequence.REGRADER_VERSION
    assert integrity._trade_path_result_v39 is sequence._trade_path_result_v41
    assert v2._trade_path_result is sequence._trade_path_result_v41
