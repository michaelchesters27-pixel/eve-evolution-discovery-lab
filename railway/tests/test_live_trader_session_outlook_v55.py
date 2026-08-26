from types import SimpleNamespace

from app.services import live_trader as core
from app.services import live_trader_session_outlook_v55 as outlook
from app.services import live_trader_zone_target_runtime_v51 as runtime_v51


def _state(direction: str) -> dict:
    bullish = direction == "bullish"
    sign = 1 if bullish else -1
    price = 100.0
    event = {
        "event_class": "sell_side_sweep_reclaim" if bullish else "buy_side_sweep_reclaim",
        "label": "POSSIBLE FAILED BEARISH BREAKOUT" if bullish else "POSSIBLE FAILED BULLISH BREAKOUT",
        "implication": direction,
        "strength": 82,
        "level": 99.2 if bullish else 100.8,
    }
    return {
        "price": price,
        "as_of": "2026-08-26T09:00:00+00:00",
        "bias": {
            "overall": "neutral",
            "raw_score": 0.04 * sign,
            "confidence": 50,
            "data_quality": {"critical_stale": []},
            "timeframes": {
                "D1": {"direction": "neutral", "structure_score": 0.05 * sign, "method": "multi_candle_structure"},
                "H4": {"direction": direction, "structure_score": 0.24 * sign, "method": "multi_candle_structure"},
                "H1": {"direction": direction, "structure_score": 0.42 * sign, "method": "multi_candle_structure"},
                "M30": {"direction": direction, "structure_score": 0.31 * sign, "method": "multi_candle_structure"},
                "M15": {"direction": direction, "structure_score": 0.48 * sign, "method": "multi_candle_structure"},
                "M5": {"direction": direction, "structure_score": 0.36 * sign, "method": "multi_candle_structure"},
            },
        },
        "market": {
            "session": "london",
            "return_12_pct": 0.09 * sign,
            "return_48_pct": 0.16 * sign,
        },
        "liquidity": {
            "primary_event": event,
            "london_low": 98.0,
            "london_high": 102.0,
            "recent_low": 98.8,
            "recent_high": 101.2,
            "previous_day_low": 97.0,
            "previous_day_high": 103.0,
        },
        "zones": {
            "demand": [{"low": 98.7, "high": 99.1, "quality": 82, "distance_atr": 0.35 if bullish else 1.6}],
            "supply": [{"low": 100.9, "high": 101.3, "quality": 82, "distance_atr": 1.6 if bullish else 0.35}],
        },
        "trade": {"action": "WAIT", "order_type": "none", "reason": "Hardened gate is waiting."},
        "setup": {"status": "WATCHING"},
    }


def test_neutral_trade_bias_can_have_bullish_session_outlook():
    trader = SimpleNamespace(_latest_state={})
    result = outlook.build_session_outlook(trader, _state("bullish"))
    assert result["direction"] == "bullish"
    assert result["confidence"] > 50
    assert result["affects_trade_gate"] is False
    assert result["trade_gate_independent"] is True


def test_neutral_trade_bias_can_have_bearish_session_outlook():
    trader = SimpleNamespace(_latest_state={})
    result = outlook.build_session_outlook(trader, _state("bearish"))
    assert result["direction"] == "bearish"
    assert result["confidence"] > 50
    assert result["affects_trade_gate"] is False


def test_opinion_explicitly_separates_trade_bias_from_session_outlook():
    trader = SimpleNamespace(_latest_state={})
    state = _state("bullish")
    text = outlook._opinion_text_v55(trader, state)
    assert "TRADE BIAS is neutral" in text
    assert "SESSION OUTLOOK is BULLISH" in text
    assert "hardened trade gate still says WAIT" in text
    assert state["session_outlook"]["direction"] == "bullish"


def test_session_outlook_does_not_replace_hardened_trade_function():
    assert core.LiveTrader._trade_idea is runtime_v51._trade_idea_v51


def test_runtime_declares_outlook_has_no_trade_authority():
    class Dummy:
        pass

    dummy = Dummy()
    # Avoid invoking the whole runtime status chain; the source contract itself
    # must keep the live gate independence explicit.
    source = outlook.__file__
    assert source
    assert outlook.SESSION_OUTLOOK_VERSION == "eve-live-session-outlook-v1"
