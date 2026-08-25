from __future__ import annotations

from app.services import live_trader_breakout_language_boundary_v54 as v54


def test_sell_side_sweep_uses_failed_bearish_breakout_without_changing_internal_confirmation() -> None:
    event = v54._clean_event(
        {
            "event_class": "sell_side_sweep_reclaim",
            "level_label": "M15 completed range low",
            "confirmation": "possible_fakeout",
            "implication": "bullish",
            "strength": 80,
        }
    )
    assert event["label"] == "POSSIBLE FAILED BEARISH BREAKOUT"
    assert "failed bearish breakout" in event["explanation"].lower()
    assert "fakeout" not in event["label"].lower()
    assert "fake-out" not in event["explanation"].lower()
    assert event["display_confirmation"] == "possible"
    assert event["confirmation"] == "possible_fakeout"
    assert event["implication"] == "bullish"
    assert event["strength"] == 80


def test_buy_side_sweep_uses_failed_bullish_breakout() -> None:
    event = v54._clean_event(
        {
            "event_class": "buy_side_sweep_reclaim",
            "level_label": "London high",
            "confirmation": "possible_fakeout",
            "implication": "bearish",
        }
    )
    assert event["label"] == "POSSIBLE FAILED BULLISH BREAKOUT"
    assert "failed bullish breakout" in event["explanation"].lower()
    assert event["confirmation"] == "possible_fakeout"


def test_accepted_breakouts_use_holding_language_only() -> None:
    up = v54._clean_event({"event_class": "accepted_breakout_up", "level_label": "London high"})
    down = v54._clean_event({"event_class": "accepted_breakout_down", "level_label": "London low"})
    for event in (up, down):
        combined = f"{event['label']} {event['explanation']}".lower()
        assert "fakeout" not in combined
        assert "fake-out" not in combined
        assert event["display_confirmation"] == "holding"
