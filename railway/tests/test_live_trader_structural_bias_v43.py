from __future__ import annotations

from datetime import datetime, timedelta, timezone

from app.services import live_trader_learning_v2 as v2
from app.services import live_trader_structural_bias_v43 as v43


def candle(start: datetime, *, open_: float, high: float, low: float, close: float, minutes: int) -> dict:
    direction = 1 if close > open_ else -1 if close < open_ else 0
    range_price = high - low
    return {
        "candle_time": start.isoformat(),
        "completed_at": (start + timedelta(minutes=minutes)).isoformat(),
        "open": open_,
        "high": high,
        "low": low,
        "close": close,
        "range_price": range_price,
        "body_abs": abs(close - open_),
        "body_price": close - open_,
        "close_location": (close - low) / range_price if range_price else 0.5,
        "return_pct": ((close / open_) - 1.0) * 100.0 if open_ else 0.0,
        "direction": direction,
    }


def base_row(start: datetime, context: dict) -> dict:
    return {
        "candle_time": start.isoformat(),
        "open": 100.0,
        "high": 101.0,
        "low": 99.0,
        "close": 100.5,
        "atr_14": 2.0,
        "regime": "range",
        "trend_12_atr": 0.0,
        "trend_48_atr": 0.0,
        "return_12_pct": 0.0,
        "return_48_pct": 0.0,
        "mtf_context": context,
    }


def test_panel_uses_multi_candle_structure_not_last_candle_colour() -> None:
    trader = v2.LiveTrader.__new__(v2.LiveTrader)
    starts = [datetime(2026, 8, 23, hour, tzinfo=timezone.utc) for hour in (1, 5, 9, 13)]
    h4_bars = [
        candle(starts[0], open_=100, high=105, low=98, close=104, minutes=240),
        candle(starts[1], open_=104, high=108, low=102, close=107, minutes=240),
        candle(starts[2], open_=107, high=111, low=105, close=110, minutes=240),
        # Last candle is red, but it still makes a higher high and higher low.
        candle(starts[3], open_=113, high=114, low=108, close=111, minutes=240),
    ]
    rows = []
    for index, h4 in enumerate(h4_bars):
        m5_start = starts[index] + timedelta(hours=4)
        rows.append(base_row(m5_start, {"H4": h4, "M1": {"available": True, "direction": -1}}))
    trader._rows = rows

    latest = rows[-1]
    bias, _ = v43._bias_v43(trader, latest)

    assert bias["timeframes"]["H4"]["legacy_direction"] == "bearish"
    assert bias["timeframes"]["H4"]["direction"] == "bullish"
    assert bias["timeframes"]["H4"]["method"] == "multi_candle_structure"
    assert bias["timeframes"]["H4"]["bars_used"] == 4
    assert bias["timeframes"]["M1"]["weight"] == 0


def test_proven_missing_new_h4_is_unknown_and_blocks_trade_bias() -> None:
    trader = v2.LiveTrader.__new__(v2.LiveTrader)
    old_h4 = candle(
        datetime(2026, 8, 23, 21, 0, tzinfo=timezone.utc),
        open_=100,
        high=105,
        low=99,
        close=104,
        minutes=240,
    )
    rows = []
    # A complete 01:00-05:00 M5 path proves that a newer closed H4 should exist.
    start = datetime(2026, 8, 24, 1, 0, tzinfo=timezone.utc)
    for index in range(48):
        stamp = start + timedelta(minutes=5 * index)
        rows.append(base_row(stamp, {"H4": old_h4, "M1": {"available": True, "direction": 1}}))
    latest = base_row(
        datetime(2026, 8, 24, 5, 55, tzinfo=timezone.utc),
        {
            "decision_time": datetime(2026, 8, 24, 6, 0, tzinfo=timezone.utc).isoformat(),
            "H4": old_h4,
            "M1": {"available": True, "direction": 1},
        },
    )
    rows.append(latest)
    trader._rows = rows

    bias, score = v43._bias_v43(trader, latest)

    assert bias["timeframes"]["H4"]["direction"] == "unknown"
    assert bias["timeframes"]["H4"]["stale"] is True
    assert "H4" in bias["data_quality"]["critical_stale"]
    assert bias["data_quality"]["trade_bias_blocked"] is True
    assert bias["overall"] == "neutral"
    assert score == 0.0


def test_wall_clock_age_without_completed_m5_path_does_not_false_flag_stale() -> None:
    trader = v2.LiveTrader.__new__(v2.LiveTrader)
    old_h4 = candle(
        datetime(2026, 8, 21, 17, 0, tzinfo=timezone.utc),
        open_=100,
        high=105,
        low=99,
        close=104,
        minutes=240,
    )
    latest = base_row(
        datetime(2026, 8, 24, 5, 55, tzinfo=timezone.utc),
        {
            "decision_time": datetime(2026, 8, 24, 6, 0, tzinfo=timezone.utc).isoformat(),
            "H4": old_h4,
            "M1": {"available": True, "direction": 1},
        },
    )
    trader._rows = [latest]

    assert v43._provably_stale(trader, latest, "H4", old_h4) is False
