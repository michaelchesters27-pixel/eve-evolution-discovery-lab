from __future__ import annotations

from app.services.live_trader_learning_v2 import (
    LEARNING_VERSION,
    _trade_path_result,
    calibration_from_rows,
    episode_key,
    family_signature,
)


def market_state(zone_id: str = "zone-a", *, as_of: str = "2026-08-21T09:15:00+00:00", session: str = "london") -> dict:
    return {
        "symbol": "XAU/USD",
        "as_of": as_of,
        "bias": {
            "overall": "bullish",
            "timeframes": {
                "D1": {"direction": "bullish"},
                "H4": {"direction": "bullish"},
                "H1": {"direction": "bearish"},
                "M30": {"direction": "bullish"},
                "M15": {"direction": "bullish"},
                "M5": {"direction": "bearish"},
            },
        },
        "market": {
            "session": session,
            "regime": "compression",
            "return_12_pct": 0.08,
            "return_48_pct": 0.14,
        },
        "trade": {"order_type": "buy_limit", "side": "BUY"},
        "zones": {
            "demand": [{"id": zone_id, "quality": 88, "distance_atr": 0.7, "status": "NEAR"}],
            "supply": [{"id": "supply-a", "quality": 70, "distance_atr": 3.5, "status": "ACTIVE"}],
        },
    }


def test_setup_family_and_episode_ignore_exact_zone_id_churn() -> None:
    first = market_state("demand-original")
    second = market_state("demand-relabelled")
    assert family_signature(first) == family_signature(second)
    assert episode_key(first) == episode_key(second)


def test_episode_changes_only_for_a_genuinely_separate_day_or_session() -> None:
    london_today = market_state("zone-a", as_of="2026-08-21T09:15:00+00:00", session="london")
    new_york_today = market_state("zone-a", as_of="2026-08-21T14:15:00+00:00", session="new_york")
    london_tomorrow = market_state("zone-a", as_of="2026-08-22T09:15:00+00:00", session="london")
    assert episode_key(london_today) != episode_key(new_york_today)
    assert episode_key(london_today) != episode_key(london_tomorrow)


def test_calibration_requires_independent_depth_and_multiple_days() -> None:
    eleven = [
        {
            "episode_key": f"episode-{index}",
            "observed_at": f"2026-08-{21 + (index % 2):02d}T10:00:00+00:00",
            "learning_success": index < 8,
        }
        for index in range(11)
    ]
    early = calibration_from_rows(eleven)
    assert early["samples"] == 11
    assert early["active"] is False
    assert early["confidence_adjustment"] == 0

    mature = [
        {
            "episode_key": f"episode-{index}",
            "observed_at": f"2026-08-{21 + (index % 3):02d}T10:00:00+00:00",
            "learning_success": index < 9,
        }
        for index in range(12)
    ]
    result = calibration_from_rows(mature)
    assert result["samples"] == 12
    assert result["independent_days"] == 3
    assert result["accuracy"] == 0.75
    assert result["active"] is True
    assert 0 < result["confidence_adjustment"] <= 6
    assert result["learning_version"] == LEARNING_VERSION


def test_calibration_deduplicates_episode_keys_defensively() -> None:
    rows = [
        {"episode_key": "same", "observed_at": "2026-08-21T10:00:00+00:00", "learning_success": True},
        {"episode_key": "same", "observed_at": "2026-08-21T10:05:00+00:00", "learning_success": False},
    ]
    result = calibration_from_rows(rows)
    assert result["samples"] == 1
    assert result["accuracy"] == 1.0


def test_trade_learning_scores_actual_limit_execution_path() -> None:
    trade = {
        "order_type": "buy_limit",
        "side": "BUY",
        "entry": 100.0,
        "stop": 98.0,
        "target": 104.0,
        "risk_reward": 2.0,
    }
    bars = [
        {"low": 100.4, "high": 102.0},
        {"low": 99.8, "high": 101.2},
        {"low": 100.5, "high": 104.2},
    ]
    result = _trade_path_result(trade, bars, 103.0)
    assert result["entry_triggered"] is True
    assert result["trade_outcome"] == "target"
    assert result["realised_r"] == 2.0
    assert result["learning_success"] is True


def test_same_bar_stop_and_target_is_scored_conservatively() -> None:
    trade = {
        "order_type": "market",
        "side": "BUY",
        "entry": 100.0,
        "stop": 98.0,
        "target": 104.0,
        "risk_reward": 2.0,
    }
    result = _trade_path_result(trade, [{"low": 97.5, "high": 104.5}], 101.0)
    assert result["trade_outcome"] == "stop"
    assert result["realised_r"] == -1.0
    assert result["learning_success"] is False
