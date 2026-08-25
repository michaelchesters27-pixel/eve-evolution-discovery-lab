from __future__ import annotations

from app.services import live_trader_breakout_wording_v53 as v53


def _state(event_class: str, level: float = 4640.0) -> dict:
    return {
        "liquidity": {
            "primary_event": {
                "event_class": event_class,
                "level_label": "M15 completed range high" if "up" in event_class or "buy_side" in event_class else "M15 completed range low",
                "level": level,
            }
        }
    }


def test_buy_side_sweep_is_called_possible_failed_bullish_breakout() -> None:
    text = v53._event_sentence_v53(_state("buy_side_sweep_reclaim"))
    assert "possible failed bullish breakout" in text.lower()
    assert "bearish warning" in text.lower()
    assert "fake-out" not in text.lower()
    assert "fakeout" not in text.lower()


def test_sell_side_sweep_is_called_possible_failed_bearish_breakout() -> None:
    text = v53._event_sentence_v53(_state("sell_side_sweep_reclaim"))
    assert "possible failed bearish breakout" in text.lower()
    assert "bullish warning" in text.lower()
    assert "fake-out" not in text.lower()
    assert "fakeout" not in text.lower()


def test_confirmed_upside_failure_is_confirmed_failed_bullish_breakout() -> None:
    text = v53._event_sentence_v53(_state("failed_breakout_up"))
    assert "confirmed failed bullish breakout" in text.lower()
    assert "currently bearish" in text.lower()


def test_confirmed_downside_failure_is_confirmed_failed_bearish_breakout() -> None:
    text = v53._event_sentence_v53(_state("failed_breakout_down"))
    assert "confirmed failed bearish breakout" in text.lower()
    assert "currently bullish" in text.lower()


def test_clear_labels_do_not_change_event_semantics() -> None:
    event = {
        "event_class": "buy_side_sweep_reclaim",
        "implication": "bearish",
        "confirmation": "possible_fakeout",
        "strength": 79,
    }
    assert v53._clear_label(event) == "POSSIBLE FAILED BULLISH BREAKOUT"
    assert event["event_class"] == "buy_side_sweep_reclaim"
    assert event["implication"] == "bearish"
    assert event["confirmation"] == "possible_fakeout"
    assert event["strength"] == 79
