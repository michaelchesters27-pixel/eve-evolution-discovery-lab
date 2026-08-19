from datetime import datetime, timedelta, timezone

from app.services import backtest_v3 as research
from app.services.intelligence_v2 import IntelligenceDirector, STRUCTURE_POOL


def _row(time, *, o=100.0, h=101.0, l=99.0, c=100.5, direction=1, session="london"):
    return {
        "symbol": "XAU/USD",
        "snapshot_interval": "15min",
        "source_interval": "5min",
        "candle_time": time.isoformat(),
        "open": o,
        "high": h,
        "low": l,
        "close": c,
        "weekday": time.isoweekday(),
        "month": time.month,
        "hour_utc": time.hour,
        "session": session,
        "regime": "range",
        "direction": direction,
        "range_price": h - l,
        "body_price": abs(c - o),
        "upper_wick": max(0.0, h - max(o, c)),
        "lower_wick": max(0.0, min(o, c) - l),
        "close_location": (c - l) / max(1e-9, h - l),
        "atr_14": 2.0,
        "average_range_12": 2.0,
        "compression_ratio": 1.0,
        "return_1_pct": 0.01,
        "return_3_pct": 0.03,
        "trend_12_atr": 0.2,
        "trend_48_atr": 0.1,
        "alignment_score": 2,
        "streak": 1,
        "outcomes": {
            "15": {"max_up_atr": 1.5, "max_down_atr": 0.1, "close_return_pct": 0.1},
            "60": {"max_up_atr": 2.0, "max_down_atr": 0.2, "close_return_pct": 0.2},
            "240": {"max_up_atr": 3.0, "max_down_atr": 0.3, "close_return_pct": 0.3},
        },
        "outcome_complete": True,
        "feature_version": "test",
    }


def _rules(*conditions, direction_rule="structure_direction", hold=15, cooldown=15):
    return {
        "family": "composed_signal",
        "market": {
            "symbol": "XAU/USD",
            "timeframe": "M5",
            "execution_timeframe": "M5",
            "snapshot_interval": "15min",
            "source_interval": "5min",
        },
        "schedule": {"weekdays": [1, 2, 3, 4, 5, 6, 7], "months": list(range(1, 13)), "sessions": [], "hours_utc": []},
        "environment": {"regimes": [], "trend_12": "any", "trend_48": "any", "compression": "any", "min_alignment_abs": 0, "alignment_sign": "any", "streak": "any"},
        "entry": {"direction_rule": direction_rule, "condition_mode": "all", "conditions": list(conditions)},
        "risk": {"stop_atr": 0.75, "target_atr": 1.5, "horizon_minutes": 15, "max_hold_minutes": hold, "cooldown_minutes": cooldown, "cost_r": 0.04},
    }


def test_previous_day_liquidity_sweep_is_causal_and_directional():
    start = datetime(2026, 8, 17, 8, 0, tzinfo=timezone.utc)
    rows = []
    # Completed prior day range: high 105, low 95.
    for i in range(8):
        rows.append(_row(start + timedelta(minutes=15 * i), h=105.0 if i == 2 else 103.0, l=95.0 if i == 4 else 97.0, c=100.0))
    next_day = datetime(2026, 8, 18, 8, 0, tzinfo=timezone.utc)
    # Sweep below 95 then reclaim above it: bullish liquidity sweep.
    rows.append(_row(next_day, o=96.0, h=99.0, l=94.0, c=97.0, direction=1))

    enriched = research.enrich_market_observations(rows)
    event = enriched[-1]
    assert event["obs_previous_day_low"] == 95.0
    assert event["obs_prev_day_low_sweep"] is True
    assert event["obs_structure_direction"] == 1
    assert research.recipe_condition_matches(event, {"type": "prev_day_low_sweep_reclaim"}) is True
    assert research.candidate_direction(event, _rules({"type": "prev_day_low_sweep_reclaim"})) == 1


def test_rolling_high_sweep_reclaim_is_detected_without_forward_data():
    start = datetime(2026, 8, 18, 8, 0, tzinfo=timezone.utc)
    rows = [_row(start + timedelta(minutes=15 * i), h=100 + i * 0.1, l=98.0, c=99.5) for i in range(12)]
    prior_high = max(row["high"] for row in rows)
    rows.append(_row(start + timedelta(minutes=15 * 12), o=99.7, h=prior_high + 0.5, l=99.0, c=prior_high - 0.2, direction=-1))
    event = research.enrich_market_observations(rows)[-1]
    assert event["obs_sweep_prior_12_high"] is True
    assert research.recipe_condition_matches(event, {"type": "sweep_prior_12_high_reclaim"}) is True
    assert event["obs_structure_direction"] == -1


def test_trade_record_timestamp_is_actual_m5_entry_time():
    signal = datetime(2026, 8, 18, 10, 0, tzinfo=timezone.utc)
    rows = [_row(signal, h=102.0, l=99.0, c=101.0)]
    rules = _rules({"type": "direction_matches_trend12"}, direction_rule="current_direction")
    records = research._trade_records_v3(rows, rules)
    assert len(records) == 1
    assert records[0].time == signal + timedelta(minutes=5)


def test_moving_block_monte_carlo_reports_cluster_model():
    start = datetime(2020, 1, 6, 8, 0, tzinfo=timezone.utc)
    rows = []
    for i in range(90):
        row = _row(start + timedelta(minutes=15 * i), c=101.0)
        # Preserve enough trade count while alternating clusters of positive and negative outcomes.
        winning_cluster = (i // 6) % 2 == 0
        row["outcomes"]["15"] = {
            "max_up_atr": 1.8 if winning_cluster else 0.1,
            "max_down_atr": 0.1 if winning_cluster else 1.0,
            "close_return_pct": 0.1 if winning_cluster else -0.1,
        }
        rows.append(row)
    rules = _rules({"type": "direction_matches_trend12"}, direction_rule="current_direction")
    result = research.monte_carlo_sequence_v3(rows, rules, simulations=40)
    assert result["method"] == "moving_block_bootstrap"
    assert result["block_size"] >= 3
    assert result["simulations"] == 40


def test_scientist_v2_has_structure_observation_grammar():
    kinds = {item["type"] for item in STRUCTURE_POOL}
    assert "prev_day_low_sweep_reclaim" in kinds
    assert "sweep_prior_12_high_reclaim" in kinds
    assert "compression_release" in kinds
    assert "displacement_atr_min" in kinds


def test_structure_rules_are_flagged_for_mt5_parity_guard():
    assert research.has_structure_conditions(_rules({"type": "prev_day_low_sweep_reclaim"})) is True
    assert research.has_structure_conditions(_rules({"type": "direction_matches_trend12"}, direction_rule="current_direction")) is False
