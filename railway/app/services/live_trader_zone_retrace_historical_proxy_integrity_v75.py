from __future__ import annotations

from typing import Any

from app.services import live_trader as core
from app.services import live_trader_zone_retrace_current_policy_academy_v71 as v71
from app.services import live_trader_zone_retrace_integrity_v64 as v64

INTEGRITY_VERSION = "eve-live-zone-retrace-historical-proxy-integrity-v75"
HISTORICAL_EXECUTION_RESOLUTION = "causal_m1_proxy"

_prior_current_policy_contract = v71._current_policy_contract
_current_runtime_status = core.LiveTrader.runtime_status


def _current_policy_contract_v75(payload: dict[str, Any]) -> dict[str, Any]:
    specialist = dict(_prior_current_policy_contract(payload or {}))

    # v71 reconstructs today's policy causally from completed M5 state and source
    # M1 execution bars. That is the best historical resolution available, but it
    # is not tick-exact. Preserve the useful historical qualification separately
    # from any claim of live/forward proof.
    historical_verified = bool(specialist.get("live_policy_expectancy_verified"))
    academy = dict(specialist.get("current_policy_academy") or {})
    historical_screening_candidate = bool(
        specialist.get("historical_screening_candidate")
        or dict(academy.get("policy") or {}).get("historical_screening_candidate")
        or specialist.get("live_promoted_execution")  # legacy pre-v92 candidate becomes screening-only
    )
    historical_candidate = "market_after_zone_confirmation" if historical_screening_candidate else None

    specialist.update(
        {
            "historical_proxy_integrity_version": INTEGRITY_VERSION,
            "historical_policy_proxy_resolution": HISTORICAL_EXECUTION_RESOLUTION,
            "historical_policy_proxy_verified": historical_verified,
            "historical_policy_proxy_caught_up": bool(academy.get("caught_up")),
            "historical_policy_proxy_candidate_execution": historical_candidate,
            "historical_tick_exact": False,
            "historical_tick_exact_reason": (
                "The archive reconstructs current policy from completed M5 state and causal M1 OHLC bars. "
                "Intraminute tick ordering is unavailable, so same-minute ambiguity is scored conservatively stop-first."
            ),
            "forward_live_campaign_validation_required": True,
            "live_policy_tick_exact_verified": False,
            "live_policy_entry_geometry_verified": False,
            "historical_policy_proxy_entry_geometry_verified": historical_verified,
            "historical_entry_execution_edge_supported": False,
            "historical_screening_candidate": historical_screening_candidate,
            "historical_screening_candidate_execution": historical_candidate,
            "historical_proxy_may_auto_promote": False,
            "live_entry_execution_edge_supported": False,
            "live_strategy_edge_proven": False,
            "promotion_scope": "historical_screening_only" if historical_candidate else "none",
        }
    )

    if historical_candidate:
        # Do not let a historical M1 qualification masquerade as a live promotion.
        specialist["live_promoted_execution"] = None
        specialist["promoted_execution"] = None
        specialist["promotion_blocked"] = True
        specialist["promotion_block_reason"] = (
            "The current-policy causal M1 archive has passed the predeclared historical screening thresholds, "
            "but that selection evidence is not confirmation. A fresh prospective forward cohort is required."
        )
        specialist["phase"] = "HISTORICAL M1 SCREENING CANDIDATE"
        specialist["status"] = "historical_m1_screening_candidate_fresh_forward_confirmation_required"
    elif historical_verified:
        specialist["phase"] = "CURRENT-POLICY M1 PROXY VERIFIED"
        specialist["status"] = "current_policy_m1_proxy_verified_no_candidate"
        specialist["promotion_blocked"] = True
        specialist["promotion_block_reason"] = (
            "The causal M1 current-policy archive is verified but has not met the historical screening thresholds."
        )
    else:
        specialist["phase"] = "CURRENT-POLICY M1 PROXY SCANNING"
        specialist["status"] = "current_policy_m1_proxy_scanning"

    return specialist


def _runtime_status_v75(self: core.LiveTrader) -> dict[str, Any]:
    status = dict(_current_runtime_status(self))
    status.update(
        {
            "zone_retrace_historical_proxy_integrity_version": INTEGRITY_VERSION,
            "zone_retrace_historical_execution_resolution": HISTORICAL_EXECUTION_RESOLUTION,
            "zone_retrace_historical_tick_exact": False,
            "zone_retrace_forward_live_validation_required": True,
            "zone_retrace_live_strategy_edge_proven": False,
        }
    )
    return status


# v71's learning-summary function resolves this module global at call time, and
# state-integrity resolves v64._audited_specialist dynamically before persistence.
v71._current_policy_contract = _current_policy_contract_v75
v64._audited_specialist = _current_policy_contract_v75
core.LiveTrader.runtime_status = _runtime_status_v75  # type: ignore[method-assign]
