from __future__ import annotations

from typing import Any

from app.services import live_trader_market_events_v23 as events

WORDING_VERSION = "eve-live-breakout-wording-v1"
_base_classify_market_events = events.classify_market_events


def _clear_label(event: dict[str, Any]) -> str:
    event_class = str(event.get("event_class") or "none")
    labels = {
        "buy_side_sweep_reclaim": "POSSIBLE FAILED BULLISH BREAKOUT",
        "sell_side_sweep_reclaim": "POSSIBLE FAILED BEARISH BREAKOUT",
        "failed_breakout_up": "CONFIRMED FAILED BULLISH BREAKOUT",
        "failed_breakout_down": "CONFIRMED FAILED BEARISH BREAKOUT",
        "accepted_breakout_up": "BULLISH BREAKOUT HOLDING",
        "accepted_breakout_down": "BEARISH BREAKOUT HOLDING",
    }
    return labels.get(event_class, str(event.get("label") or "LIQUIDITY EVENT"))


def classify_market_events_clear_wording(
    self: Any,
    rows: list[dict[str, Any]],
    liquidity: dict[str, Any],
) -> list[dict[str, Any]]:
    # Wording-only wrapper. Event class, implication, strength, confirmation and
    # every trading/learning input remain unchanged.
    result: list[dict[str, Any]] = []
    for item in _base_classify_market_events(self, rows, liquidity):
        event = dict(item or {})
        event["label"] = _clear_label(event)
        result.append(event)
    return result


def _event_sentence_v53(state: dict[str, Any]) -> str:
    event = dict(((state.get("liquidity") or {}).get("primary_event") or {}))
    event_class = str(event.get("event_class") or "none")
    if event_class == "none":
        return "Micky, I do not have an active liquidity sweep or breakout failure strong enough to call right now."

    level = events._num(event.get("level"))
    level_label = event.get("level_label") or "the level"

    if event_class == "buy_side_sweep_reclaim":
        return (
            f"Micky, possible failed bullish breakout at {level_label} around {level:.2f}. "
            "Price pushed above it, swept buy-side liquidity, then came back below. "
            "That is a bearish warning unless price gets back above and holds."
        )
    if event_class == "sell_side_sweep_reclaim":
        return (
            f"Micky, possible failed bearish breakout at {level_label} around {level:.2f}. "
            "Price pushed below it, swept sell-side liquidity, then came back above. "
            "That is a bullish warning unless price drops back below and holds."
        )
    if event_class == "failed_breakout_up":
        return (
            f"Micky, confirmed failed bullish breakout at {level_label} around {level:.2f}. "
            "Price had broken above it but could not hold above, so the failed move is currently bearish."
        )
    if event_class == "failed_breakout_down":
        return (
            f"Micky, confirmed failed bearish breakout at {level_label} around {level:.2f}. "
            "Price had broken below it but could not hold below, so the failed move is currently bullish."
        )
    if event_class == "accepted_breakout_up":
        return (
            f"Micky, the bullish breakout above {level_label} around {level:.2f} is holding for now. "
            "I will only call it failed if price loses that level again."
        )
    if event_class == "accepted_breakout_down":
        return (
            f"Micky, the bearish breakout below {level_label} around {level:.2f} is holding for now. "
            "I will only call it failed if price reclaims that level again."
        )
    return f"Micky, the active market event is {_clear_label(event)} at {level_label}."


# v23's opinion, trade-sentence and chat functions resolve these module globals at
# call time, so this wording patch changes what EVE says without changing the
# underlying event classifications or trading decisions.
events.classify_market_events = classify_market_events_clear_wording
events._event_sentence = _event_sentence_v53
