from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace

from app.services import live_trader_execution_cost_model as cost_model
from app.services import live_trader_execution_costs_v90 as v90
from app.services import live_trader_policy_lab_v85 as v85


def settings(**overrides):
    values = {
        "live_trader_manual_delay_seconds": 15,
        "live_trader_cost_spread_price": 0.30,
        "live_trader_cost_entry_slippage_price": 0.10,
        "live_trader_cost_exit_slippage_price": 0.10,
        "live_trader_cost_commission_price_equivalent": 0.07,
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def profile() -> dict:
    return cost_model.profile_from_settings(settings())


def trade(*, entry: float = 100.0, stop: float = 95.0, order_type: str = "buy_limit") -> dict:
    return {
        "side": "BUY",
        "order_type": order_type,
        "entry": entry,
        "stop": stop,
        "target": entry + abs(entry - stop) * 1.5,
        "risk_reward": 1.5,
        "execution_cost_model": profile(),
    }


def test_raw_price_cost_is_converted_by_original_risk_distance() -> None:
    gross = {
        "entry_triggered": True,
        "trade_outcome": "target",
        "realised_r": 1.5,
        "learning_success": True,
    }
    wide = cost_model.apply_cost_model(trade(entry=100, stop=95), gross, [{"open": 100.0}])
    tight = cost_model.apply_cost_model(trade(entry=100, stop=98), gross, [{"open": 100.0}])

    # Same raw execution cost = 0.57, but it consumes more R on a tighter stop.
    assert wide["estimated_cost_r"] == 0.114
    assert wide["net_realised_r"] == 1.386
    assert tight["estimated_cost_r"] == 0.285
    assert tight["net_realised_r"] == 1.215
    assert wide["gross_realised_r"] == 1.5


def test_market_manual_delay_adverse_move_is_added_to_cost() -> None:
    item = trade(entry=100, stop=98, order_type="market")
    gross = {
        "entry_triggered": True,
        "trade_outcome": "target",
        "realised_r": 1.5,
        "learning_success": True,
    }
    result = cost_model.apply_cost_model(item, gross, [{"open": 100.4}])

    # Base 0.57 + 0.40 adverse move = 0.97 price units / 2.0 planned risk.
    assert result["execution_costs"]["manual_delay_adverse_price"] == 0.4
    assert result["estimated_cost_r"] == 0.485
    assert result["net_realised_r"] == 1.015


def test_untriggered_pending_order_pays_no_execution_cost() -> None:
    result = cost_model.apply_cost_model(
        trade(),
        {
            "entry_triggered": False,
            "trade_outcome": "not_triggered",
            "realised_r": 0.0,
            "learning_success": None,
        },
        [],
    )
    assert result["estimated_cost_r"] == 0.0
    assert result["net_realised_r"] == 0.0
    assert result["execution_costs"]["cost_applied"] is False


def test_cost_adjustment_can_turn_marginal_gross_trade_into_learning_failure() -> None:
    item = trade(entry=100, stop=99, order_type="market")
    gross = {
        "entry_triggered": True,
        "trade_outcome": "expired_win",
        "realised_r": 0.10,
        "learning_success": True,
    }
    result = cost_model.apply_cost_model(item, gross, [{"open": 100.0}])
    assert result["gross_realised_r"] == 0.10
    assert result["net_realised_r"] == -0.47
    assert result["learning_success"] is False
    assert result["net_learning_success"] is False


def test_manual_execution_start_waits_delay_then_uses_next_full_m1() -> None:
    activation = datetime(2026, 9, 22, 8, 0, 55, tzinfo=timezone.utc)
    eligible, start = cost_model.manual_execution_start(activation, profile())
    assert eligible == datetime(2026, 9, 22, 8, 1, 10, tzinfo=timezone.utc)
    assert start == datetime(2026, 9, 22, 8, 2, 0, tzinfo=timezone.utc)


def test_v90_wraps_v88_gross_result_with_costs() -> None:
    item = trade(entry=100, stop=95, order_type="buy_limit")
    bars = [{"open": 105.0, "high": 108.0, "low": 99.0, "close": 108.0}]
    result = v90._trade_path_result_v90(item, bars, 108.0)
    assert result["realised_r"] == 1.5
    assert result["gross_realised_r"] == 1.5
    assert result["net_realised_r"] < 1.5
    assert result["cost_model_version"] == cost_model.COST_MODEL_VERSION


def test_policy_lab_cannot_qualify_on_positive_gross_but_negative_net() -> None:
    rows = []
    for index in range(30):
        rows.append(
            {
                "observed_at": f"2026-09-{(index % 15) + 1:02d}T10:00:00+00:00",
                "entry_triggered": True,
                "realised_r": 0.20,
                "gross_realised_r": 0.20,
                "net_realised_r": -0.05,
                "cost_model_version": cost_model.COST_MODEL_VERSION,
                "trade_outcome": "expired_win",
                "timing_contract_version": v85.hardening.TIMING_CONTRACT_VERSION,
                "trade_idea": {"policy_lab": {"policy_key": "directional_quality_market"}},
            }
        )
    stats = v85._policy_stats(rows)
    leader = next(item for item in stats["leaderboard"] if item["policy_key"] == "directional_quality_market")
    assert leader["gross_expectancy_r"] == 0.2
    assert leader["net_expectancy_r"] == -0.05
    assert leader["forward_candidate"] is False
