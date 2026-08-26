from __future__ import annotations

import json
from types import SimpleNamespace

from app.services.live_trader import LiveTrader


def trader() -> LiveTrader:
    settings = SimpleNamespace(
        live_trader_symbol="XAU/USD",
        live_trader_enabled=True,
        twelve_data_api_key="server-side-secret-key",
        twelve_data_ws_url="wss://ws.twelvedata.com/v1/quotes/price",
        live_trader_learning_horizon_minutes=60,
    )
    return LiveTrader(settings, SimpleNamespace())


def bullish_bias() -> dict:
    return {
        "overall": "bullish",
        "confidence": 74,
        "timeframes": {
            "D1": {"direction": "bullish"},
            "H4": {"direction": "bullish"},
            "H1": {"direction": "bullish"},
            "M30": {"direction": "bullish"},
            "M15": {"direction": "bullish"},
            "M5": {"direction": "bullish"},
            "M1": {"direction": "bearish"},
        },
    }


def test_bias_weights_higher_timeframes_more_than_m1_noise() -> None:
    engine = trader()
    latest = {
        "mtf_context": {
            "D1": {"direction": 1, "return_pct": 2.0},
            "H4": {"direction": 1, "return_pct": 0.8},
            "H1": {"direction": 1, "return_pct": 0.2},
            "M30": {"direction": -1, "return_pct": -0.1},
            "M15": {"direction": -1, "return_pct": -0.05},
            "M5": {"direction": -1, "return_pct": -0.02},
            "M1": {"direction": -1},
        }
    }
    bias, score = engine._bias(latest)
    assert score > 0
    assert bias["overall"] == "bullish"
    assert bias["timeframes"]["D1"]["direction"] == "bullish"


def test_market_buy_requires_zone_and_short_term_confirmation() -> None:
    engine = trader()
    zones = {
        "demand": [{"low": 98.0, "high": 100.5, "quality": 82, "quality_label": "HIGH", "distance_atr": 0.0}],
        "supply": [{"low": 108.0, "high": 110.0, "quality": 75, "quality_label": "HIGH", "distance_atr": 4.0}],
    }
    setup, trade = engine._trade_idea(
        100.0,
        2.0,
        bullish_bias(),
        zones,
        {"recent_high": 102.0, "recent_low": 96.0},
    )
    assert setup["status"] == "ZONE RETRACE CONFIRMED"
    assert trade["action"] == "BUY NOW"
    assert trade["order_type"] == "market"
    assert trade["entry"] == 100.0
    assert trade["stop"] < trade["entry"] < trade["target"]
    assert trade["risk_reward"] >= 1.35
    assert trade["strategy_key"] == "zone_retrace_v1"
    assert trade["execution_class"] == "zone_retrace_confirmation"
    assert trade["manual_only"] is True
    assert trade["automatic_order_placement"] is False


def test_nearby_demand_waits_for_confirmation_instead_of_blind_limit() -> None:
    engine = trader()
    zones = {
        "demand": [{"low": 98.0, "high": 100.0, "quality": 80, "quality_label": "HIGH", "distance_atr": 0.75}],
        "supply": [{"low": 108.0, "high": 110.0, "quality": 72, "quality_label": "HIGH", "distance_atr": 3.25}],
    }
    setup, trade = engine._trade_idea(
        101.5,
        2.0,
        bullish_bias(),
        zones,
        {"recent_high": 104.0, "recent_low": 97.0},
    )
    assert setup["status"] == "ZONE RETRACE WAIT"
    assert trade["action"] == "WAIT"
    assert trade["order_type"] == "none"
    assert trade["strategy_key"] == "zone_retrace_v1"


def test_target_opinion_speaks_to_micky_without_claiming_certainty() -> None:
    engine = trader()
    state = {"price": 100.0, "bias": {"overall": "bullish"}, "zones": {"supply": [], "demand": []}}
    answer = engine._target_sentence("Do you think price gets to 110?", state)
    assert answer is not None
    assert answer.startswith("Micky,")
    assert "110.00" in answer
    assert "guaranteed" in answer


def test_runtime_never_exposes_twelve_data_api_key() -> None:
    engine = trader()
    payload = json.dumps(engine.runtime_status())
    assert "server-side-secret-key" not in payload
    assert '"api_key_configured": true' in payload
    assert '"automatic_order_placement": false' in payload
