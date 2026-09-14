from __future__ import annotations

from datetime import datetime, timezone

from app.services import live_trader_forward_shadow_learning_v83 as v83


def _bullish_state() -> dict:
    return {
        "symbol": "XAU/USD",
        "price": 4300.0,
        "as_of": "2026-09-14T10:15:00+00:00",
        "feed": {
            "connected": True,
            "last_tick_at": "2026-09-14T10:15:00+00:00",
        },
        "bias": {"overall": "bullish", "confidence": 72},
        "market": {"session": "london", "atr": 10.0},
        "zones": {
            "demand": [
                {
                    "low": 4282.0,
                    "high": 4290.0,
                    "quality": 74,
                    "distance_atr": 1.0,
                }
            ],
            "supply": [],
        },
        "setup_family": "abc123",
        "setup_signature": "abc123",
        "setup_family_descriptor": {"bias": "bullish"},
    }


def test_recent_observation_prefers_feed_timestamp() -> None:
    state = _bullish_state()
    state["as_of"] = "2026-09-14T09:00:00+00:00"
    now = datetime(2026, 9, 14, 10, 15, 30, tzinfo=timezone.utc)
    observed = v83._recent_observation_time(state, now=now)
    assert observed == datetime(2026, 9, 14, 10, 15, tzinfo=timezone.utc)


def test_shadow_candidates_are_research_only_and_valid() -> None:
    candidates = v83._shadow_candidates(_bullish_state())
    variants = {item["shadow_variant"] for item in candidates}
    assert variants == {"market_probe", "zone_touch_limit", "momentum_confirmation"}
    for candidate in candidates:
        assert candidate["shadow_only"] is True
        assert candidate["automatic_order_placement"] is False
        assert candidate["manual_only"] is True
        assert candidate["entry"] > 0
        assert candidate["stop"] > 0
        assert candidate["target"] > 0
        assert candidate["risk_reward"] == 1.5


def test_trade_skill_exposes_bad_forward_record() -> None:
    reviews = [
        {"triggered": True, "realised_r": -1.0, "outcome": "LOSS"}
        for _ in range(7)
    ]
    skill = v83._trade_skill_from_reviews(reviews)
    assert skill["published_triggered"] == 7
    assert skill["wins"] == 0
    assert skill["losses"] == 7
    assert skill["total_r"] == -7.0
    assert skill["score"] < 1.0
    assert skill["grade"] == "UNPROVEN"


def test_trade_skill_requires_sample_before_proven() -> None:
    reviews = [
        {"triggered": True, "realised_r": 0.5, "outcome": "WIN"}
        for _ in range(8)
    ]
    skill = v83._trade_skill_from_reviews(reviews)
    assert skill["grade"] == "UNPROVEN"
    assert skill["score"] <= 3.0


def test_trade_skill_can_become_proven_with_forward_evidence() -> None:
    reviews = [
        {"triggered": True, "realised_r": 1.0 if index % 2 == 0 else -1.0, "outcome": "DONE"}
        for index in range(40)
    ]
    # 50% win rate at 1:1 is not good enough to be called proven.
    skill = v83._trade_skill_from_reviews(reviews)
    assert skill["published_triggered"] == 40
    assert skill["score"] < 7.5

    better = [
        {"triggered": True, "realised_r": 1.5 if index % 3 != 0 else -1.0, "outcome": "DONE"}
        for index in range(45)
    ]
    better_skill = v83._trade_skill_from_reviews(better)
    assert better_skill["published_triggered"] == 45
    assert better_skill["score"] >= 7.5
    assert better_skill["grade"] == "PROVEN"
