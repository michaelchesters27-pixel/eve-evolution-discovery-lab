from __future__ import annotations

from app.services.live_trader_learning_v22 import (
    LEARNING_VERSION,
    episode_key,
    family_signature,
    setup_family_descriptor,
    weighted_calibration_from_rows,
)


def state(
    *,
    bias: str = "bullish",
    session: str = "london",
    regime: str = "compression",
    order_type: str = "buy_limit",
    htf: tuple[str, str, str] = ("bullish", "bullish", "bearish"),
    intraday: tuple[str, str, str] = ("bullish", "bullish", "bearish"),
    demand_distance: float = 0.7,
    supply_distance: float = 3.5,
    demand_status: str = "NEAR",
    supply_status: str = "ACTIVE",
    quality: int = 88,
    m12: float = 0.08,
    m48: float = 0.14,
    as_of: str = "2026-08-21T09:15:00+00:00",
    zone_id: str = "demand-a",
) -> dict:
    d1, h4, h1 = htf
    m30, m15, m5 = intraday
    return {
        "symbol": "XAU/USD",
        "as_of": as_of,
        "bias": {
            "overall": bias,
            "timeframes": {
                "D1": {"direction": d1},
                "H4": {"direction": h4},
                "H1": {"direction": h1},
                "M30": {"direction": m30},
                "M15": {"direction": m15},
                "M5": {"direction": m5},
            },
        },
        "market": {
            "session": session,
            "regime": regime,
            "return_12_pct": m12,
            "return_48_pct": m48,
        },
        "trade": {"order_type": order_type, "side": "BUY" if bias == "bullish" else "SELL"},
        "zones": {
            "demand": [{"id": zone_id, "quality": quality, "distance_atr": demand_distance, "status": demand_status}],
            "supply": [{"id": "supply-a", "quality": 72, "distance_atr": supply_distance, "status": supply_status}],
        },
    }


def test_family_ignores_zone_id_session_regime_and_momentum_churn() -> None:
    first = state(zone_id="demand-one", session="london", regime="compression", m12=0.08, m48=0.14)
    second = state(zone_id="demand-two", session="new_york", regime="trend_up", m12=0.01, m48=0.20)
    assert family_signature(first) == family_signature(second)
    first_descriptor = setup_family_descriptor(first)
    second_descriptor = setup_family_descriptor(second)
    assert first_descriptor["session"] != second_descriptor["session"]
    assert first_descriptor["regime_group"] != second_descriptor["regime_group"]


def test_family_changes_when_structural_setup_changes() -> None:
    pullback = state(order_type="buy_limit")
    breakout = state(order_type="buy_stop")
    opposing_location = state(demand_distance=4.0, supply_distance=0.6, demand_status="ACTIVE", supply_status="NEAR")
    assert family_signature(pullback) != family_signature(breakout)
    assert family_signature(pullback) != family_signature(opposing_location)


def test_episode_is_stable_within_day_session_but_changes_across_real_episodes() -> None:
    first = state(zone_id="zone-a", session="london", as_of="2026-08-21T09:15:00+00:00")
    relabelled = state(zone_id="zone-b", session="london", as_of="2026-08-21T11:15:00+00:00")
    new_york = state(zone_id="zone-a", session="new_york", as_of="2026-08-21T14:15:00+00:00")
    tomorrow = state(zone_id="zone-a", session="london", as_of="2026-08-22T09:15:00+00:00")
    assert episode_key(first) == episode_key(relabelled)
    assert episode_key(first) != episode_key(new_york)
    assert episode_key(first) != episode_key(tomorrow)


def _row(index: int, success: bool, descriptor: dict, *, day_offset: int = 0) -> dict:
    return {
        "episode_key": f"episode-{index}",
        "observed_at": f"2026-08-{21 + day_offset:02d}T10:00:00+00:00",
        "learning_success": success,
        "market_state": {"setup_family_descriptor": descriptor},
    }


def test_weighted_calibration_requires_depth_days_and_effective_evidence() -> None:
    current = setup_family_descriptor(state())
    early = [_row(i, i < 7, current, day_offset=i % 2) for i in range(11)]
    result = weighted_calibration_from_rows(early, current)
    assert result["samples"] == 11
    assert result["active"] is False
    assert result["confidence_adjustment"] == 0

    mature = [_row(i, i < 9, current, day_offset=i % 3) for i in range(12)]
    result = weighted_calibration_from_rows(mature, current)
    assert result["samples"] == 12
    assert result["independent_days"] == 3
    assert result["effective_samples"] == 12.0
    assert result["active"] is True
    assert 0 < result["confidence_adjustment"] <= 6
    assert result["learning_version"] == LEARNING_VERSION


def test_context_weighting_prefers_same_session_regime_and_momentum() -> None:
    current = setup_family_descriptor(state(session="london", regime="compression", m12=0.08, m48=0.14))
    different = setup_family_descriptor(state(session="new_york", regime="trend_down", m12=-0.10, m48=-0.12))
    rows = []
    # Six same-context wins, six different-context losses across three days.
    for index in range(6):
        rows.append(_row(index, True, current, day_offset=index % 3))
    for index in range(6, 12):
        rows.append(_row(index, False, different, day_offset=index % 3))
    result = weighted_calibration_from_rows(rows, current)
    assert result["raw_accuracy"] == 0.5
    assert result["accuracy"] > result["raw_accuracy"]
    assert result["effective_samples"] < 12.0
    assert result["independent_days"] == 3
    assert result["confidence_adjustment"] > 0
    assert result["confidence_adjustment"] <= 6
