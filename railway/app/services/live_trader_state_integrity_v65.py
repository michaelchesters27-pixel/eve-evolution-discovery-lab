from __future__ import annotations

from typing import Any

from app.services import live_trader as core
from app.services import live_trader_trade_lock_v28 as lock
from app.services import live_trader_zone_retrace_integrity_v64 as v64

STATE_INTEGRITY_VERSION = "eve-live-state-integrity-v65"

_current_refresh_state = core.LiveTrader.refresh_state
_current_persist_state = core.LiveTrader._maybe_persist_state
_current_runtime_status = core.LiveTrader.runtime_status


def _inject_integrity_state(self: core.LiveTrader, state: dict[str, Any]) -> dict[str, Any]:
    specialist = dict(getattr(self, "_zone_retrace_learning_v58", {}) or state.get("zone_retrace_learning") or {})
    if specialist:
        specialist = v64._audited_specialist(specialist)
        state["zone_retrace_learning"] = specialist
        learning = dict(state.get("learning") or {})
        learning["zone_retrace_specialist"] = specialist
        learning["strategy_specialist"] = specialist
        state["learning"] = learning

    mtf_map = dict(getattr(self, "_mtf_zone_map_v63", {}) or {})
    if mtf_map:
        state["mtf_zone_map"] = mtf_map

    integrity = dict(state.get("state_integrity") or {})
    integrity.update(
        {
            "version": STATE_INTEGRITY_VERSION,
            "specialist_state_synchronised_before_persist": bool(specialist),
            "mtf_zone_map_persisted": bool(mtf_map),
        }
    )
    state["state_integrity"] = integrity
    return state


async def _maybe_persist_state_v65(self: core.LiveTrader, state: dict[str, Any]) -> None:
    _inject_integrity_state(self, state)
    await _current_persist_state(self, state)


async def _refresh_state_v65(self: core.LiveTrader, *, force_rows: bool = False) -> dict[str, Any]:
    state = dict(await _current_refresh_state(self, force_rows=force_rows))
    _inject_integrity_state(self, state)
    self._latest_state = state
    return state


def _runtime_status_v65(self: core.LiveTrader) -> dict[str, Any]:
    status = dict(_current_runtime_status(self))
    status.update(
        {
            "live_state_integrity_version": STATE_INTEGRITY_VERSION,
            "specialist_state_persisted_before_write": True,
            "mtf_zone_map_persisted": True,
        }
    )
    return status


core.LiveTrader._maybe_persist_state = _maybe_persist_state_v65  # type: ignore[method-assign]
core.LiveTrader.refresh_state = _refresh_state_v65  # type: ignore[method-assign]
core.LiveTrader.runtime_status = _runtime_status_v65  # type: ignore[method-assign]

# Preserve the established newest-wrapper alias contract used by older safety
# modules and regression tests.
lock._maybe_persist_state_v28 = _maybe_persist_state_v65
lock._refresh_state_v28 = _refresh_state_v65
v64.v58._refresh_state_v58 = _refresh_state_v65
v64.historical_runtime._refresh_state_v30 = _refresh_state_v65
v64.outcomes._refresh_v38 = _refresh_state_v65
