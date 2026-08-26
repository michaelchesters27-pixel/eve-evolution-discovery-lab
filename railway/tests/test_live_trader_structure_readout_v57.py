from __future__ import annotations

from app.services import live_trader as core
from app.services import live_trader_structure_readout_v57 as structure
from app.services import live_trader_zone_target_runtime_v51 as runtime


class DummyTrader:
    def __init__(self, rows: list[dict]):
        self._rows = rows


def _row(index: int, high: float, low: float, close: float) -> dict:
    hour = 8 + index // 12
    minute = (index % 12) * 5
    return {
        "candle_time": f"2026-08-26T{hour:02d}:{minute:02d}:00+00:00",
        "open": close,
        "high": high,
        "low": low,
        "close": close,
        "atr_14": 2.0,
        "session": "london",
    }


def test_completed_m5_structure_detects_bearish_bos_then_bullish_choch() -> None:
    values = [
        (100, 98, 99),
        (102, 99, 101),
        (105, 100, 104),  # confirmed swing high
        (103, 98, 99),
        (101, 95, 96),   # confirmed swing low
        (100, 96, 98),
        (99, 96, 97),
        (98, 93, 94),    # close breaks swing low -> bearish BOS
        (99, 94, 98),
        (103, 97, 102),  # next confirmed swing high
        (101, 97, 99),
        (100, 96, 98),
        (102, 97, 101),
        (106, 100, 105), # close breaks swing high -> bullish CHoCH
        (104, 101, 103),
        (103, 99, 100),
    ]
    trader = DummyTrader([_row(index, *value) for index, value in enumerate(values)])
    state = {"market": {"session": "london"}, "trade": {"action": "WAIT"}}

    readout = structure.build_structure_readout(trader, state)

    assert readout["choch_present"] is True
    assert readout["choch_direction"] == "bullish"
    assert readout["choch"]["level"] == 103.0
    assert readout["bos_waiting_after_choch"] is True
    assert readout["bos_support"] == "none"
    assert "waiting for a confirming BULLISH BOS" in readout["summary"]
    assert readout["display_only"] is True
    assert readout["affects_trade_gate"] is False
    assert readout["affects_session_outlook_score"] is False
    assert state["trade"] == {"action": "WAIT"}


def test_structure_display_does_not_replace_hardened_trade_engine() -> None:
    assert core.LiveTrader._trade_idea is runtime._trade_idea_v51
