from __future__ import annotations

from typing import Any

from app.services import live_trader as core
from app.services import live_trader_clear_bias_gate_v45 as clear_gate
from app.services import live_trader_execution_integrity_v39 as integrity
from app.services import live_trader_london_session_gate_v46 as session_gate
from app.services import live_trader_trade_lock_v28 as lock
from app.services import live_trader_zone_target_guard_v49 as v49

RUNTIME_VERSION = "eve-live-zone-target-runtime-v1"
_v49_trade_idea = v49._trade_idea_v49
_session_trade_idea = v49._current_trade_idea


def _is_v49_campaign(campaign: dict[str, Any]) -> bool:
    return "source_zone_required" in campaign or isinstance(campaign.get("target_policy"), dict)


def _trade_idea_v51(
    self: core.LiveTrader,
    price: float,
    atr: float,
    bias: dict[str, Any],
    zones: dict[str, list[dict[str, Any]]],
    liquidity: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, Any]]:
    campaign = getattr(self, "_live_campaign", None)
    status = str((campaign or {}).get("status") or "").lower() if isinstance(campaign, dict) else ""
    if isinstance(campaign, dict) and status == "pending":
        if not _is_v49_campaign(campaign):
            return _session_trade_idea(self, price, atr, bias, zones, liquidity)
        if clear_gate._is_modern_structural_bias(dict(bias or {})):
            session = session_gate._session_status()
            created_inside = session_gate._campaign_created_inside_session(campaign)
            if created_inside is False or not bool(session.get("open")):
                return _session_trade_idea(self, price, atr, bias, zones, liquidity)
    return _v49_trade_idea(self, price, atr, bias, zones, liquidity)


def _runtime_status_v51(self: core.LiveTrader) -> dict[str, Any]:
    state = dict(v49._runtime_status_v49(self))
    state.update({
        "zone_target_runtime_version": RUNTIME_VERSION,
        "legacy_pending_campaigns_preserve_prior_chain": True,
        "session_gate_precedes_v49_pending_revalidation": True,
    })
    return state


core.LiveTrader._trade_idea = _trade_idea_v51  # type: ignore[method-assign]
core.LiveTrader.runtime_status = _runtime_status_v51  # type: ignore[method-assign]
integrity._trade_idea_v39 = _trade_idea_v51
lock._trade_idea_v28 = _trade_idea_v51
session_gate._trade_idea_v46 = _trade_idea_v51

from app.services import live_trader_management_learning_v52 as _management_learning_v52  # noqa: E402,F401
from app.services import live_trader_breakout_wording_v53 as _breakout_wording_v53  # noqa: E402,F401
from app.services import live_trader_breakout_language_boundary_v54 as _breakout_language_boundary_v54  # noqa: E402,F401
from app.services import live_trader_session_outlook_v55 as _live_trader_session_outlook_v55  # noqa: E402,F401
from app.services import live_trader_session_outlook_compat_v56 as _live_trader_session_outlook_compat_v56  # noqa: E402,F401
from app.services import live_trader_structure_readout_v57 as _live_trader_structure_readout_v57  # noqa: E402,F401
from app.services import live_trader_zone_retrace_specialist_v58 as _live_trader_zone_retrace_specialist_v58  # noqa: E402,F401
from app.services import live_trader_zone_retrace_audit_v60 as _live_trader_zone_retrace_audit_v60  # noqa: E402,F401
from app.services import live_trader_zone_ranking_v62 as _live_trader_zone_ranking_v62  # noqa: E402,F401
from app.services import live_trader_mtf_zones_v63 as _live_trader_mtf_zones_v63  # noqa: E402,F401
from app.services import live_trader_zone_retrace_integrity_v64 as _live_trader_zone_retrace_integrity_v64  # noqa: E402,F401
from app.services import live_trader_state_integrity_v65 as _live_trader_state_integrity_v65  # noqa: E402,F401
from app.services import live_trader_campaign_consensus_v66 as _live_trader_campaign_consensus_v66  # noqa: E402,F401
from app.services import live_trader_zone_retrace_evidence_contract_v67 as _live_trader_zone_retrace_evidence_contract_v67  # noqa: E402,F401
from app.services import live_trader_zone_retrace_live_policy_replay_v68 as _live_trader_zone_retrace_live_policy_replay_v68  # noqa: E402,F401
from app.services import live_trader_zone_retrace_replay_path_fix_v69 as _live_trader_zone_retrace_replay_path_fix_v69  # noqa: E402,F401
from app.services import live_trader_zone_retrace_replay_diagnostics_v70 as _live_trader_zone_retrace_replay_diagnostics_v70  # noqa: E402,F401
from app.services import live_trader_zone_retrace_current_policy_academy_v71 as _live_trader_zone_retrace_current_policy_academy_v71  # noqa: E402,F401
from app.services import live_trader_run_forever_compat_v72 as _live_trader_run_forever_compat_v72  # noqa: E402,F401
