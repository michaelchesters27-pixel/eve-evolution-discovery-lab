from __future__ import annotations

from datetime import datetime, timezone

from app.services import backtest_v3 as research
from app.services import evidence_miner
from app.services import compact_research_rows_v96 as compact


def make_row(year: int, index: int) -> dict:
    direction = 1 if index % 2 == 0 else -1
    close = 1800.0 + year - 2020 + index * 0.1
    outcome = {}
    for horizon in (5, 15, 30, 60, 240):
        outcome[str(horizon)] = {
            "direction": "up" if direction > 0 else "down",
            "first_side": "favourable",
            "max_up_atr": 2.4 if direction > 0 else 0.5,
            "continuation": True,
            "max_down_atr": 0.5 if direction > 0 else 2.4,
            "max_up_price": 4.8 if direction > 0 else 1.0,
            "max_down_price": 1.0 if direction > 0 else 4.8,
            "close_return_pct": 0.08 * direction,
        }
    stamp = datetime(year, 1 + (index % 10), 1 + (index % 20), 10 + (index % 6), (index % 4) * 15, tzinfo=timezone.utc)
    return {
        "symbol": "XAU/USD",
        "snapshot_interval": "15min",
        "source_interval": "5min",
        "candle_time": stamp.isoformat(),
        "open": close - 0.2 * direction,
        "high": close + 1.0,
        "low": close - 1.0,
        "close": close,
        "volume": 100.0,
        "weekday": index % 5,
        "month": stamp.month,
        "quarter": 1,
        "hour_utc": stamp.hour,
        "week_of_month": 1,
        "session": "london" if index % 2 == 0 else "new_york",
        "direction": direction,
        "range_price": 2.0,
        "body_price": 0.2,
        "upper_wick": 0.4,
        "lower_wick": 0.4,
        "close_location": 0.75 if direction > 0 else 0.25,
        "atr_14": 2.0,
        "average_range_12": 2.0,
        "volatility_12": 1.0,
        "compression_ratio": 1.0,
        "return_1_pct": 0.01 * direction,
        "return_3_pct": 0.03 * direction,
        "return_12_pct": 0.05 * direction,
        "return_48_pct": 0.08 * direction,
        "return_288_pct": 0.1 * direction,
        "context_m15_return_pct": 0.01,
        "context_h1_return_pct": 0.02,
        "context_h4_return_pct": 0.03,
        "context_d1_return_pct": 0.04,
        "trend_12_atr": 0.5 * direction,
        "trend_48_atr": 0.6 * direction,
        "streak": 2 * direction,
        "regime": "trend_up" if direction > 0 else "trend_down",
        "alignment_score": 3 * direction,
        "outcomes": outcome,
        "outcome_horizons": [5, 15, 30, 60, 240],
        "outcome_complete": True,
        "feature_version": "fixture-v1",
        "imported_at": stamp.isoformat(),
    }


def candidate() -> dict:
    return {
        "name": "compact parity fixture",
        "rules": {
            "family": "momentum_continuation",
            "market": {
                "symbol": "XAU/USD",
                "snapshot_interval": "15min",
                "source_interval": "5min",
            },
            "schedule": {"weekdays": [], "months": [], "sessions": [], "hours_utc": []},
            "environment": {
                "regimes": [],
                "trend_12": "directional",
                "trend_48": "directional",
                "compression": "any",
                "min_alignment_abs": 0,
                "alignment_sign": "any",
                "streak": "any",
            },
            "entry": {"direction_rule": "current_direction"},
            "risk": {
                "horizon_minutes": 60,
                "stop_atr": 1.0,
                "target_atr": 2.0,
                "cost_r": 0.04,
                "cooldown_minutes": 15,
                "max_hold_minutes": 60,
            },
        },
    }


def test_compact_rows_preserve_exact_backtest_result_and_dataset_hash() -> None:
    full = [make_row(year, index) for year in range(2020, 2027) for index in range(80)]
    compact_rows = [compact.compact_row(dict(row)) for row in full]

    research.enrich_market_observations(full)
    research.enrich_market_observations(compact_rows)

    full_result = research.evaluate_strategy(candidate(), full, stage="selection", min_validation_trades=20)
    compact_result = research.evaluate_strategy(candidate(), compact_rows, stage="selection", min_validation_trades=20)

    assert compact_result == full_result
    assert compact_result["dataset_version"] == full_result["dataset_version"]
    assert compact_result["evidence"]["dataset"]["content_sha256"] == full_result["evidence"]["dataset"]["content_sha256"]


def test_compact_row_preserves_hot_outcome_values_without_retaining_nested_tree() -> None:
    row = make_row(2026, 1)
    item = compact.compact_row(row)
    outcome = compact.research_outcome(item, 60)
    assert outcome == {
        "max_up_atr": row["outcomes"]["60"]["max_up_atr"],
        "max_down_atr": row["outcomes"]["60"]["max_down_atr"],
        "close_return_pct": row["outcomes"]["60"]["close_return_pct"],
    }
    assert evidence_miner._stored_return(item, 60) == row["outcomes"]["60"]["close_return_pct"]
    assert compact.fingerprint_outcomes(item) == row["outcomes"]


def test_compact_rows_accept_causal_observation_writes_without_per_row_source_dict_growth() -> None:
    rows = [compact.compact_row(make_row(2026, index)) for index in range(60)]
    result = research.enrich_market_observations(rows)
    assert len(result) == len(rows)
    assert result[-1].get("observation_version") == research.OBSERVATION_VERSION
    assert result[-1].get("obs_prior_12_high") is not None
    assert result[-1]._extras is None
