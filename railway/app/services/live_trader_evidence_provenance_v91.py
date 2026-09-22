from __future__ import annotations

from typing import Any

from app.services import live_trader as core
from app.services import live_trader_audit_hardening_v26 as hardening
from app.services import live_trader_campaign_consensus_v66 as consensus
from app.services import live_trader_evidence_identity as evidence_id
from app.services import live_trader_execution_timing_v89 as timing
from app.services import live_trader_trade_lock_v28 as lock

VERSION = "eve-live-evidence-provenance-v91"
PUBLISHED_CAMPAIGN_LEARNING_VERSION = "eve-live-published-paper-campaign-v1"

_current_new_campaign = lock._new_campaign
_current_persist_campaign = lock._persist_campaign
_current_campaign_trade = lock._campaign_trade
_current_refresh_state = core.LiveTrader.refresh_state
_current_runtime_status = core.LiveTrader.runtime_status


def _published_identity(self: core.LiveTrader) -> dict[str, Any]:
    return evidence_id.production_identity(
        self.settings,
        learning_version=PUBLISHED_CAMPAIGN_LEARNING_VERSION,
        evaluation_stage="published_paper_campaign",
    )


def _forward_identity(self: core.LiveTrader) -> dict[str, Any]:
    return evidence_id.production_identity(
        self.settings,
        learning_version=hardening.LEARNING_NAMESPACE,
        evaluation_stage="production_forward_learning",
    )


def _new_campaign_v91(self: core.LiveTrader, trade: dict[str, Any], price: float) -> dict[str, Any]:
    campaign = dict(_current_new_campaign(self, trade, price))
    identity = _published_identity(self)
    campaign.update(evidence_id.row_columns(identity))
    campaign["evidence_identity"] = evidence_id.public_identity(identity)

    published = dict(campaign.get("published_trade") or {})
    campaign["published_trade"] = evidence_id.attach_trade(published, identity)
    self._live_campaign_dirty = True
    self._live_campaign_new_v28 = True
    return campaign


async def _persist_campaign_v91(self: core.LiveTrader, campaign: dict[str, Any]) -> dict[str, Any]:
    # Never retroactively pretend a legacy campaign belongs to the new
    # prospective cohort. Only campaigns created through v91 carry the marker.
    if str(campaign.get("evidence_identity_version") or "") == evidence_id.IDENTITY_VERSION:
        identity = _published_identity(self)
        if str(campaign.get("cohort_id") or "") != str(identity.get("cohort_id") or ""):
            raise RuntimeError(
                "Live Trader refused to persist a campaign under a different policy/scorer cohort than the one it was created with."
            )
        await evidence_id.ensure_registered(self.repo, identity)
    return await _current_persist_campaign(self, campaign)


def _campaign_trade_v91(campaign: dict[str, Any]) -> dict[str, Any]:
    trade = dict(_current_campaign_trade(campaign))
    identity = campaign.get("evidence_identity")
    if isinstance(identity, dict):
        trade["evidence_identity"] = dict(identity)
        trade["policy_id"] = campaign.get("policy_id")
        trade["scorer_id"] = campaign.get("scorer_id")
        trade["cohort_id"] = campaign.get("cohort_id")
        trade["evaluation_stage"] = campaign.get("evaluation_stage")
    else:
        trade["evidence_identity_status"] = "legacy_unattributed_campaign"
    return trade


async def _refresh_state_v91(self: core.LiveTrader, *, force_rows: bool = False) -> dict[str, Any]:
    state = dict(await _current_refresh_state(self, force_rows=force_rows))
    forward = _forward_identity(self)
    published = _published_identity(self)
    state["evidence_provenance"] = {
        "version": VERSION,
        "identity_version": evidence_id.IDENTITY_VERSION,
        "cohort_protocol_version": evidence_id.COHORT_PROTOCOL_VERSION,
        "production_forward_learning": evidence_id.public_identity(forward),
        "published_paper_campaign": evidence_id.public_identity(published),
        "legacy_rows_may_remain_unattributed": True,
        "policy_or_scorer_change_starts_new_cohort": True,
        "old_cohorts_deleted_or_reset": False,
    }
    self._latest_state = state
    return state


def _runtime_status_v91(self: core.LiveTrader) -> dict[str, Any]:
    status = dict(_current_runtime_status(self))
    forward = _forward_identity(self)
    published = _published_identity(self)
    status.update(
        {
            "evidence_provenance_version": VERSION,
            "evidence_identity_version": evidence_id.IDENTITY_VERSION,
            "cohort_protocol_version": evidence_id.COHORT_PROTOCOL_VERSION,
            "production_policy_id": forward.get("policy_id"),
            "production_scorer_id": forward.get("scorer_id"),
            "production_forward_cohort_id": forward.get("cohort_id"),
            "published_paper_cohort_id": published.get("cohort_id"),
            "policy_or_scorer_change_forces_new_cohort": True,
            "legacy_evidence_never_auto_relabelled": True,
        }
    )
    return status


lock._new_campaign = _new_campaign_v91
lock._persist_campaign = _persist_campaign_v91
lock._campaign_trade = _campaign_trade_v91
consensus._persist_campaign_v66 = _persist_campaign_v91

core.LiveTrader.refresh_state = _refresh_state_v91  # type: ignore[method-assign]
core.LiveTrader.runtime_status = _runtime_status_v91  # type: ignore[method-assign]

# Preserve timing module compatibility aliases so downstream calls resolve the
# newest provenance-aware persistence path.
timing._current_campaign_trade = _campaign_trade_v91
