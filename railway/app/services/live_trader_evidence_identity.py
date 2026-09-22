from __future__ import annotations

import hashlib
import json
from typing import Any

IDENTITY_VERSION = "eve-live-evidence-identity-v1"
COHORT_PROTOCOL_VERSION = "eve-live-prospective-cohort-v1"
PRODUCTION_POLICY_CONTRACT_VERSION = "eve-live-production-policy-contract-v1"


def _canonical(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True, default=str)


def _hash(value: Any) -> str:
    return hashlib.sha256(_canonical(value).encode("utf-8")).hexdigest()


def _id(prefix: str, value: Any) -> str:
    return f"{prefix}_{_hash(value)[:24]}"


def production_policy_definition() -> dict[str, Any]:
    # Imports are deliberately local. This helper is used by modules that are
    # themselves part of the Live Trader wrapper chain, so eager imports here
    # would create a circular bootstrap dependency.
    from app.services import live_trader_clear_bias_gate_v45 as clear_gate
    from app.services import live_trader_london_session_gate_v46 as session_gate
    from app.services import live_trader_trade_lock_v28 as lock
    from app.services import live_trader_zone_retrace_evidence_contract_v67 as evidence
    from app.services import live_trader_zone_retrace_historical_proxy_integrity_v75 as proxy
    from app.services import live_trader_zone_target_guard_v49 as target_guard
    from app.services import live_trader_zone_target_runtime_v51 as target_runtime

    return {
        "contract_version": PRODUCTION_POLICY_CONTRACT_VERSION,
        "policy_kind": "production_manual_paper",
        "symbol": "XAU/USD",
        "manual_only": True,
        "automatic_order_placement": False,
        "clear_bias_gate": {
            "version": clear_gate.GATE_VERSION,
            "minimum_confidence": clear_gate.MIN_CLEAR_CONFIDENCE,
            "critical_timeframes": list(clear_gate.CRITICAL_TIMEFRAMES),
        },
        "publication_session": {
            "version": session_gate.SESSION_GATE_VERSION,
            "timezone": "Europe/London",
            "start": session_gate.SESSION_START.strftime("%H:%M"),
            "end": session_gate.SESSION_END.strftime("%H:%M"),
            "end_exclusive": True,
            "weekdays_only": True,
        },
        "trade_lock": {
            "version": lock.CAMPAIGN_VERSION,
            "pending_expiry_minutes": lock.PENDING_EXPIRY_MINUTES,
            "one_trade_at_a_time": True,
        },
        "target_policy": {
            "guard_version": target_guard.GUARD_VERSION,
            "policy_version": target_guard.TARGET_POLICY_VERSION,
            "max_target_r": target_guard.MAX_TARGET_R,
            "max_pending_age_minutes": target_guard.MAX_PENDING_AGE_MINUTES,
            "runtime_version": target_runtime.RUNTIME_VERSION,
        },
        "zone_retrace_contract": {
            "version": evidence.EVIDENCE_CONTRACT_VERSION,
            "live_entry_policy": "market_after_zone_retrace_and_m5_m15_confirmation",
            "live_target_cap_r": evidence.LIVE_TARGET_CAP_R,
            "historical_proxy_integrity_version": proxy.INTEGRITY_VERSION,
            "forward_live_campaign_validation_required": True,
        },
    }


def historical_archive_policy_definition() -> dict[str, Any]:
    return {
        "contract_version": "eve-live-historical-archive-mixed-policy-v1",
        "policy_kind": "historical_education_legacy_mixed",
        "scope": (
            "Existing Historical Academy trade ideas were generated across earlier Live Trader policy revisions. "
            "This identity labels that mixed archive honestly; it is not a claim that those rows share one frozen production policy."
        ),
        "prospective_validation_eligible": False,
    }


def current_scorer_definition(settings: Any) -> dict[str, Any]:
    from app.services import live_trader_audit_hardening_v26 as hardening
    from app.services import live_trader_execution_cost_model as cost_model
    from app.services import live_trader_execution_integrity_v39 as integrity

    return {
        "scorer_contract_version": "eve-live-scorer-contract-v1",
        "execution_schema": str(integrity.EXECUTION_SCHEMA),
        "historical_regrader_version": str(integrity.REGRADER_VERSION),
        "timing_contract_version": str(hardening.TIMING_CONTRACT_VERSION),
        "outcome_schema": str(hardening.OUTCOME_SCHEMA),
        "cost_model_version": str(cost_model.COST_MODEL_VERSION),
        "cost_profile": cost_model.profile_from_settings(settings),
        "learning_horizon_minutes": int(getattr(settings, "live_trader_learning_horizon_minutes", 60)),
        "pre_entry_invalidation_enforced": True,
        "same_bar_ambiguity_policy": "adverse_entry_then_stop_and_no_prefill_target_credit",
        "gross_r_preserved": True,
        "qualification_uses_net_r": True,
    }


def build_identity(
    *,
    policy_kind: str,
    policy_key: str,
    policy_definition: dict[str, Any],
    settings: Any,
    learning_version: str,
    evaluation_stage: str,
    scorer_definition: dict[str, Any] | None = None,
    evaluation_protocol: dict[str, Any] | None = None,
) -> dict[str, Any]:
    policy_payload = {
        "identity_version": IDENTITY_VERSION,
        "policy_kind": str(policy_kind),
        "policy_key": str(policy_key),
        "definition": dict(policy_definition),
    }
    policy_hash = _hash(policy_payload)
    policy_id = f"pol_{policy_hash[:24]}"

    scorer_definition = dict(scorer_definition or current_scorer_definition(settings))
    scorer_payload = {
        "identity_version": IDENTITY_VERSION,
        "definition": scorer_definition,
    }
    scorer_hash = _hash(scorer_payload)
    scorer_id = f"scr_{scorer_hash[:24]}"

    protocol = dict(evaluation_protocol or {})
    cohort_definition = {
        "identity_version": IDENTITY_VERSION,
        "cohort_protocol_version": COHORT_PROTOCOL_VERSION,
        "policy_id": policy_id,
        "scorer_id": scorer_id,
        "learning_version": str(learning_version),
        "evaluation_stage": str(evaluation_stage),
    }
    # Preserve the exact v91 cohort identity when no evaluation protocol is
    # supplied. Only qualification-aware stages should start a new cohort.
    if protocol:
        cohort_definition.update(
            {
                "evaluation_protocol_version": protocol.get("version"),
                "evaluation_protocol_hash": _hash(protocol),
                "evaluation_protocol": protocol,
            }
        )
    cohort_hash = _hash(cohort_definition)
    cohort_id = f"coh_{cohort_hash[:24]}"

    return {
        "identity_version": IDENTITY_VERSION,
        "policy_id": policy_id,
        "policy_kind": str(policy_kind),
        "policy_key": str(policy_key),
        "policy_definition_hash": policy_hash,
        "policy_definition": dict(policy_definition),
        "scorer_id": scorer_id,
        "scorer_definition_hash": scorer_hash,
        "scorer_definition": scorer_definition,
        "cohort_id": cohort_id,
        "cohort_definition_hash": cohort_hash,
        "cohort_definition": cohort_definition,
        "cohort_protocol_version": COHORT_PROTOCOL_VERSION,
        "evaluation_protocol_version": cohort_definition.get("evaluation_protocol_version"),
        "evaluation_protocol_hash": cohort_definition.get("evaluation_protocol_hash"),
        "learning_version": str(learning_version),
        "evaluation_stage": str(evaluation_stage),
    }


def row_columns(identity: dict[str, Any]) -> dict[str, Any]:
    return {
        "evidence_identity_version": identity.get("identity_version"),
        "policy_id": identity.get("policy_id"),
        "scorer_id": identity.get("scorer_id"),
        "cohort_id": identity.get("cohort_id"),
        "evaluation_stage": identity.get("evaluation_stage"),
    }


def public_identity(identity: dict[str, Any]) -> dict[str, Any]:
    return {
        **row_columns(identity),
        "policy_kind": identity.get("policy_kind"),
        "policy_key": identity.get("policy_key"),
        "policy_definition_hash": identity.get("policy_definition_hash"),
        "scorer_definition_hash": identity.get("scorer_definition_hash"),
        "cohort_definition_hash": identity.get("cohort_definition_hash"),
        "cohort_protocol_version": identity.get("cohort_protocol_version"),
        "evaluation_protocol_version": identity.get("evaluation_protocol_version"),
        "evaluation_protocol_hash": identity.get("evaluation_protocol_hash"),
    }


def attach_trade(trade: dict[str, Any], identity: dict[str, Any]) -> dict[str, Any]:
    result = dict(trade or {})
    result["evidence_identity"] = public_identity(identity)
    return result


async def ensure_registered(repo: Any, identity: dict[str, Any]) -> None:
    await repo.client.rpc(
        "register_live_trader_evidence_identity",
        {
            "p_identity_version": identity["identity_version"],
            "p_policy_id": identity["policy_id"],
            "p_policy_kind": identity["policy_kind"],
            "p_policy_key": identity["policy_key"],
            "p_policy_definition_hash": identity["policy_definition_hash"],
            "p_policy_definition": identity["policy_definition"],
            "p_scorer_id": identity["scorer_id"],
            "p_scorer_definition_hash": identity["scorer_definition_hash"],
            "p_scorer_definition": identity["scorer_definition"],
            "p_cohort_id": identity["cohort_id"],
            "p_cohort_definition_hash": identity["cohort_definition_hash"],
            "p_cohort_definition": identity["cohort_definition"],
            "p_cohort_protocol_version": identity["cohort_protocol_version"],
            "p_learning_version": identity["learning_version"],
            "p_evaluation_stage": identity["evaluation_stage"],
        },
    )


def published_campaign_scorer_definition(settings: Any) -> dict[str, Any]:
    from app.services import live_trader_audit_hardening_v26 as hardening
    from app.services import live_trader_execution_cost_model as cost_model
    from app.services import live_trader_trade_lock_v28 as lock

    return {
        "scorer_contract_version": "eve-live-published-campaign-scorer-v1",
        "campaign_version": lock.CAMPAIGN_VERSION,
        "timing_contract_version": hardening.TIMING_CONTRACT_VERSION,
        "path_source": "fresh_live_websocket_price_updates",
        "pending_trigger_rule": "entry threshold observed after durable publication and manual-delay activation",
        "active_exit_rule": "first sampled live price observed at or beyond published stop or target",
        "intraminute_tick_complete": False,
        "cost_model_version": cost_model.COST_MODEL_VERSION,
        "cost_profile": cost_model.profile_from_settings(settings),
        "gross_r_preserved": True,
        "net_r_recorded": True,
        "actual_mt5_fill": False,
        "manual_fill_ledger_separate": True,
    }


def published_campaign_identity(
    settings: Any,
    *,
    learning_version: str,
    evaluation_stage: str = "published_paper_campaign",
) -> dict[str, Any]:
    from app.services import live_trader_evidence_quality_v92 as quality

    return build_identity(
        policy_kind="production_manual_paper",
        policy_key=PRODUCTION_POLICY_CONTRACT_VERSION,
        policy_definition=production_policy_definition(),
        settings=settings,
        learning_version=learning_version,
        evaluation_stage=evaluation_stage,
        scorer_definition=published_campaign_scorer_definition(settings),
        evaluation_protocol=quality.published_paper_protocol_definition(),
    )


def production_identity(settings: Any, *, learning_version: str, evaluation_stage: str) -> dict[str, Any]:
    return build_identity(
        policy_kind="production_manual_paper",
        policy_key=PRODUCTION_POLICY_CONTRACT_VERSION,
        policy_definition=production_policy_definition(),
        settings=settings,
        learning_version=learning_version,
        evaluation_stage=evaluation_stage,
    )


def historical_regrade_identity(settings: Any) -> dict[str, Any]:
    return build_identity(
        policy_kind="historical_education_legacy_mixed",
        policy_key="historical-academy-legacy-mixed",
        policy_definition=historical_archive_policy_definition(),
        settings=settings,
        learning_version="live_trader_historical_learning",
        evaluation_stage="historical_education_regrade",
    )
