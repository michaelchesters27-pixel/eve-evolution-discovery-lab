from __future__ import annotations

from typing import Any

from app.services import live_trader as core

STRUCTURE_READOUT_VERSION = "eve-live-structure-readout-v1"
PIVOT_WINDOW = 2
LOOKBACK_BARS = 180

_current_opinion_text = core.LiveTrader._opinion_text


def _num(value: Any, default: float = 0.0) -> float:
    return core.number(value, default)


def _row_day(row: dict[str, Any]) -> str:
    return str(row.get("candle_time") or "")[:10]


def _pivots(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    pivots: list[dict[str, Any]] = []
    window = PIVOT_WINDOW
    if len(rows) < window * 2 + 1:
        return pivots

    for index in range(window, len(rows) - window):
        row = rows[index]
        nearby = rows[index - window : index + window + 1]
        high = _num(row.get("high"))
        low = _num(row.get("low"))
        if high >= max(_num(item.get("high")) for item in nearby):
            pivots.append(
                {
                    "kind": "high",
                    "level": high,
                    "pivot_index": index,
                    "confirmed_index": index + window,
                    "pivot_time": row.get("candle_time"),
                }
            )
        if low <= min(_num(item.get("low")) for item in nearby):
            pivots.append(
                {
                    "kind": "low",
                    "level": low,
                    "pivot_index": index,
                    "confirmed_index": index + window,
                    "pivot_time": row.get("candle_time"),
                }
            )
    return pivots


def _structure_events(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    pivots = _pivots(rows)
    by_confirmation: dict[int, list[dict[str, Any]]] = {}
    for pivot in pivots:
        by_confirmation.setdefault(int(pivot["confirmed_index"]), []).append(pivot)

    active_high: dict[str, Any] | None = None
    active_low: dict[str, Any] | None = None
    consumed_high: tuple[Any, Any] | None = None
    consumed_low: tuple[Any, Any] | None = None
    structural_direction: str | None = None
    events: list[dict[str, Any]] = []

    for index, row in enumerate(rows):
        for pivot in by_confirmation.get(index, []):
            if pivot["kind"] == "high":
                active_high = pivot
                consumed_high = None
            else:
                active_low = pivot
                consumed_low = None

        close = _num(row.get("close"))
        atr = max(_num(row.get("atr_14"), 0.0), 0.01)
        buffer = max(atr * 0.02, 0.01)

        if active_high is not None and index > int(active_high["confirmed_index"]):
            key = (active_high.get("pivot_time"), active_high.get("level"))
            if consumed_high != key and close > _num(active_high.get("level")) + buffer:
                direction = "bullish"
                event_type = "choch" if structural_direction == "bearish" else "bos"
                events.append(
                    {
                        "type": event_type,
                        "direction": direction,
                        "level": round(_num(active_high.get("level")), 3),
                        "broken_at": row.get("candle_time"),
                        "session": row.get("session"),
                        "day": _row_day(row),
                        "bar_index": index,
                        "swing_time": active_high.get("pivot_time"),
                        "confirmation": "completed_m5_close",
                    }
                )
                structural_direction = direction
                consumed_high = key

        if active_low is not None and index > int(active_low["confirmed_index"]):
            key = (active_low.get("pivot_time"), active_low.get("level"))
            if consumed_low != key and close < _num(active_low.get("level")) - buffer:
                direction = "bearish"
                event_type = "choch" if structural_direction == "bullish" else "bos"
                events.append(
                    {
                        "type": event_type,
                        "direction": direction,
                        "level": round(_num(active_low.get("level")), 3),
                        "broken_at": row.get("candle_time"),
                        "session": row.get("session"),
                        "day": _row_day(row),
                        "bar_index": index,
                        "swing_time": active_low.get("pivot_time"),
                        "confirmation": "completed_m5_close",
                    }
                )
                structural_direction = direction
                consumed_low = key

    return events


def build_structure_readout(self: core.LiveTrader, state: dict[str, Any]) -> dict[str, Any]:
    source = list(getattr(self, "_rows", None) or [])[-LOOKBACK_BARS:]
    latest = source[-1] if source else {}
    current_day = _row_day(latest)
    current_session = str(latest.get("session") or (state.get("market") or {}).get("session") or "unknown")

    events = _structure_events(source)
    current_events = [
        event
        for event in events
        if str(event.get("day") or "") == current_day
        and (current_session == "unknown" or str(event.get("session") or "unknown") == current_session)
    ]

    latest_choch = next((event for event in reversed(current_events) if event.get("type") == "choch"), None)
    latest_bos = next((event for event in reversed(current_events) if event.get("type") == "bos"), None)

    bos_support = "none"
    bos_waiting_after_choch = False
    if latest_bos is not None:
        if latest_choch is None or int(latest_bos.get("bar_index", -1)) > int(latest_choch.get("bar_index", -1)):
            bos_support = str(latest_bos.get("direction") or "none")
        else:
            bos_waiting_after_choch = True
    elif latest_choch is not None:
        bos_waiting_after_choch = True

    choch_direction = str((latest_choch or {}).get("direction") or "none")
    if bos_support in {"bullish", "bearish"}:
        structure_support = bos_support
        summary = f"BOS supports {bos_support.upper()}."
        if latest_choch is not None:
            summary += f" Latest CHoCH was {choch_direction.upper()}."
    elif latest_choch is not None:
        structure_support = f"{choch_direction}_change"
        summary = f"{choch_direction.upper()} CHoCH detected; waiting for a confirming {choch_direction.upper()} BOS."
    else:
        structure_support = "none"
        summary = "No current-session BOS or CHoCH is confirmed yet."

    return {
        "version": STRUCTURE_READOUT_VERSION,
        "timeframe": "M5",
        "method": "confirmed_swing_break_by_completed_m5_close",
        "session": current_session,
        "day": current_day,
        "bos_support": bos_support,
        "bos_waiting_after_choch": bos_waiting_after_choch,
        "bos": latest_bos,
        "choch_direction": choch_direction,
        "choch_present": latest_choch is not None,
        "choch": latest_choch,
        "structure_support": structure_support,
        "summary": summary,
        "display_only": True,
        "affects_trade_gate": False,
        "affects_session_outlook_score": False,
        "events_in_current_session": len(current_events),
    }


def _opinion_text_v57(self: core.LiveTrader, state: dict[str, Any]) -> str:
    # Let v55 build the directional session opinion first. We then attach a
    # read-only structure panel. Nothing here changes bias, confidence, trade,
    # setup, targets, stops, campaign state or the session-outlook score.
    text = _current_opinion_text(self, state)
    readout = build_structure_readout(self, state)

    outlook = dict(state.get("session_outlook") or {})
    outlook["structure"] = readout
    state["session_outlook"] = outlook

    market = dict(state.get("market") or {})
    market_outlook = dict(market.get("session_outlook") or {})
    market_outlook["structure"] = readout
    market["session_outlook"] = market_outlook
    state["market"] = market
    return text


core.LiveTrader._opinion_text = _opinion_text_v57  # type: ignore[method-assign]
