from __future__ import annotations

from typing import Any

from app.services import backtest as legacy
from app.services import backtest_v3 as research
from app.services import intelligence as v1

EVIDENCE_LONG = "evidence_long"
EVIDENCE_SHORT = "evidence_short"

_BASE_DIRECTION = research.candidate_direction


def candidate_direction(row: dict[str, Any], rules: dict[str, Any]) -> int:
    rule = str((rules.get("entry") or {}).get("direction_rule") or "")
    if rule == EVIDENCE_LONG:
        return 1
    if rule == EVIDENCE_SHORT:
        return -1
    return _BASE_DIRECTION(row, rules)


def activate() -> None:
    """Install explicit anomaly direction on all shared Python research paths.

    This module is imported by the evidence-seeding director before M1 replay is
    imported by the orchestrator, so coarse research, selection and M1 intent
    generation bind the same deterministic direction semantics.
    """
    if getattr(research, "_EVE_EVIDENCE_DIRECTION_ACTIVE", False):
        return
    research.candidate_direction = candidate_direction
    legacy.candidate_direction = candidate_direction
    v1.candidate_direction = candidate_direction
    research._EVE_EVIDENCE_DIRECTION_ACTIVE = True


activate()
