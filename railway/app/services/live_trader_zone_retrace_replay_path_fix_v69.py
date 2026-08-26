from __future__ import annotations

from typing import Any

from app.services import live_trader as core
from app.services import live_trader_audit_hardening_v26 as hardening
from app.services import live_trader_zone_retrace_live_policy_replay_v68 as v68

FIX_VERSION = "eve-live-zone-retrace-replay-path-fix-v69"
_current_runtime_status = core.LiveTrader.runtime_status


def _finite_number(value: Any) -> float | None:
    if value is None:
        return None
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result


def _path_complete_v69(path: dict[str, Any]) -> bool:
    endpoint_lag = _finite_number(path.get("endpoint_lag_seconds"))
    initial_gap = _finite_number(path.get("initial_gap_seconds"))
    gap_count = path.get("gap_count")
    try:
        gaps = int(gap_count) if gap_count is not None else None
    except (TypeError, ValueError):
        gaps = None
    return bool(
        path.get("endpoint_price") is not None
        and path.get("endpoint_time") is not None
        and endpoint_lag is not None
        and endpoint_lag <= hardening.MAX_ENDPOINT_LAG_SECONDS
        and initial_gap is not None
        and initial_gap <= 1.0
        and gaps == 0
    )


def _runtime_status_v69(self: core.LiveTrader) -> dict[str, Any]:
    status = dict(_current_runtime_status(self))
    status.update(
        {
            "zone_retrace_replay_path_fix_version": FIX_VERSION,
            "zero_initial_gap_is_valid": True,
            "zero_endpoint_lag_is_valid": True,
        }
    )
    return status


# v68 resolves this module global at replay time. Patch it before FastAPI lifespan
# starts the background worker so a perfect 0-second gap/lag is correctly accepted.
v68._path_complete = _path_complete_v69
core.LiveTrader.runtime_status = _runtime_status_v69  # type: ignore[method-assign]
