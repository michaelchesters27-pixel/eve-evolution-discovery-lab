from __future__ import annotations

from typing import Any

from app.services import orchestrator as base

MT5_EVIDENCE_PARITY_GATE = "advanced_rule_parity_required"
_ORIGINAL_GENERATE_PENDING_PACKAGE = base.DiscoveryOrchestrator.generate_pending_package


def requires_parity_proof(frozen: dict[str, Any]) -> bool:
    rules = dict(frozen.get("rules") or {})
    market = dict(rules.get("market") or {})
    required = str(market.get("mt5_export_gate") or "") == MT5_EVIDENCE_PARITY_GATE
    passed = bool(market.get("advanced_rule_parity_passed"))
    return required and not passed


async def guarded_generate_pending_package(self: Any) -> bool:
    """Quarantine evidence-seeded survivors before package generation.

    The research survivor remains frozen and auditable. Only MT5 packaging is
    blocked until an explicit advanced-rule parity proof releases it.
    """
    if not self.settings.mt5_generation_enabled:
        return False

    pending = await self.repo.frozen_without_package(20)
    blocked = 0
    for frozen in pending:
        if not requires_parity_proof(frozen):
            continue
        frozen_id = str(frozen.get("id") or "")
        if not frozen_id:
            continue
        reason = (
            "Evidence-seeded research survivor is frozen, but MT5 export is blocked until "
            "the advanced Python-to-MT5 rule parity gate is explicitly passed."
        )
        await self.repo.update_frozen_profile(
            frozen_id,
            {
                "package_status": "blocked_parity",
                "profile_status": "complete",
                "profile_reason": reason,
            },
        )
        await self.repo.event(
            "warning",
            "mt5_parity_gate",
            f"MT5 package blocked for {frozen.get('name')}: advanced-rule parity proof required.",
            {
                "frozen_id": frozen_id,
                "gate": MT5_EVIDENCE_PARITY_GATE,
                "evidence_seed_version": ((frozen.get("rules") or {}).get("market") or {}).get("evidence_seed_version"),
                "automatic_trading": "not_permitted",
            },
        )
        blocked += 1

    # Quarantined rows are no longer `pending`, so the normal generator can now
    # safely pick the next ordinary survivor without being starved by this gate.
    if pending and blocked == len(pending):
        return False
    return await _ORIGINAL_GENERATE_PENDING_PACKAGE(self)


def activate() -> None:
    if getattr(base.DiscoveryOrchestrator, "_EVE_MT5_EVIDENCE_GATE_ACTIVE", False):
        return
    base.DiscoveryOrchestrator.generate_pending_package = guarded_generate_pending_package
    base.DiscoveryOrchestrator._EVE_MT5_EVIDENCE_GATE_ACTIVE = True


activate()
