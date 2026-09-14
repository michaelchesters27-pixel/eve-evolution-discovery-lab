from __future__ import annotations

from app.services import live_trader as core
from app.services import live_trader_historical_runtime_v30 as historical_runtime
from app.services import live_trader_trade_lock_v28 as lock
from app.services import live_trader_trade_outcomes_v38 as outcomes
from app.services import live_trader_zone_retrace_integrity_v64 as v64
from app.services import live_trader_zone_retrace_specialist_v58 as v58

COMPAT_VERSION = "eve-live-forward-shadow-compat-v84"
_latest_refresh_state = core.LiveTrader.refresh_state
_current_runtime_status = core.LiveTrader.runtime_status

# The older safety modules deliberately expose aliases to the newest production
# refresh wrapper. v83 adds forward/shadow learning after v65, so move those
# aliases to the new wrapper without changing any safety or trade-decision logic.
lock._refresh_state_v28 = _latest_refresh_state
historical_runtime._refresh_state_v30 = _latest_refresh_state
outcomes._refresh_v38 = _latest_refresh_state
v58._refresh_state_v58 = _latest_refresh_state

# v64 keeps module references used by several regression/audit contracts.
v64.v58._refresh_state_v58 = _latest_refresh_state
v64.historical_runtime._refresh_state_v30 = _latest_refresh_state
v64.outcomes._refresh_v38 = _latest_refresh_state


def _runtime_status_v84(self: core.LiveTrader):
    status = dict(_current_runtime_status(self))
    status.update(
        {
            "forward_shadow_compat_version": COMPAT_VERSION,
            "refresh_aliases_point_to_latest_runtime": True,
        }
    )
    return status


core.LiveTrader.runtime_status = _runtime_status_v84  # type: ignore[method-assign]
