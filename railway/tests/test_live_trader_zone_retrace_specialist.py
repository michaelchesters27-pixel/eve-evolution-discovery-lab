from __future__ import annotations

from types import SimpleNamespace

from app.services import live_trader as core
from app.services import live_trader_historical_learning_v29 as academy
from app.services import live_trader_london_session_gate_v46 as session_gate
from app.services import live_trader_trade_lock_v28 as lock
from app.services import live_trader_zone_retrace_specialist_v58 as v58


def trader() -> core.LiveTrader:
    settings = SimpleNamespace(
        live_trader_symbol="XAU/USD",
        live_trader_enabled=True,
        twelve_data_api_key="test-key",
        twelve_data_ws_url="wss://example.invalid",
        live_trader_learning_horizon_minutes=60,
    )
    engine = core.LiveTrader(settings, SimpleNamespace())
    engine._live_campaign_loaded_v28 = True
    engine._live_campaign = None
    engine._feed_is_fresh = lambda max_age_seconds=30.0: True
    # These tests model the settled production runtime. The real execution ledger
    # has completed the v2 historical regrade, so a synthetic production engine
    # must explicitly satisfy that prerequisite rather than bypassing the gate.
    engine._execution_regrade_ready_v39 = True
    # The production chain is deliberately fail-closed when the calendar has not
    # been loaded. These deterministic execution tests provide an explicit clear,
    # confirmed synthetic calendar rather than weakening the real news guard.
    engine._news_status_v35 = {
        "available": True,
        "new_trade_blocked": False,
        "week_confirmed": True,
        "active": False,
        "active_events": [],
    }
    return engine


def structural_bias(direction: str) -> dict:
    return {
        "overall": direction,
        "confidence": 78,
        "panel_bias_version": "eve-live-bias-v2.5-structural-panel",
        "data_quality": {"critical_stale": [], "trade_bias_blocked": False},
        "timeframes": {
            "D1": {"direction": direction, "method": "test"},
            "H4": {"direction": direction, "method": "test"},
            "H1": {"direction": direction, "method": "test"},
            "M30": {"direction": direction, "method": "test"},
            "M15": {"direction": direction, "method": "test"},
            "M5": {"direction": direction, "method": "test"},
        },
    }


def zones(direction: str) -> dict:
    if direction == "bullish":
        return {
            "demand": [{"id": "d1", "kind": "demand", "low": 99.0, "high": 101.0, "quality": 82, "quality_label": "HIGH", "distance_atr": 0.0, "fresh": True, "retests": 0}],
            "supply": [{"id": "s1", "kind": "supply", "low": 110.0, "high": 112.0, "quality": 80, "quality_label": "HIGH", "distance_atr": 5.0, "fresh": True, "retests": 0}],
        }
    return {
        "demand": [{"id": "d1", "kind": "demand", "low": 88.0, "high": 90.0, "quality": 80, "quality_label": "HIGH", "distance_atr": 5.0, "fresh": True, "retests": 0}],
        "supply": [{"id": "s1", "kind": "supply", "low": 99.0, "high": 101.0, "quality": 82, "quality_label": "HIGH", "distance_atr": 0.0, "fresh": True, "retests": 0}],
    }


def open_session(monkeypatch) -> None:
    monkeypatch.setattr(academy, "broker_market_open", lambda at: True)
    monkeypatch.setattr(
        session_gate,
        "_session_status",
        lambda now=None: {
            "version": session_gate.SESSION_GATE_VERSION,
            "timezone": "Europe/London",
            "local_time": "2026-08-26T10:00:00+01:00",
            "session_date": "2026-08-26",
            "weekday": "Wednesday",
            "start": "08:20",
            "end": "17:00",
            "end_exclusive": True,
            "open": True,
            "reason": "inside London trade-idea window",
        },
    )


def test_specialist_blocks_blind_limit_before_zone_confirmation() -> None:
    engine = trader()
    setup, trade = v58._candidate_v58(
        engine,
        102.0,
        2.0,
        structural_bias("bullish"),
        {
            "demand": [{"id": "d1", "kind": "demand", "low": 99.0, "high": 101.0, "quality": 82, "quality_label": "HIGH", "distance_atr": 0.5}],
            "supply": [],
        },
        {"recent_high": 105.0, "recent_low": 97.0},
    )
    assert setup["status"] == "ZONE RETRACE WAIT"
    assert trade["action"] == "WAIT"
    assert trade["order_type"] == "none"
    assert trade["strategy_key"] == v58.STRATEGY_KEY


def test_production_chain_can_publish_bullish_retracement_market_campaign(monkeypatch) -> None:
    open_session(monkeypatch)
    engine = trader()
    setup, trade = core.LiveTrader._trade_idea(
        engine,
        100.0,
        2.0,
        structural_bias("bullish"),
        zones("bullish"),
        {"recent_high": 106.0, "recent_low": 96.0},
    )
    assert setup["status"] in {"IDEA LOCKED", "TRADE ACTIVE"}
    assert trade["order_type"] == "market"
    assert trade["side"] == "BUY"
    assert trade["campaign_status"] == "active"
    assert engine._live_campaign["strategy_key"] == v58.STRATEGY_KEY
    assert engine._live_campaign["execution_class"] == "zone_retrace_confirmation"
    assert engine._live_campaign["source_zone"]["kind"] == "demand"


def test_production_chain_can_publish_bearish_retracement_market_campaign(monkeypatch) -> None:
    open_session(monkeypatch)
    engine = trader()
    setup, trade = core.LiveTrader._trade_idea(
        engine,
        100.0,
        2.0,
        structural_bias("bearish"),
        zones("bearish"),
        {"recent_high": 104.0, "recent_low": 94.0},
    )
    assert setup["status"] in {"IDEA LOCKED", "TRADE ACTIVE"}
    assert trade["order_type"] == "market"
    assert trade["side"] == "SELL"
    assert trade["campaign_status"] == "active"
    assert engine._live_campaign["strategy_key"] == v58.STRATEGY_KEY
    assert engine._live_campaign["execution_class"] == "zone_retrace_confirmation"
    assert engine._live_campaign["source_zone"]["kind"] == "supply"


def test_campaign_metadata_wrapper_preserves_specialist_identity() -> None:
    engine = trader()
    engine._zone_target_context_v49 = {"zones": zones("bullish"), "atr": 2.0}
    trade = {
        "action": "BUY NOW",
        "side": "BUY",
        "order_type": "market",
        "entry": 100.0,
        "stop": 98.4,
        "target": 102.4,
        "risk_reward": 1.5,
        "confidence": 80,
        "reason": "test",
        "invalidation": "The trade thesis is invalid beyond the stop at 98.40.",
        "manual_only": True,
        "automatic_order_placement": False,
        "strategy_key": v58.STRATEGY_KEY,
        "specialist_version": v58.SPECIALIST_VERSION,
        "execution_class": "zone_retrace_confirmation",
        "entry_policy": "market_after_zone_confirmation",
        "source_zone": {"id": "d1", "kind": "demand", "low": 99.0, "high": 101.0, "quality": 82},
    }
    campaign = lock._new_campaign(engine, trade, 100.0)
    assert campaign["strategy_key"] == v58.STRATEGY_KEY
    assert campaign["specialist_version"] == v58.SPECIALIST_VERSION
    assert campaign["execution_class"] == "zone_retrace_confirmation"
    assert campaign["published_trade"]["strategy_key"] == v58.STRATEGY_KEY
