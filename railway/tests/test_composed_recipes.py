from datetime import datetime, timedelta, timezone
import random

from app.services.backtest import evaluate_strategy, row_is_eligible
from app.services.composer import compose_batch, mutate_rules
from app.services.mt5_generator import generate_mq5_source, static_validate


def composite_rules():
    return {
        "family": "composed_signal",
        "schedule": {
            "weekdays": [1, 2, 3, 4, 5, 6, 7],
            "months": list(range(1, 13)),
            "sessions": [],
            "hours_utc": list(range(24)),
            "everyday_target": True,
        },
        "environment": {
            "regimes": [], "trend_12": "any", "trend_48": "any", "compression": "any",
            "min_alignment_abs": 0, "alignment_sign": "any", "streak": "any",
        },
        "entry": {
            "direction_rule": "alignment_direction",
            "condition_mode": "all",
            "conditions": [
                {"type": "direction_matches_trend12"},
                {"type": "alignment_abs_min", "min": 2},
                {"type": "trend12_trend48_agree"},
            ],
        },
        "risk": {
            "stop_atr": 0.75, "target_atr": 1.5, "horizon_minutes": 15,
            "max_hold_minutes": 15, "cooldown_minutes": 15, "cost_r": 0.04,
            "risk_percent": 0.25, "max_daily_loss_percent": 1.0, "max_spread_points": 100,
        },
    }


def rows():
    result = []
    for year in range(2020, 2026):
        start = datetime(year, 1, 6, 8, 0, tzinfo=timezone.utc)
        for i in range(180):
            time = start + timedelta(minutes=15 * i)
            result.append({
                "candle_time": time.isoformat(), "weekday": time.isoweekday(), "month": time.month,
                "hour_utc": time.hour, "session": "london", "regime": "trend_up", "direction": 1,
                "trend_12_atr": 0.3, "trend_48_atr": 0.2, "compression_ratio": 1.0,
                "alignment_score": 3, "return_1_pct": 0.02, "return_3_pct": 0.08,
                "close_location": 0.8, "upper_wick": 0.1, "lower_wick": 0.05,
                "body_price": 0.3, "atr_14": 2.0, "close": 2000,
                "outcomes": {"15": {"max_up_atr": 1.8, "max_down_atr": 0.1, "close_return_pct": 0.1}},
            })
    return result


def test_composer_prefers_independent_recipes():
    candidates = compose_batch(100, generation=1, seed=2026, everyday_bias=0.8)
    recipes = [item for item in candidates if item["family"] == "composed_signal"]
    assert len(recipes) >= 60
    assert all(len(item["rules"]["entry"]["conditions"]) >= 2 for item in recipes)
    assert all(item["name"].startswith("EVE Composite") for item in recipes)


def test_composed_recipe_backtests_and_generates_mq5():
    rules = composite_rules()
    assert row_is_eligible(rows()[0], rules)
    candidate = {"name": "Composite Test", "rules": rules}
    result = evaluate_strategy(candidate, rows(), min_validation_trades=50, min_locked_trades=50)
    assert result["result_status"] == "elite"
    assert result["evidence"]["decision"]["failed_gates"] == []

    frozen = {
        "name": "Composite Test", "strategy_code": "EVE-DISC-COMPOSITE01", "family": "composed_signal",
        "rule_hash": "c" * 64, "rules": rules, "metrics": result["metrics"],
        "walk_forward": result["walk_forward"], "robustness": result["robustness"],
        "evidence": result["evidence"], "stability_score": result["stability_score"],
    }
    _, source = generate_mq5_source(frozen)
    assert static_validate(source, "c" * 64) == []
    assert "f.direction == SignDouble(f.trend_12_atr)" in source
    assert "MathAbs(f.alignment_score) >= 2" in source


def test_recipe_mutation_can_change_structure():
    rules = composite_rules()
    mutation = mutate_rules(rules, random.Random(7), preferred_genes=["add_condition"])
    assert mutation.gene == "add_condition"
    assert len(mutation.rules["entry"]["conditions"]) == len(rules["entry"]["conditions"]) + 1
    assert rules["entry"]["conditions"] != mutation.rules["entry"]["conditions"]
