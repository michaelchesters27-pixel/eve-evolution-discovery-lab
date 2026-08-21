from __future__ import annotations

import re
from typing import Any

from app.services import live_trader as core
from app.services import live_trader_trade_lock_v28 as lock

COMPAT_VERSION = "eve-live-trade-lock-compat-v1"
_v28_trade_idea = lock._trade_idea_v28


def _invalidation_price_v29(trade: dict[str, Any]) -> float:
    text = str(trade.get("invalidation") or "")
    directional = re.findall(r"(?:below|above)\s+(\d+(?:\.\d+)?)", text, flags=re.IGNORECASE)
    if directional:
        return lock._num(directional[-1], lock._num(trade.get("stop")))
    numbers = re.findall(r"(?<!\d)(\d+(?:\.\d+)?)(?!\d)", text)
    if numbers:
        return lock._num(numbers[-1], lock._num(trade.get("stop")))
    return lock._num(trade.get("stop"))


def _trade_idea_v29(
    self: core.LiveTrader,
    price: float,
    atr: float,
    bias: dict[str, Any],
    zones: dict[str, list[dict[str, Any]]],
    liquidity: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, Any]]:
    # The campaign lock is a runtime concern. Pure strategy/unit calls to
    # _trade_idea have not restored the campaign ledger yet and must retain
    # the underlying execution-engine semantics for deterministic testing.
    if not getattr(self, "_live_campaign_loaded_v28", False):
        return lock._original_trade_idea(self, price, atr, bias, zones, liquidity)
    return _v28_trade_idea(self, price, atr, bias, zones, liquidity)


lock._invalidation_price = _invalidation_price_v29
lock._trade_idea_v28 = _trade_idea_v29
core.LiveTrader._trade_idea = _trade_idea_v29  # type: ignore[method-assign]
