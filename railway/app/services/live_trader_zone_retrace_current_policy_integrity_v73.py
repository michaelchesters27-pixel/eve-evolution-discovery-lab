from __future__ import annotations

import os
import socket
from typing import Any

from app.services import live_trader as core
from app.services import live_trader_zone_retrace_current_policy_academy_v71 as v71
from app.services import live_trader_zone_retrace_integrity_v64 as v64

INTEGRITY_VERSION = "eve-live-zone-retrace-current-policy-integrity-v73"
SCAN_LEASE_SECONDS = 300

_original_run_cycle = v71.CurrentPolicyZoneRetraceAcademy.run_cycle
_original_replay_current_opportunity = v71.CurrentPolicyZoneRetraceAcademy._replay_current_opportunity
_current_runtime_status = core.LiveTrader.runtime_status


def _lease_owner() -> str:
    return f"{socket.gethostname()}:{os.getpid()}"


async def _replay_current_opportunity_v73(
    self: v71.CurrentPolicyZoneRetraceAcademy,
    opportunity: dict[str, Any],
) -> dict[str, Any]:
    result = dict(await _original_replay_current_opportunity(self, opportunity) or {})
    # A no-entry observation is still directional evidence. Preserve the side so
    # every opportunity can be audited without inferring BUY/SELL from free text.
    if not result.get("side"):
        result["side"] = opportunity.get("side")
    details = dict(result.get("details") or {})
    details["current_policy_integrity_version"] = INTEGRITY_VERSION
    details["side_preserved_without_entry"] = bool(result.get("side") and not result.get("entry_at"))
    result["details"] = details
    return result


async def _run_cycle_v73(self: v71.CurrentPolicyZoneRetraceAcademy) -> bool:
    claim_payload = await self.repo.client.rpc(
        "claim_live_trader_zone_retrace_current_policy_scan",
        {
            "p_symbol": self.symbol,
            "p_academy_version": v71.ACADEMY_VERSION,
            "p_owner": _lease_owner(),
            "p_lease_seconds": SCAN_LEASE_SECONDS,
        },
    )
    claim = v64._row_from_rpc(claim_payload)
    if not bool(claim.get("claimed")):
        # Another Railway process owns this archive slice. Return as progress so
        # the outer loop retries shortly rather than sleeping for the caught-up interval.
        return True

    token = str(claim.get("claim_token") or "")
    if not token:
        raise RuntimeError("current-policy academy database lease returned no claim token")

    try:
        return await _original_run_cycle(self)
    finally:
        try:
            await self.repo.client.rpc(
                "release_live_trader_zone_retrace_current_policy_scan",
                {"p_symbol": self.symbol, "p_claim_token": token},
            )
        except Exception as exc:
            # The lease is time-bounded, so a failed release cannot permanently
            # deadlock the academy. Surface it in logs for auditability.
            core.logger.warning("Current-policy academy could not release v73 scan lease: %s", exc)


def _runtime_status_v73(self: core.LiveTrader) -> dict[str, Any]:
    status = dict(_current_runtime_status(self))
    status.update(
        {
            "zone_retrace_current_policy_integrity_version": INTEGRITY_VERSION,
            "zone_retrace_current_policy_cross_process_scan_lease": True,
            "zone_retrace_current_policy_scan_lease_seconds": SCAN_LEASE_SECONDS,
            "zone_retrace_current_policy_no_entry_side_preserved": True,
        }
    )
    return status


v71.CurrentPolicyZoneRetraceAcademy._replay_current_opportunity = _replay_current_opportunity_v73  # type: ignore[method-assign]
v71.CurrentPolicyZoneRetraceAcademy.run_cycle = _run_cycle_v73  # type: ignore[method-assign]
core.LiveTrader.runtime_status = _runtime_status_v73  # type: ignore[method-assign]
