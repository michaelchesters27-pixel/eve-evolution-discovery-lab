from __future__ import annotations

from typing import Any

from app.services import live_trader_market_events_v23 as events

LANGUAGE_VERSION = "eve-live-breakout-language-v2"
_base_classify_market_events = events.classify_market_events


def _clean_event(event: dict[str, Any]) -> dict[str, Any]:
    item = dict(event or {})
    event_class = str(item.get("event_class") or "none")
    level_label = str(item.get("level_label") or "the level")

    if event_class == "sell_side_sweep_reclaim":
        item["label"] = "POSSIBLE FAILED BEARISH BREAKOUT"
        item["display_confirmation"] = "possible"
        item["explanation"] = (
            f"Price pushed below {level_label}, swept sell-side liquidity, then came back above. "
            "Possible failed bearish breakout."
        )
    elif event_class == "buy_side_sweep_reclaim":
        item["label"] = "POSSIBLE FAILED BULLISH BREAKOUT"
        item["display_confirmation"] = "possible"
        item["explanation"] = (
            f"Price pushed above {level_label}, swept buy-side liquidity, then came back below. "
            "Possible failed bullish breakout."
        )
    elif event_class == "failed_breakout_up":
        item["label"] = "CONFIRMED FAILED BULLISH BREAKOUT"
        item["display_confirmation"] = "confirmed"
        item["explanation"] = (
            f"Price broke above {level_label} but could not hold above it. "
            "Confirmed failed bullish breakout."
        )
    elif event_class == "failed_breakout_down":
        item["label"] = "CONFIRMED FAILED BEARISH BREAKOUT"
        item["display_confirmation"] = "confirmed"
        item["explanation"] = (
            f"Price broke below {level_label} but could not hold below it. "
            "Confirmed failed bearish breakout."
        )
    elif event_class == "accepted_breakout_up":
        item["label"] = "BULLISH BREAKOUT HOLDING"
        item["display_confirmation"] = "holding"
        item["explanation"] = f"Price has broken above {level_label} and is holding above it."
    elif event_class == "accepted_breakout_down":
        item["label"] = "BEARISH BREAKOUT HOLDING"
        item["display_confirmation"] = "holding"
        item["explanation"] = f"Price has broken below {level_label} and is holding below it."
    elif event_class == "none":
        item["display_confirmation"] = "waiting"

    item["user_language_version"] = LANGUAGE_VERSION
    return item


def classify_market_events_plain_language(
    self: Any,
    rows: list[dict[str, Any]],
    liquidity: dict[str, Any],
) -> list[dict[str, Any]]:
    # User-language boundary only. Do not alter event_class, implication,
    # strength or the internal confirmation code used by learning.
    return [_clean_event(dict(item or {})) for item in _base_classify_market_events(self, rows, liquidity)]


events.classify_market_events = classify_market_events_plain_language
