from __future__ import annotations

from datetime import datetime, timedelta, timezone

from app.services import live_trader as core
from app.services import live_trader_clear_bias_gate_v45 as v45
from app.services import live_trader_zone_target_guard_v49 as v49


def test_target_cap_reduces_large_buy_target_to_one_point_five_r() -> None:
    trade = {
        "side": "BUY",
        "order_type": "buy_limit",
        "entry": 100.0,
        "stop": 98.0,
        "target": 112.0,
        "risk_reward": 6.0,
    }

    result = v49._apply_target_cap(trade)

    assert result["target"] == 103.0
    assert result["risk_reward"] == 1.5
    assert result["structural_target"] == 112.0
    assert result["target_policy"]["applied"] is True
    assert result["target_policy"]["cap_r"] == 1.5


def test_target_cap_reduces_large_sell_target_to_one_point_five_r() -> None:
    trade = {
        "side": "SELL",
        "order_type": "sell_limit",
        "entry": 100.0,
        "stop": 102.0,
        "target": 88.0,
        "risk_reward": 6.0,
    }

    result = v49._apply_target_cap(trade)

    assert result["target"] == 97.0
    assert result["risk_reward"] == 1.5
    assert result["structural_target"] == 88.0
    assert result["target_policy"]["applied"] is True


def test_target_at_or_below_cap_is_not_moved() -> None:
    trade = {
        "side": "BUY",
        "order_type": "buy_limit",
        "entry": 100.0,
        "stop": 98.0,
        "target": 102.5,
        "risk_reward": 1.25,
    }

    result = v49._apply_target_cap(trade)

    assert result["target"] == 102.5
    assert result["risk_reward"] == 1.25
    assert "structural_target" not in result
    assert result["target_policy"]["applied"] is False


def test_source_zone_binding_persists_exact_current_zone_identity() -> None:
    campaign = {
        "side": "BUY",
        "order_type": "buy_limit",
        "entry": 104.0,
    }
    zones = {
        "demand": [
            {
                "id": "demand-current",
                "kind": "demand",
                "low": 102.0,
                "high": 104.0,
                "quality": 91,
                "origin_time": "2026-08-25T10:30:00+00:00",
            }
        ],
        "supply": [],
    }

    v49._bind_source_zone(campaign, zones, 4.0)

    assert campaign["source_zone_required"] is True
    assert campaign["source_zone"]["id"] == "demand-current"
    assert campaign["source_zone"]["low"] == 102.0
    assert campaign["source_zone"]["high"] == 104.0


def test_pending_limit_is_cancelled_if_source_zone_is_replaced() -> None:
    trader = core.LiveTrader.__new__(core.LiveTrader)
    trader._live_campaign_dirty = False
    campaign = {
        "id": "campaign-1",
        "status": "pending",
        "side": "BUY",
        "order_type": "buy_limit",
        "entry": 104.0,
        "stop": 100.0,
        "target": 110.0,
        "source_zone": {
            "id": "old-demand",
            "kind": "demand",
            "low": 102.0,
            "high": 104.0,
        },
        "created_at": core.utc_now().isoformat(),
    }
    trader._live_campaign = campaign
    zones = {
        "demand": [
            {
                "id": "new-demand",
                "kind": "demand",
                "low": 98.0,
                "high": 100.0,
                "quality": 94,
            }
        ],
        "supply": [],
    }

    setup, trade = v49._revalidate_pending(
        trader,
        campaign,
        106.0,
        4.0,
        {},
        zones,
        {},
    )

    assert setup["status"] == "IDEA CANCELLED"
    assert trade["action"] == "CANCEL — CONTEXT CHANGED"
    assert trader._live_campaign["status"] == "invalidated"
    assert trader._live_campaign["pending_revalidation"]["reason"] == "source_zone_replaced"


def test_pending_idea_ages_out_after_ninety_minutes(monkeypatch) -> None:
    fixed_now = datetime(2026, 8, 25, 14, 0, tzinfo=timezone.utc)
    monkeypatch.setattr(v49.core, "utc_now", lambda: fixed_now)
    trader = core.LiveTrader.__new__(core.LiveTrader)
    trader._live_campaign_dirty = False
    campaign = {
        "id": "campaign-aged",
        "status": "pending",
        "side": "BUY",
        "order_type": "buy_stop",
        "entry": 105.0,
        "stop": 100.0,
        "target": 112.5,
        "created_at": (fixed_now - timedelta(minutes=91)).isoformat(),
    }
    trader._live_campaign = campaign

    setup, trade = v49._revalidate_pending(trader, campaign, 103.0, 4.0, {}, {}, {})

    assert setup["status"] == "IDEA CANCELLED"
    assert trade["action"] == "CANCEL — CONTEXT CHANGED"
    assert trader._live_campaign["pending_revalidation"]["reason"] == "pending_age_limit"


def test_target_alternative_replay_scores_full_m1_bars_stop_first() -> None:
    campaign = {
        "side": "BUY",
        "entry": 100.0,
        "stop": 99.0,
        "triggered_at": "2026-08-25T12:00:30+00:00",
        "completed_at": "2026-08-25T12:04:20+00:00",
    }
    bars = [
        {"candle_time": "2026-08-25T12:00:00+00:00", "low": 99.8, "high": 100.8},
        {"candle_time": "2026-08-25T12:01:00+00:00", "low": 99.7, "high": 101.1},
        {"candle_time": "2026-08-25T12:02:00+00:00", "low": 99.6, "high": 101.6},
        {"candle_time": "2026-08-25T12:03:00+00:00", "low": 99.4, "high": 101.9},
        {"candle_time": "2026-08-25T12:04:00+00:00", "low": 98.9, "high": 102.1},
    ]

    replay = v49._fixed_target_replays(campaign, bars)

    assert replay["available"] is True
    assert replay["results"]["1R"]["trade_outcome"] == "target"
    assert replay["results"]["1.5R"]["trade_outcome"] == "target"
    assert replay["results"]["2R"]["trade_outcome"] == "stop"


def test_v49_does_not_weaken_hardened_clear_bias_gate() -> None:
    assert v45.MIN_CLEAR_CONFIDENCE == 65
    assert v49.MAX_TARGET_R == 1.5
    assert v49.MAX_PENDING_AGE_MINUTES == 90
