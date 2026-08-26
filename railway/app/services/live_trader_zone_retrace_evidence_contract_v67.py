from __future__ import annotations

from typing import Any

from app.services import live_trader as core
from app.services import live_trader_zone_retrace_integrity_v64 as v64

EVIDENCE_CONTRACT_VERSION = "eve-live-zone-retrace-evidence-contract-v67"
RESEARCH_TARGET_R = 2.2
LIVE_TARGET_CAP_R = 1.5

_prior_audited_specialist = v64._audited_specialist
_current_learning_summary = core.LiveTrader.learning_summary
_current_runtime_status = core.LiveTrader.runtime_status


def _evidence_contract(payload: dict[str, Any]) -> dict[str, Any]:
    """Prevent the historical baseline from masquerading as live-policy proof.

    The existing Historical Academy challenger called `market` enters immediately
    at the historical decision price and uses a 2.2R target. Live Trader instead
    waits for price to retrace into the selected zone, requires M5/M15 confirmation,
    then publishes a market campaign whose target is capped at 1.5R by v49.
    Those are different execution contracts. The 173-episode baseline remains
    useful research evidence, but it cannot promote a live execution until the
    exact live contract is causally rescored from source M1 paths.
    """
    specialist = dict(_prior_audited_specialist(payload or {}))

    research_best = specialist.get("research_best_execution")
    if research_best is None:
        research_best = specialist.get("best_execution")
    research_promoted = specialist.get("research_promoted_execution")
    if research_promoted is None:
        research_promoted = specialist.get("promoted_execution")

    evidence = dict(specialist.get("execution_evidence") or {})
    specialist.update(
        {
            "evidence_contract_version": EVIDENCE_CONTRACT_VERSION,
            "research_execution_evidence": evidence,
            "research_best_execution": research_best,
            "research_promoted_execution": research_promoted,
            "research_entry_policy": "immediate_market_at_historical_decision_price",
            "research_target_r": RESEARCH_TARGET_R,
            "research_evidence_verified": bool(evidence),
            "live_entry_policy": "market_after_zone_retrace_and_m5_m15_confirmation",
            "live_target_cap_r": LIVE_TARGET_CAP_R,
            "live_policy_execution_evidence": dict(specialist.get("live_policy_execution_evidence") or {}),
            "live_policy_expectancy_verified": False,
            "live_promoted_execution": None,
            "promoted_execution": None,
            "phase": "LIVE POLICY RESCORE REQUIRED" if evidence else "DEEP LEARNING",
            "status": "research_only_rescore_required" if evidence else specialist.get("status", "learning"),
            "promotion_blocked": True,
            "promotion_block_reason": (
                "The current 173-episode execution comparison uses immediate decision-price entry and 2.2R targets. "
                "Live Trader waits for zone retracement plus M5/M15 confirmation and caps new targets at 1.5R. "
                "A causal source-M1 rescore of the exact live contract is required before any execution method can be promoted for live policy."
            ),
            "live_policy_rescore_status": "required",
        }
    )

    # Preserve the familiar best_execution field only as a research result, and
    # make its scope impossible to mistake for live authority.
    specialist["best_execution"] = research_best
    specialist["best_execution_scope"] = "research_immediate_entry_2_2r"
    specialist["scored_examples_scope"] = "research_immediate_entry_2_2r"
    specialist["raw_success_rate_scope"] = "research_immediate_entry_2_2r"
    return specialist


async def _learning_summary_v67(self: core.LiveTrader) -> dict[str, Any]:
    summary = dict(await _current_learning_summary(self))
    specialist = dict(summary.get("zone_retrace_specialist") or getattr(self, "_zone_retrace_learning_v58", {}) or {})
    if specialist:
        specialist = _evidence_contract(specialist)
        summary["zone_retrace_specialist"] = specialist
    summary["zone_retrace_evidence_contract"] = {
        "version": EVIDENCE_CONTRACT_VERSION,
        "research_entry_policy": "immediate_market_at_historical_decision_price",
        "research_target_r": RESEARCH_TARGET_R,
        "live_entry_policy": "market_after_zone_retrace_and_m5_m15_confirmation",
        "live_target_cap_r": LIVE_TARGET_CAP_R,
        "live_policy_expectancy_verified": False,
        "live_policy_rescore_status": "required",
    }
    return summary


def _runtime_status_v67(self: core.LiveTrader) -> dict[str, Any]:
    status = dict(_current_runtime_status(self))
    status.update(
        {
            "zone_retrace_evidence_contract_version": EVIDENCE_CONTRACT_VERSION,
            "zone_retrace_research_target_r": RESEARCH_TARGET_R,
            "zone_retrace_live_target_cap_r": LIVE_TARGET_CAP_R,
            "zone_retrace_live_policy_expectancy_verified": False,
            "zone_retrace_live_promotion_blocked_pending_rescore": True,
        }
    )
    return status


# Every later state-integrity injection resolves v64._audited_specialist at call
# time, so this one patch protects API state, persisted state and future cycles.
v64._audited_specialist = _evidence_contract
core.LiveTrader.learning_summary = _learning_summary_v67  # type: ignore[method-assign]
core.LiveTrader.runtime_status = _runtime_status_v67  # type: ignore[method-assign]
