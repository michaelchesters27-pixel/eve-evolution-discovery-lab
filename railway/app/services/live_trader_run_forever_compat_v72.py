from __future__ import annotations

from app.services import live_trader as core
from app.services import live_trader_audit_hardening_v26 as hardening
from app.services import live_trader_execution_integrity_v39 as integrity
from app.services import live_trader_historical_runtime_v30 as historical_runtime
from app.services import live_trader_zone_retrace_current_policy_academy_v71 as v71

COMPAT_VERSION = "eve-live-run-forever-compat-v72"
_latest_run_forever = core.LiveTrader.run_forever

# Earlier audit modules intentionally export aliases to the newest production
# runtime wrapper. v68/v71 added background academy tasks after those modules had
# captured their aliases, so restore the established identity contract without
# changing the actual wrapper chain or starting another task.
hardening._run_forever_v26 = _latest_run_forever
integrity._run_forever_v39 = _latest_run_forever
historical_runtime._run_forever_v30 = _latest_run_forever

_current_runtime_status = core.LiveTrader.runtime_status


def _runtime_status_v72(self: core.LiveTrader):
    status = dict(_current_runtime_status(self))
    status.update(
        {
            "run_forever_compat_version": COMPAT_VERSION,
            "run_forever_aliases_point_to_latest_runtime": True,
            "latest_run_forever_wrapper": v71.ACADEMY_VERSION,
        }
    )
    return status


core.LiveTrader.runtime_status = _runtime_status_v72  # type: ignore[method-assign]
