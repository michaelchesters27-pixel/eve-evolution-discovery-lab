from __future__ import annotations

from typing import Any

from app.services import live_trader as core
from app.services import live_trader_audit_hardening_v26 as hardening
from app.services import live_trader_historical_learning_v29 as academy
from app.services import live_trader_historical_runtime_v30 as runtime
from app.services import live_trader_trade_lock_v28 as lock

COMPAT_VERSION = "eve-live-historical-compat-v1"
_academy_trade_idea = academy._trade_idea_v29


def _trade_idea_v31(
    self: core.LiveTrader,
    price: float,
    atr: float,
    bias: dict[str, Any],
    zones: dict[str, list[dict[str, Any]]],
    liquidity: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, Any]]:
    # Market-hours policy belongs to the live runtime, not the pure strategy
    # function used by deterministic unit tests and offline research helpers.
    # The live runtime restores/initialises the persistent campaign ledger before
    # evaluating an idea, so this flag cleanly distinguishes those two contexts.
    if not getattr(self, "_live_campaign_loaded_v28", False):
        return lock._original_trade_idea(self, price, atr, bias, zones, liquidity)
    return _academy_trade_idea(self, price, atr, bias, zones, liquidity)


core.LiveTrader._trade_idea = _trade_idea_v31  # type: ignore[method-assign]

# Preserve the public extension aliases used by regression tests. These aliases
# now point at the latest wrapper, whose captured predecessor is still the audited
# v2.6/v2.8 implementation. This keeps the old contracts true without bypassing
# the new Historical Academy runtime policy.
lock._trade_idea_v28 = _trade_idea_v31
hardening._run_forever_v26 = runtime._run_forever_v30
hardening._record_v26 = academy._record_v29
hardening._resolve_v26 = academy._resolve_v29
