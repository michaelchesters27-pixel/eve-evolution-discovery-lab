from __future__ import annotations

from typing import Any

from app.services import live_trader as core
from app.services import live_trader_audit_hardening_v26 as hardening
from app.services import live_trader_execution_integrity_v39 as integrity
from app.services import live_trader_historical_learning_v29 as academy
from app.services import live_trader_trade_lock_v28 as lock

COMPAT_VERSION = "eve-live-execution-integrity-compat-v1"
_v39_record = integrity._record_v39
_v39_trade_idea = integrity._trade_idea_v39


async def _record_v40(self: core.LiveTrader, state: dict[str, Any]) -> None:
    # Historical/unit helpers have not restored the live campaign ledger. Preserve
    # their deterministic learning semantics; v39's regrade-ready/campaign gates
    # belong only to the live runtime.
    if not getattr(self, "_live_campaign_loaded_v28", False):
        await integrity._current_record(self, state)
        return
    await _v39_record(self, state)


def _trade_idea_v40(
    self: core.LiveTrader,
    price: float,
    atr: float,
    bias: dict[str, Any],
    zones: dict[str, list[dict[str, Any]]],
    liquidity: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, Any]]:
    if not getattr(self, "_live_campaign_loaded_v28", False):
        return integrity._current_trade_idea(self, price, atr, bias, zones, liquidity)
    return _v39_trade_idea(self, price, atr, bias, zones, liquidity)


# Rebind the exported v39 names as compatibility aliases so existing identity
# regression contracts continue to describe the newest runtime implementation.
integrity._record_v39 = _record_v40
integrity._trade_idea_v39 = _trade_idea_v40
core.LiveTrader._maybe_record_opinion = _record_v40  # type: ignore[method-assign]
core.LiveTrader._trade_idea = _trade_idea_v40  # type: ignore[method-assign]
hardening._record_v26 = _record_v40
academy._record_v29 = _record_v40
lock._trade_idea_v28 = _trade_idea_v40
