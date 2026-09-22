from __future__ import annotations

from app.services import live_trader_execution_integrity_v39 as integrity
from app.services import live_trader_execution_sequence_v41 as v41
from app.services import live_trader_execution_sequence_v88 as v88
from app.services import live_trader_execution_costs_v90 as v90
from app.services import live_trader_learning_v2 as v2


def bar(open_: float, high: float, low: float, close: float) -> dict:
    return {"open": open_, "high": high, "low": low, "close": close}


def test_buy_limit_does_not_credit_target_that_may_precede_fill() -> None:
    # Reproduces the audit counterexample: a valid path is
    # 105 -> 108(target) -> 99(entry fill) -> 100.5(close).
    trade = {"side": "BUY", "order_type": "buy_limit", "entry": 100, "stop": 95, "target": 107.5, "risk_reward": 1.5}
    result = v88._trade_path_result_v88(trade, [bar(105, 108, 99, 100.5)], 100.5)
    assert result["entry_triggered"] is True
    assert result["trade_outcome"] == "expired_flat"
    assert result["realised_r"] == 0.1
    assert result["learning_success"] is None
    assert result["entry_target_same_bar_ambiguous"] is True


def test_sell_limit_does_not_credit_target_that_may_precede_fill() -> None:
    trade = {"side": "SELL", "order_type": "sell_limit", "entry": 100, "stop": 105, "target": 92.5, "risk_reward": 1.5}
    # 95 -> 92(target) -> 101(entry fill) -> 99.5(close) is possible.
    result = v88._trade_path_result_v88(trade, [bar(95, 101, 92, 99.5)], 99.5)
    assert result["entry_triggered"] is True
    assert result["trade_outcome"] == "expired_flat"
    assert result["realised_r"] == 0.1
    assert result["entry_target_same_bar_ambiguous"] is True


def test_buy_limit_target_is_valid_when_close_proves_post_fill_traversal() -> None:
    trade = {"side": "BUY", "order_type": "buy_limit", "entry": 100, "stop": 95, "target": 107.5, "risk_reward": 1.5}
    result = v88._trade_path_result_v88(trade, [bar(105, 108, 99, 108)], 108)
    assert result == {
        "entry_triggered": True,
        "trade_outcome": "target",
        "realised_r": 1.5,
        "learning_success": True,
    }


def test_sell_limit_target_is_valid_when_close_proves_post_fill_traversal() -> None:
    trade = {"side": "SELL", "order_type": "sell_limit", "entry": 100, "stop": 105, "target": 92.5, "risk_reward": 1.5}
    result = v88._trade_path_result_v88(trade, [bar(95, 101, 92, 92)], 92)
    assert result == {
        "entry_triggered": True,
        "trade_outcome": "target",
        "realised_r": 1.5,
        "learning_success": True,
    }


def test_ambiguous_first_bar_carries_exposure_to_later_bar() -> None:
    trade = {"side": "BUY", "order_type": "buy_limit", "entry": 100, "stop": 95, "target": 107.5, "risk_reward": 1.5}
    bars = [
        bar(105, 108, 99, 100.5),   # target may precede fill; no credit
        bar(100.5, 108, 100, 107.8) # target now definitely occurs while exposed
    ]
    result = v88._trade_path_result_v88(trade, bars, 107.8)
    assert result["trade_outcome"] == "target"
    assert result["realised_r"] == 1.5
    assert result["entry_target_same_bar_ambiguous"] is True


def test_stop_remains_adverse_on_first_limit_fill_bar() -> None:
    trade = {"side": "BUY", "order_type": "buy_limit", "entry": 100, "stop": 95, "target": 107.5, "risk_reward": 1.5}
    result = v88._trade_path_result_v88(trade, [bar(105, 108, 94, 100)], 100)
    assert result == {
        "entry_triggered": True,
        "trade_outcome": "stop",
        "realised_r": -1.0,
        "learning_success": False,
    }


def test_market_and_stop_orders_retain_v39_semantics() -> None:
    trade = {"side": "BUY", "order_type": "buy_stop", "entry": 105, "stop": 100, "target": 115, "risk_reward": 2}
    result = v88._trade_path_result_v88(trade, [bar(103, 104, 99, 101), bar(101, 106, 101, 105)], 106)
    assert result["entry_triggered"] is False
    assert result["trade_outcome"] == "invalidated_before_entry"


def test_v88_gross_scorer_is_wrapped_by_v90_cost_scorer() -> None:
    assert integrity.EXECUTION_SCHEMA == v90.EXECUTION_SCHEMA
    assert integrity.REGRADER_VERSION == v90.REGRADER_VERSION
    assert v41.EXECUTION_SCHEMA == v90.EXECUTION_SCHEMA
    assert v41.REGRADER_VERSION == v90.REGRADER_VERSION
    assert v88.EXECUTION_SCHEMA == v90.EXECUTION_SCHEMA
    assert v88.REGRADER_VERSION == v90.REGRADER_VERSION
    assert integrity._trade_path_result_v39 is v90._trade_path_result_v90
    assert v2._trade_path_result is v90._trade_path_result_v90
