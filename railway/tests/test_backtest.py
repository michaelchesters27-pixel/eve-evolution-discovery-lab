from datetime import datetime, timedelta, timezone

from app.services.backtest import evaluate_strategy, compare_child_to_parent, row_is_eligible


def rules():
    return {
        "family": "momentum_continuation",
        "schedule": {
            "weekdays": [1,2,3,4,5,6,7], "months": list(range(1,13)),
            "sessions": [], "hours_utc": list(range(24)), "everyday_target": True,
        },
        "environment": {
            "regimes": [], "trend_12": "any", "trend_48": "any", "compression": "any",
            "min_alignment_abs": 0, "alignment_sign": "any", "streak": "any",
        },
        "entry": {"direction_rule": "current_direction"},
        "risk": {"stop_atr": .75, "target_atr": 1.5, "horizon_minutes": 15, "max_hold_minutes": 15, "cooldown_minutes": 15, "cost_r": .04},
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
                "candle_time":t.isoformat(),"weekday":t.isoweekday(),"month":t.month,"hour_utc":t.hour,
                "session":"london","regime":"trend_up","direction":1,"trend_12_atr":.3,"trend_48_atr":.2,
                "compression_ratio":1.0,"alignment_score":3,"return_1_pct":.02,"return_3_pct":.08,
                "close_location":.8,"upper_wick":.1,"lower_wick":.05,"body_price":.3,"atr_14":2.0,"close":2000,
                "outcomes":{"15":{"max_up_atr":favourable,"max_down_atr":adverse,"close_return_pct":.1 if win else -.1}},
            })
    return rows


def test_eligible_and_strong_strategy_survives():
    candidate={"name":"Everyday Momentum","rules":rules()}
    assert row_is_eligible(synthetic_rows()[0], rules())
    result=evaluate_strategy(candidate,synthetic_rows(),min_validation_trades=50,min_locked_trades=50)
    assert result["result_status"] == "elite"
    assert result["profit_factor"] > 1.3
    assert result["stability_score"] == 100
    assert result["robustness"]["pass_rate"] >= .75


def test_bad_strategy_is_rejected():
    candidate={"name":"Bad Momentum","rules":rules()}
    result=evaluate_strategy(candidate,synthetic_rows(win=False),min_validation_trades=50,min_locked_trades=50)
    assert result["result_status"] == "rejected"
    assert result["expectancy_r"] < 0


def test_child_selection_uses_validation_and_locked_veto():
    result=evaluate_strategy({"name":"Child","rules":rules()},synthetic_rows(),min_validation_trades=50,min_locked_trades=50)
    result["fitness_score"] = 100
    comparison=compare_child_to_parent(result,{"validation":{"expectancy_r":0,"profit_factor":1},"locked":{"max_drawdown_r":5}},10)
    assert comparison["promoted"] is True
