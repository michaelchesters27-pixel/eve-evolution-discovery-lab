from __future__ import annotations

from datetime import datetime, timedelta, timezone

import app.services.live_trader_market_events_v23 as events
from app.services import live_trader_learning_v2 as v2
from app.services import live_trader_learning_v22 as v22


def row(
    minute: int,
    *,
    open_: float = 100.2,
    high: float = 100.7,
    low: float = 99.8,
    close: float = 100.2,
    atr: float = 2.0,
    session: str = "london",
) -> dict:
    stamp = datetime(2026, 8, 21, 8, 0, tzinfo=timezone.utc) + timedelta(minutes=5 * minute)
    return {
        "candle_time": stamp.isoformat(),
        "open": open_,
        "high": high,
        "low": low,
        "close": close,
        "atr_14": atr,
        "session": session,
        "regime": "range",
        "mtf_context": {},
    }


def fake_trader(rows: list[dict], current: float):
    trader = v2.LiveTrader.__new__(v2.LiveTrader)
    trader._rows = rows
    trader._ticks = [(datetime.now(timezone.utc), current)]
    trader.connected = True
    trader.last_tick_at = datetime.now(timezone.utc).isoformat()
    return trader


def test_sell_side_sweep_and_reclaim_is_explicit_market_event():
    rows = [row(i, low=100.4, high=102.0, close=101.2) for i in range(9)]
    rows[-2] = row(8, low=100.3, high=101.3, close=100.6)
    rows[-1] = row(9, open_=100.5, low=99.45, high=101.0, close=100.45)
    trader = fake_trader(rows, 100.45)

    detected = events.classify_market_events(
        trader,
        rows,
        {"previous_day_low": 100.0, "previous_day_high": 106.0},
    )

    primary = detected[0]
    assert primary["event_class"] == "sell_side_sweep_reclaim"
    assert primary["implication"] == "bullish"
    assert primary["confirmation"] == "possible_fakeout"
    assert primary["level_label"] == "Previous day low"


def test_failed_breakout_above_is_confirmed_fakeout():
    rows = [row(i, low=98.0, high=99.7, close=99.5) for i in range(9)]
    rows[-2] = row(8, low=99.8, high=100.6, close=100.3)
    rows[-1] = row(9, open_=100.2, low=99.5, high=100.55, close=99.75)
    trader = fake_trader(rows, 99.75)

    detected = events.classify_market_events(
        trader,
        rows,
        {"previous_day_high": 100.0, "previous_day_low": 94.0},
    )

    primary = detected[0]
    assert primary["event_class"] == "failed_breakout_up"
    assert primary["implication"] == "bearish"
    assert primary["confirmation"] == "confirmed"


def test_breakout_that_holds_is_not_labelled_fakeout():
    rows = [row(i, low=98.0, high=99.8, close=99.6) for i in range(9)]
    rows[-2] = row(8, low=99.9, high=100.5, close=100.2)
    rows[-1] = row(9, open_=100.2, low=100.0, high=100.8, close=100.4)
    trader = fake_trader(rows, 100.4)

    detected = events.classify_market_events(
        trader,
        rows,
        {"previous_day_high": 100.0, "previous_day_low": 94.0},
    )

    primary = detected[0]
    assert primary["event_class"] == "accepted_breakout_up"
    assert primary["implication"] == "bullish"
    assert primary["confirmation"] == "accepted"


def test_event_is_part_of_transferable_learning_family():
    base_state = {
        "bias": {
            "overall": "bullish",
            "timeframes": {
                "D1": {"direction": "bullish"},
                "H4": {"direction": "bullish"},
                "H1": {"direction": "bullish"},
                "M15": {"direction": "bullish"},
                "M5": {"direction": "bullish"},
            },
        },
        "market": {"session": "london", "regime": "range", "return_12_pct": 0.1, "return_48_pct": 0.2},
        "trade": {"order_type": "buy_stop"},
        "zones": {
            "demand": [{"distance_atr": 0.5, "quality": 80}],
            "supply": [{"distance_atr": 4.0, "quality": 70}],
        },
        "liquidity": {
            "primary_event": {
                "event_class": "sell_side_sweep_reclaim",
                "implication": "bullish",
                "confirmation": "possible_fakeout",
            }
        },
    }
    no_event = {
        **base_state,
        "liquidity": {"primary_event": {"event_class": "none", "implication": "neutral", "confirmation": "none"}},
    }

    descriptor = events.setup_family_descriptor(base_state)
    assert descriptor["market_event_class"] == "sweep_reclaim"
    assert descriptor["market_event_relation"] == "aligned"
    assert "market_event_class" in v22._FAMILY_KEYS
    assert "market_event_relation" in v22._FAMILY_KEYS
    assert v22.family_signature(base_state) != v22.family_signature(no_event)
    assert v2.LEARNING_VERSION == events.LEARNING_VERSION


def test_opposing_fakeout_blocks_existing_trade(monkeypatch):
    monkeypatch.setattr(
        events,
        "_original_trade_idea",
        lambda *args, **kwargs: (
            {"status": "TRADE IDEA", "reason": "base"},
            {
                "action": "BUY NOW",
                "order_type": "market",
                "entry": 101.0,
                "stop": 99.0,
                "target": 105.0,
                "confidence": 70,
                "manual_only": True,
            },
        ),
    )
    trader = fake_trader([row(i) for i in range(10)], 101.0)
    bias = {
        "overall": "bullish",
        "confidence": 70,
        "timeframes": {"M5": {"direction": "bullish"}, "M15": {"direction": "bullish"}},
    }
    liquidity = {
        "primary_event": {
            "event_class": "buy_side_sweep_reclaim",
            "label": "BUY-SIDE SWEEP → RECLAIM",
            "level_label": "London high",
            "implication": "bearish",
            "strength": 84,
        }
    }

    setup, trade = events._trade_idea_v23(trader, 101.0, 2.0, bias, {"demand": [], "supply": []}, liquidity)

    assert setup["status"] == "WATCHING"
    assert trade["action"] == "WAIT"
    assert trade["order_type"] == "none"
    assert bias["confidence"] == 65


def test_aligned_sell_side_sweep_can_arm_buy_stop(monkeypatch):
    monkeypatch.setattr(
        events,
        "_original_trade_idea",
        lambda *args, **kwargs: (
            {"status": "WATCHING", "reason": "base"},
            {"action": "WAIT", "order_type": "none", "reason": "base", "manual_only": True},
        ),
    )
    rows = [row(i, low=99.5, high=101.0, close=100.5) for i in range(10)]
    rows[-1] = row(9, open_=100.2, low=99.4, high=101.2, close=101.0)
    trader = fake_trader(rows, 101.0)
    trader._feed_is_fresh = lambda: True

    bias = {
        "overall": "bullish",
        "confidence": 68,
        "timeframes": {"M5": {"direction": "bullish"}, "M15": {"direction": "bullish"}},
    }
    zones = {
        "demand": [{"low": 99.0, "high": 100.0, "distance_atr": 0.5, "quality": 85}],
        "supply": [{"low": 106.0, "high": 107.0, "distance_atr": 2.5, "quality": 75}],
    }
    liquidity = {
        "previous_day_high": 106.0,
        "primary_event": {
            "event_class": "sell_side_sweep_reclaim",
            "label": "SELL-SIDE SWEEP → RECLAIM",
            "level_label": "London low",
            "side": "sell_side",
            "implication": "bullish",
            "strength": 86,
            "extreme": 99.4,
            "explanation": "Price swept below London low and reclaimed.",
        },
    }

    setup, trade = events._trade_idea_v23(trader, 101.0, 2.0, bias, zones, liquidity)

    assert setup["status"] == "ARMED"
    assert trade["action"] == "BUY STOP"
    assert trade["order_type"] == "buy_stop"
    assert trade["entry"] > 101.2
    assert trade["stop"] < 99.4
    assert trade["target"] == 106.0
    assert trade["risk_reward"] >= 1.6
    assert trade["market_event"] == "sell_side_sweep_reclaim"


def test_event_sentence_uses_plain_trading_language():
    state = {
        "liquidity": {
            "primary_event": {
                "event_class": "failed_breakout_down",
                "level_label": "Previous day low",
                "level": 4500.0,
            }
        }
    }
    sentence = events._event_sentence(state)
    assert "Micky" in sentence
    assert "failed breakdown" in sentence.lower()
    assert "bullish fake-out" in sentence.lower()
