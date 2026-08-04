from copy import deepcopy
from datetime import datetime, timedelta, timezone

from app.services.backtest import (
    candle_body,
    compare_child_to_parent,
    evaluate_segment,
    evaluate_strategy,
    recipe_condition_matches,
    row_is_eligible,
)


def rules(*, hold=15, cooldown=15):
    return {
        "family": "momentum_continuation",
        "market": {"symbol": "XAU/USD", "timeframe": "M5", "snapshot_interval": "15min", "source_interval": "5min"},
        "schedule": {
            "weekdays": [1,2,3,4,5,6,7], "months": list(range(1,13)),
            "sessions": [], "hours_utc": list(range(24)), "everyday_target": True,
        },
        "environment": {
            "regimes": [], "trend_12": "any", "trend_48": "any", "compression": "any",
            "min_alignment_abs": 0, "alignment_sign": "any", "streak": "any",
        },
        "entry": {"direction_rule": "current_direction"},
        "risk": {"stop_atr": .75, "target_atr": 1.5, "horizon_minutes": 15, "max_hold_minutes": hold, "cooldown_minutes": cooldown, "cost_r": .04},
    }


def synthetic_rows(win=True):
    rows=[]
    for year in range(2020, 2026):
        start=datetime(year,1,6,8,0,tzinfo=timezone.utc)
        for i in range(180):
            t=start+timedelta(minutes=15*i)
            favourable=1.8 if win else .1
            adverse=.1 if win else 1.0
            rows.append({
                "symbol":"XAU/USD","snapshot_interval":"15min","source_interval":"5min",
                "candle_time":t.isoformat(),"weekday":t.isoweekday(),"month":t.month,"hour_utc":t.hour,
                "session":"london","regime":"trend_up","direction":1,"trend_12_atr":.3,"trend_48_atr":.2,
                "compression_ratio":1.0,"alignment_score":3,"return_1_pct":.02,"return_3_pct":.08,
                "close_location":.8,"upper_wick":.1,"lower_wick":.05,"body_price":.3,"atr_14":2.0,"close":2000,
                "outcomes":{"15":{"max_up_atr":favourable,"max_down_atr":adverse,"close_return_pct":.1 if win else -.1}},
                "feature_version":"test-v1","outcome_complete":True,
            })
    return rows


def test_eligible_and_strong_strategy_survives_final_stage():
    candidate={"name":"Everyday Momentum","rules":rules()}
    assert row_is_eligible(synthetic_rows()[0], rules())
    result=evaluate_strategy(candidate,synthetic_rows(),min_validation_trades=50,min_locked_trades=50,stage="final")
    assert result["result_status"] == "elite"
    assert result["profit_factor"] > 1.3
    assert result["stability_score"] == 100
    assert result["robustness"]["pass_rate"] >= .75


def test_bad_strategy_is_rejected():
    result=evaluate_strategy({"name":"Bad Momentum","rules":rules()},synthetic_rows(win=False),min_validation_trades=50,min_locked_trades=50,stage="final")
    assert result["result_status"] == "rejected"
    assert result["expectancy_r"] < 0


def test_child_selection_uses_validation_only_and_never_holdout():
    result=evaluate_strategy({"name":"Child","rules":rules()},synthetic_rows(),min_validation_trades=50,min_locked_trades=50,stage="selection")
    result["fitness_score"] = 100
    comparison=compare_child_to_parent(result,{"validation":{"expectancy_r":0,"profit_factor":1,"max_drawdown_r":5}},10)
    assert comparison["promoted"] is True
    assert comparison["holdout_used_for_selection"] is False
    assert result["metrics"]["holdout"]["sealed"] is True


def test_selection_result_is_unchanged_when_final_holdout_is_corrupted():
    original=synthetic_rows()
    corrupted=deepcopy(original)
    for row in corrupted:
        if row["candle_time"].startswith("2025-"):
            row["outcomes"]["15"]={"max_up_atr":.01,"max_down_atr":2.0,"close_return_pct":-.2}
    one=evaluate_strategy({"name":"A","rules":rules()},original,min_validation_trades=50,stage="selection")
    two=evaluate_strategy({"name":"A","rules":rules()},corrupted,min_validation_trades=50,stage="selection")
    assert one["fitness_score"] == two["fitness_score"]
    assert one["result_status"] == two["result_status"]
    assert one["dataset_version"] != two["dataset_version"]


def test_bearish_candle_body_is_absolute_for_wick_ratios():
    row={"body_price":-2.0,"open":2002.0,"close":2000.0,"upper_wick":1.0,"lower_wick":1.0}
    assert candle_body(row) == 2.0
    assert recipe_condition_matches(row,{"type":"wick_body_ratio_min","ratio":1.5}) is False


def test_backtest_enforces_one_position_at_a_time():
    rows=synthetic_rows()[:8]
    result=evaluate_segment(rows,rules(hold=60,cooldown=15))
    assert result.trades == 2


def test_source_interval_mismatch_is_rejected():
    row=synthetic_rows()[0]
    wrong=deepcopy(rules())
    wrong["market"]["source_interval"]="1min"
    assert row_is_eligible(row,wrong) is False
