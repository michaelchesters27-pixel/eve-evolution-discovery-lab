from __future__ import annotations

import random
from typing import Any

from app.services import backtest as legacy
from app.services import backtest_v3 as research
from app.services import intelligence as v1
from app.services import intelligence_v2 as scientist

MTF_REASONING_VERSION = "eve-mtf-relationship-reasoning-v1"

MTF_CONDITION_TYPES = {
    "mtf_m1_path_efficiency_min",
    "mtf_m1_direction_changes_max",
    "mtf_m1_direction_matches_m5",
    "mtf_m1_direction_opposes_m5",
    "mtf_m1_last_minute_matches_m5",
    "mtf_m1_last_minute_opposes_m5",
    "mtf_m15_matches_m5",
    "mtf_m15_opposes_m5",
    "mtf_m30_matches_m5",
    "mtf_m30_opposes_m5",
    "mtf_h1_matches_m5",
    "mtf_h1_opposes_m5",
    "mtf_h4_matches_m5",
    "mtf_h4_opposes_m5",
    "mtf_d1_matches_m5",
    "mtf_d1_opposes_m5",
    "mtf_m15_m30_agree",
    "mtf_m15_m30_agree_m5_opposes",
    "mtf_h1_h4_agree",
    "mtf_h1_h4_agree_m5_opposes",
    "mtf_h4_d1_agree",
    "mtf_h1_h4_d1_agree",
    "mtf_context_alignment_abs_min",
    "mtf_context_alignment_matches_m5",
    "mtf_context_alignment_opposes_m5",
}

MTF_DIRECTION_RULES = (
    "mtf_htf_consensus_direction",
    "mtf_m15_m30_consensus_direction",
    "mtf_h1_h4_consensus_direction",
    "mtf_h1_direction",
    "mtf_h4_direction",
    "mtf_d1_direction",
)

MTF_POOL: tuple[dict[str, Any], ...] = (
    {"type": "mtf_m1_path_efficiency_min", "min": 0.55},
    {"type": "mtf_m1_path_efficiency_min", "min": 0.75},
    {"type": "mtf_m1_path_efficiency_min", "min": 0.90},
    {"type": "mtf_m1_direction_changes_max", "max": 0},
    {"type": "mtf_m1_direction_changes_max", "max": 1},
    {"type": "mtf_m1_direction_changes_max", "max": 2},
    {"type": "mtf_m1_direction_matches_m5"},
    {"type": "mtf_m1_direction_opposes_m5"},
    {"type": "mtf_m1_last_minute_matches_m5"},
    {"type": "mtf_m1_last_minute_opposes_m5"},
    {"type": "mtf_m15_matches_m5"},
    {"type": "mtf_m15_opposes_m5"},
    {"type": "mtf_m30_matches_m5"},
    {"type": "mtf_m30_opposes_m5"},
    {"type": "mtf_h1_matches_m5"},
    {"type": "mtf_h1_opposes_m5"},
    {"type": "mtf_h4_matches_m5"},
    {"type": "mtf_h4_opposes_m5"},
    {"type": "mtf_d1_matches_m5"},
    {"type": "mtf_d1_opposes_m5"},
    {"type": "mtf_m15_m30_agree"},
    {"type": "mtf_m15_m30_agree_m5_opposes"},
    {"type": "mtf_h1_h4_agree"},
    {"type": "mtf_h1_h4_agree_m5_opposes"},
    {"type": "mtf_h4_d1_agree"},
    {"type": "mtf_h1_h4_d1_agree"},
    {"type": "mtf_context_alignment_abs_min", "min": 2},
    {"type": "mtf_context_alignment_abs_min", "min": 3},
    {"type": "mtf_context_alignment_abs_min", "min": 4},
    {"type": "mtf_context_alignment_abs_min", "min": 5},
    {"type": "mtf_context_alignment_matches_m5"},
    {"type": "mtf_context_alignment_opposes_m5"},
)

MTF_CONFLICTS: dict[str, set[str]] = {
    "mtf_m1_direction_matches_m5": {"mtf_m1_direction_opposes_m5"},
    "mtf_m1_direction_opposes_m5": {"mtf_m1_direction_matches_m5"},
    "mtf_m1_last_minute_matches_m5": {"mtf_m1_last_minute_opposes_m5"},
    "mtf_m1_last_minute_opposes_m5": {"mtf_m1_last_minute_matches_m5"},
    "mtf_m15_matches_m5": {"mtf_m15_opposes_m5", "mtf_m15_m30_agree_m5_opposes"},
    "mtf_m15_opposes_m5": {"mtf_m15_matches_m5"},
    "mtf_m30_matches_m5": {"mtf_m30_opposes_m5", "mtf_m15_m30_agree_m5_opposes"},
    "mtf_m30_opposes_m5": {"mtf_m30_matches_m5"},
    "mtf_h1_matches_m5": {"mtf_h1_opposes_m5", "mtf_h1_h4_agree_m5_opposes"},
    "mtf_h1_opposes_m5": {"mtf_h1_matches_m5"},
    "mtf_h4_matches_m5": {"mtf_h4_opposes_m5", "mtf_h1_h4_agree_m5_opposes"},
    "mtf_h4_opposes_m5": {"mtf_h4_matches_m5"},
    "mtf_d1_matches_m5": {"mtf_d1_opposes_m5"},
    "mtf_d1_opposes_m5": {"mtf_d1_matches_m5"},
    "mtf_context_alignment_matches_m5": {"mtf_context_alignment_opposes_m5"},
    "mtf_context_alignment_opposes_m5": {"mtf_context_alignment_matches_m5"},
    "mtf_m15_m30_agree_m5_opposes": {"mtf_m15_matches_m5", "mtf_m30_matches_m5"},
    "mtf_h1_h4_agree_m5_opposes": {"mtf_h1_matches_m5", "mtf_h4_matches_m5"},
}


def _direction(row: dict[str, Any], field: str) -> int:
    return legacy.sign(row.get(field))


def _same_nonzero(*values: int) -> bool:
    return bool(values) and values[0] != 0 and all(value == values[0] for value in values)


def _opposes(left: int, right: int) -> bool:
    return left != 0 and right != 0 and left == -right


def _m5(row: dict[str, Any]) -> int:
    return _direction(row, "direction")


def recipe_condition_matches(row: dict[str, Any], condition: dict[str, Any]) -> bool:
    kind = str(condition.get("type") or "")
    if kind not in MTF_CONDITION_TYPES:
        return _ORIGINAL_RECIPE(row, condition)

    m5 = _m5(row)
    m1 = _direction(row, "mtf_m1_direction")
    m1_last = _direction(row, "mtf_m1_last_direction")
    m15 = _direction(row, "mtf_m15_direction")
    m30 = _direction(row, "mtf_m30_direction")
    h1 = _direction(row, "mtf_h1_direction")
    h4 = _direction(row, "mtf_h4_direction")
    d1 = _direction(row, "mtf_d1_direction")
    htf = _direction(row, "mtf_htf_alignment_score")

    if kind == "mtf_m1_path_efficiency_min":
        return bool(row.get("mtf_m1_available")) and legacy.number(row.get("mtf_m1_path_efficiency")) >= legacy.number(condition.get("min"), 0.75)
    if kind == "mtf_m1_direction_changes_max":
        return bool(row.get("mtf_m1_available")) and legacy.number(row.get("mtf_m1_direction_changes"), 99) <= legacy.number(condition.get("max"), 1)
    if kind == "mtf_m1_direction_matches_m5":
        return bool(row.get("mtf_m1_available")) and _same_nonzero(m1, m5)
    if kind == "mtf_m1_direction_opposes_m5":
        return bool(row.get("mtf_m1_available")) and _opposes(m1, m5)
    if kind == "mtf_m1_last_minute_matches_m5":
        return bool(row.get("mtf_m1_available")) and _same_nonzero(m1_last, m5)
    if kind == "mtf_m1_last_minute_opposes_m5":
        return bool(row.get("mtf_m1_available")) and _opposes(m1_last, m5)
    if kind == "mtf_m15_matches_m5":
        return _same_nonzero(m15, m5)
    if kind == "mtf_m15_opposes_m5":
        return _opposes(m15, m5)
    if kind == "mtf_m30_matches_m5":
        return _same_nonzero(m30, m5)
    if kind == "mtf_m30_opposes_m5":
        return _opposes(m30, m5)
    if kind == "mtf_h1_matches_m5":
        return _same_nonzero(h1, m5)
    if kind == "mtf_h1_opposes_m5":
        return _opposes(h1, m5)
    if kind == "mtf_h4_matches_m5":
        return _same_nonzero(h4, m5)
    if kind == "mtf_h4_opposes_m5":
        return _opposes(h4, m5)
    if kind == "mtf_d1_matches_m5":
        return _same_nonzero(d1, m5)
    if kind == "mtf_d1_opposes_m5":
        return _opposes(d1, m5)
    if kind == "mtf_m15_m30_agree":
        return _same_nonzero(m15, m30)
    if kind == "mtf_m15_m30_agree_m5_opposes":
        return _same_nonzero(m15, m30) and _opposes(m5, m15)
    if kind == "mtf_h1_h4_agree":
        return _same_nonzero(h1, h4)
    if kind == "mtf_h1_h4_agree_m5_opposes":
        return _same_nonzero(h1, h4) and _opposes(m5, h1)
    if kind == "mtf_h4_d1_agree":
        return _same_nonzero(h4, d1)
    if kind == "mtf_h1_h4_d1_agree":
        return _same_nonzero(h1, h4, d1)
    if kind == "mtf_context_alignment_abs_min":
        return abs(int(legacy.number(row.get("mtf_htf_alignment_score")))) >= int(legacy.number(condition.get("min"), 3))
    if kind == "mtf_context_alignment_matches_m5":
        return _same_nonzero(htf, m5)
    if kind == "mtf_context_alignment_opposes_m5":
        return _opposes(htf, m5)
    return False


def candidate_direction(row: dict[str, Any], rules: dict[str, Any]) -> int:
    rule = str((rules.get("entry") or {}).get("direction_rule") or "current_direction")
    if rule == "mtf_htf_consensus_direction":
        return _direction(row, "mtf_htf_alignment_score")
    if rule == "mtf_h1_direction":
        return _direction(row, "mtf_h1_direction")
    if rule == "mtf_h4_direction":
        return _direction(row, "mtf_h4_direction")
    if rule == "mtf_d1_direction":
        return _direction(row, "mtf_d1_direction")
    if rule == "mtf_m15_m30_consensus_direction":
        m15 = _direction(row, "mtf_m15_direction")
        m30 = _direction(row, "mtf_m30_direction")
        return m15 if _same_nonzero(m15, m30) else 0
    if rule == "mtf_h1_h4_consensus_direction":
        h1 = _direction(row, "mtf_h1_direction")
        h4 = _direction(row, "mtf_h4_direction")
        return h1 if _same_nonzero(h1, h4) else 0
    return _ORIGINAL_DIRECTION(row, rules)


def has_advanced_conditions(rules: dict[str, Any]) -> bool:
    entry = dict(rules.get("entry") or {})
    direction_rule = str(entry.get("direction_rule") or "")
    if direction_rule in MTF_DIRECTION_RULES:
        return True
    if any(
        str(item.get("type") or "") in MTF_CONDITION_TYPES
        for item in entry.get("conditions") or []
        if isinstance(item, dict)
    ):
        return True
    return _ORIGINAL_HAS_ADVANCED(rules)


def _compatible(selected: list[dict[str, Any]], candidate: dict[str, Any]) -> bool:
    kind = str(candidate.get("type") or "")
    selected_types = {str(item.get("type") or "") for item in selected}
    if kind in selected_types:
        return False
    blocked = (
        set(v1.CONDITION_CONFLICTS.get(kind, set()))
        | set(scientist.PAIR_CONFLICTS.get(kind, set()))
        | set(MTF_CONFLICTS.get(kind, set()))
    )
    for selected_kind in selected_types:
        blocked |= set(MTF_CONFLICTS.get(selected_kind, set()))
    return not any(item in blocked for item in selected_types)


def proposal_rules(
    rng: random.Random,
    memory: dict[str, float],
    *,
    symbol: str,
    timeframe: str,
    snapshot_interval: str,
    source_interval: str,
) -> dict[str, Any]:
    rules = v1.proposal_rules(
        rng,
        memory,
        symbol=symbol,
        timeframe=timeframe,
        snapshot_interval=snapshot_interval,
        source_interval=source_interval,
    )
    rules["engine_version"] = scientist.INTELLIGENCE_VERSION
    use_mtf = str(snapshot_interval).lower() == "5min"
    rules["market"]["research_source"] = (
        "causal_structure_and_multitimeframe_relationship_mining"
        if use_mtf
        else "causal_market_structure_and_state_mining"
    )
    if use_mtf:
        rules["market"]["mtf_reasoning_version"] = MTF_REASONING_VERSION

    target_count = rng.choices([2, 3, 4, 5], weights=[24, 37, 29, 10], k=1)[0]
    combined_pool = [dict(item) for item in v1.CONDITION_POOL] + [dict(item) for item in scientist.STRUCTURE_POOL]
    if use_mtf:
        combined_pool.extend(dict(item) for item in MTF_POOL)

    selected: list[dict[str, Any]] = []
    attempts = 0
    while len(selected) < target_count and attempts < 180:
        attempts += 1
        available = [item for item in combined_pool if _compatible(selected, item)]
        if not available:
            break
        weights: list[float] = []
        for item in available:
            kind = str(item.get("type") or "")
            weight = v1.memory_weight(memory, v1.condition_key(item))
            if kind in MTF_CONDITION_TYPES:
                weight *= 1.60
            elif kind in research.STRUCTURE_CONDITION_TYPES:
                weight *= 1.35
            weights.append(weight)
        selected.append(dict(v1.weighted_choice(rng, available, weights)))

    base_directions = list(scientist.DIRECTION_RULES)
    direction_values = base_directions + (list(MTF_DIRECTION_RULES) if use_mtf else [])
    direction_weights = [v1.memory_weight(memory, f"direction:{item}") for item in direction_values]
    for index, item in enumerate(direction_values):
        if item in MTF_DIRECTION_RULES:
            direction_weights[index] *= 1.45
        elif item in {"structure_direction", "three_bar_direction"}:
            direction_weights[index] *= 1.25

    rules["entry"] = {
        "direction_rule": str(v1.weighted_choice(rng, direction_values, direction_weights)),
        "condition_mode": "all",
        "conditions": selected,
    }
    return rules


def _runtime_status(self: Any) -> dict[str, Any]:
    status = _ORIGINAL_RUNTIME_STATUS(self)
    capabilities = list(status.get("capabilities") or [])
    for item in (
        "m1_microstructure_relationships",
        "m15_m30_relationships",
        "h1_h4_d1_relationships",
        "cross_timeframe_pullback_detection",
        "higher_timeframe_consensus_direction",
        "multi_timeframe_hypothesis_generation",
    ):
        if item not in capabilities:
            capabilities.append(item)
    status["capabilities"] = capabilities
    status["mtf_reasoning_version"] = MTF_REASONING_VERSION
    status["mtf_condition_types"] = len(MTF_CONDITION_TYPES)
    status["mtf_direction_rules"] = list(MTF_DIRECTION_RULES)
    return status


def activate() -> None:
    if getattr(scientist, "_EVE_MTF_REASONING_ACTIVE", False):
        return

    # Every historical evaluation, selection test and live-watch comparison must
    # use the same relationship definitions.
    research.recipe_condition_matches = recipe_condition_matches
    research.candidate_direction = candidate_direction
    research.has_structure_conditions = has_advanced_conditions
    research.MTF_CONDITION_TYPES = set(MTF_CONDITION_TYPES)
    research.STRUCTURE_CONDITION_TYPES = set(research.STRUCTURE_CONDITION_TYPES) | set(MTF_CONDITION_TYPES)

    legacy.recipe_condition_matches = recipe_condition_matches
    legacy.candidate_direction = candidate_direction
    v1.recipe_condition_matches = recipe_condition_matches
    v1.candidate_direction = candidate_direction

    scientist._proposal_rules = proposal_rules
    scientist.IntelligenceDirector.runtime_status = _runtime_status
    scientist._EVE_MTF_REASONING_ACTIVE = True


_ORIGINAL_RECIPE = research.recipe_condition_matches
_ORIGINAL_DIRECTION = research.candidate_direction
_ORIGINAL_HAS_ADVANCED = research.has_structure_conditions
_ORIGINAL_RUNTIME_STATUS = scientist.IntelligenceDirector.runtime_status

activate()
