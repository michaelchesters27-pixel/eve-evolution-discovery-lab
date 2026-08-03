from __future__ import annotations

import hashlib
import json
import random
from dataclasses import dataclass
from typing import Any, Iterable

ENGINE_VERSION = "eve-discovery-composer-v2"

LEGACY_FAMILIES = (
    "momentum_continuation",
    "alignment_continuation",
    "pullback_continuation",
    "volatility_breakout",
    "mean_reversion",
    "candle_reversal",
)
FAMILIES = (*LEGACY_FAMILIES, "composed_signal")
SESSIONS = ("asia", "london", "new_york", "off_session")
HOURS = tuple(range(0, 24))
WEEKDAY_PRESETS = (
    (1, 2, 3, 4, 5),
    (1,), (2,), (3,), (4,), (5,),
    (1, 2, 3), (3, 4, 5),
)
MONTH_PRESETS = (
    tuple(range(1, 13)),
    (1, 2, 3), (4, 5, 6), (7, 8, 9), (10, 11, 12),
    (1,), (2,), (3,), (4,), (5,), (6,), (7,), (8,), (9,), (10,), (11,), (12,),
)
STOP_GRID = (0.50, 0.65, 0.75, 0.90, 1.00, 1.15, 1.25, 1.50, 1.75, 2.00)
TARGET_GRID = (0.75, 1.00, 1.25, 1.50, 1.75, 2.00, 2.50, 3.00, 3.50, 4.00)
HORIZONS = (15, 60, 240)
COOLDOWNS = (5, 10, 15, 30, 45, 60, 90, 120, 240)
DIRECTION_RULES = (
    "current_direction",
    "alignment_direction",
    "trend_direction",
    "reverse_current",
    "wick_reversal",
)

CONDITION_TYPES = (
    "direction_matches_trend12",
    "direction_opposes_trend12",
    "alignment_abs_min",
    "alignment_matches_direction",
    "alignment_opposes_direction",
    "return_3_abs_min",
    "return_3_matches_direction",
    "impulse_1_vs_3",
    "close_location_extreme",
    "wick_body_ratio_min",
    "trend12_trend48_agree",
)
CONDITION_CONFLICTS = {
    "direction_matches_trend12": {"direction_opposes_trend12"},
    "direction_opposes_trend12": {"direction_matches_trend12"},
    "alignment_matches_direction": {"alignment_opposes_direction"},
    "alignment_opposes_direction": {"alignment_matches_direction"},
}


def canonical(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)


def strategy_hash(rules: dict[str, Any]) -> str:
    return hashlib.sha256(canonical(rules).encode()).hexdigest()


def weighted_choice(rng: random.Random, values: Iterable[str], weights: dict[str, float] | None = None) -> str:
    items = list(values)
    if not weights:
        return rng.choice(items)
    vector = [max(0.05, 1.0 + float(weights.get(item, 0.0))) for item in items]
    return rng.choices(items, weights=vector, k=1)[0]


def family_defaults(family: str) -> dict[str, Any]:
    defaults = {
        "momentum_continuation": {"direction_rule": "current_direction", "trend_band": "same_as_direction"},
        "alignment_continuation": {"direction_rule": "alignment_direction", "min_alignment": 1},
        "pullback_continuation": {"direction_rule": "trend_direction", "pullback_required": True},
        "volatility_breakout": {"direction_rule": "current_direction", "compression_band": "compressed"},
        "mean_reversion": {"direction_rule": "reverse_current", "close_location_extreme": True},
        "candle_reversal": {"direction_rule": "wick_reversal", "wick_ratio_min": 1.5},
    }
    return dict(defaults[family])


def _schedule(rng: random.Random, everyday_bias: float) -> dict[str, Any]:
    everyday = rng.random() < everyday_bias
    weekdays = (1, 2, 3, 4, 5) if everyday else rng.choice(WEEKDAY_PRESETS)
    all_months = rng.random() < max(0.70, everyday_bias)
    months = tuple(range(1, 13)) if all_months else rng.choice(MONTH_PRESETS)

    schedule_kind = rng.choices(
        ["all_day", "session", "hour_window", "single_hour"],
        weights=[28 if everyday else 6, 38, 27, 7],
        k=1,
    )[0]
    sessions: list[str] = []
    hours: list[int] = []
    if schedule_kind == "all_day":
        hours = list(HOURS)
    elif schedule_kind == "session":
        sessions = [rng.choice(SESSIONS)]
    elif schedule_kind == "hour_window":
        start = rng.randrange(0, 22)
        width = rng.choice((2, 3, 4, 6))
        hours = list(range(start, min(24, start + width)))
    else:
        hours = [rng.choice(HOURS)]

    return {
        "weekdays": list(weekdays),
        "months": list(months),
        "sessions": sessions,
        "hours_utc": hours,
        "schedule_kind": schedule_kind,
        "everyday_target": len(weekdays) >= 5 and len(months) == 12,
    }


def _environment(rng: random.Random, family: str) -> dict[str, Any]:
    environment: dict[str, Any] = {
        "regimes": [],
        "trend_12": "any",
        "trend_48": "any",
        "compression": "any",
        "min_alignment_abs": 0,
        "alignment_sign": "any",
        "streak": "any",
    }
    if family in {"momentum_continuation", "alignment_continuation", "pullback_continuation"}:
        environment["trend_12"] = rng.choice(("up", "down", "directional"))
        if rng.random() < 0.45:
            environment["trend_48"] = rng.choice(("up", "down", "directional"))
    elif family == "composed_signal":
        if rng.random() < 0.55:
            environment["trend_12"] = rng.choice(("any", "up", "down", "flat", "directional"))
        if rng.random() < 0.35:
            environment["trend_48"] = rng.choice(("any", "up", "down", "flat", "directional"))
    if family == "alignment_continuation":
        environment["min_alignment_abs"] = rng.choice((1, 2, 3))
    if family == "volatility_breakout":
        environment["compression"] = rng.choice(("compressed", "normal"))
    if family == "mean_reversion":
        environment["trend_12"] = rng.choice(("flat", "any"))
        environment["compression"] = rng.choice(("normal", "expanded"))
    if family == "candle_reversal":
        environment["compression"] = rng.choice(("any", "expanded"))
    if rng.random() < 0.25:
        environment["regimes"] = [rng.choice(("trend_up", "trend_down", "range", "compression", "high_volatility"))]
    return environment


def _condition(rng: random.Random, existing: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    existing = existing or []
    existing_types = {str(item.get("type")) for item in existing}
    blocked = set(existing_types)
    for condition_type in existing_types:
        blocked.update(CONDITION_CONFLICTS.get(condition_type, set()))
    available = [item for item in CONDITION_TYPES if item not in blocked]
    if not available:
        available = [item for item in CONDITION_TYPES if item not in existing_types] or list(CONDITION_TYPES)
    kind = rng.choice(available)
    result: dict[str, Any] = {"type": kind}
    if kind == "alignment_abs_min":
        result["min"] = rng.choice((1, 2, 3, 4))
    elif kind == "return_3_abs_min":
        result["threshold"] = rng.choice((0.0025, 0.005, 0.01, 0.02, 0.04))
    elif kind == "impulse_1_vs_3":
        result["ratio"] = rng.choice((0.20, 0.25, 0.33, 0.50, 0.75))
    elif kind == "close_location_extreme":
        result["edge"] = rng.choice((0.12, 0.15, 0.20, 0.25, 0.30))
    elif kind == "wick_body_ratio_min":
        result["ratio"] = rng.choice((1.20, 1.50, 1.80, 2.00, 2.50, 3.00))
    return result


def _composed_entry(rng: random.Random) -> dict[str, Any]:
    conditions: list[dict[str, Any]] = []
    for _ in range(rng.choice((2, 2, 3, 3, 4))):
        conditions.append(_condition(rng, conditions))
    return {
        "direction_rule": rng.choice(DIRECTION_RULES),
        "condition_mode": "all",
        "conditions": conditions,
    }


def describe_condition(condition: dict[str, Any]) -> str:
    kind = str(condition.get("type") or "")
    return {
        "direction_matches_trend12": "candle direction agrees with the 12-bar trend",
        "direction_opposes_trend12": "candle direction opposes the 12-bar trend",
        "alignment_abs_min": f"multi-timeframe alignment strength is at least {condition.get('min')}",
        "alignment_matches_direction": "alignment agrees with the current candle",
        "alignment_opposes_direction": "alignment opposes the current candle",
        "return_3_abs_min": f"the three-bar move exceeds {float(condition.get('threshold') or 0):.4f}%",
        "return_3_matches_direction": "the three-bar move agrees with the current candle",
        "impulse_1_vs_3": f"the latest move is at least {float(condition.get('ratio') or 0):.2f} of the three-bar move",
        "close_location_extreme": f"the candle closes in an outer {float(condition.get('edge') or 0) * 100:.0f}% band",
        "wick_body_ratio_min": f"a wick is at least {float(condition.get('ratio') or 0):.1f}× the body",
        "trend12_trend48_agree": "the 12-bar and 48-bar trends agree",
    }.get(kind, kind.replace("_", " "))


def describe_strategy(rules: dict[str, Any]) -> str:
    schedule = dict(rules.get("schedule") or {})
    entry = dict(rules.get("entry") or {})
    conditions = [describe_condition(item) for item in entry.get("conditions") or []]
    timing = "every weekday" if schedule.get("everyday_target") else f"{len(schedule.get('weekdays') or [])} selected weekdays"
    if schedule.get("sessions"):
        timing += f" during {', '.join(schedule['sessions']).replace('_', ' ')}"
    elif len(schedule.get("hours_utc") or []) != 24:
        timing += f" at UTC hours {', '.join(str(v) for v in schedule.get('hours_utc') or [])}"
    if rules.get("family") == "composed_signal":
        recipe = "; ".join(conditions)
        return f"Independently composed signal recipe for {timing}: {recipe}. Direction uses {str(entry.get('direction_rule')).replace('_', ' ')}."
    return (
        f"Benchmark archetype for {timing}: {str(rules.get('family')).replace('_', ' ')} with "
        f"{str(entry.get('direction_rule')).replace('_', ' ')} direction."
    )


def create_strategy(
    rng: random.Random,
    generation: int,
    family_weights: dict[str, float] | None = None,
    everyday_bias: float = 0.70,
) -> dict[str, Any]:
    weights = dict(family_weights or {})
    # Most new candidates are independent recipes; legacy archetypes remain as useful benchmarks.
    weights["composed_signal"] = float(weights.get("composed_signal", 0.0)) + 15.0
    family = weighted_choice(rng, FAMILIES, weights)
    stop = rng.choice(STOP_GRID)
    viable_targets = [value for value in TARGET_GRID if value / stop >= 0.8]
    target = rng.choice(viable_targets)
    horizon = rng.choice(HORIZONS)
    cooldown = rng.choice([value for value in COOLDOWNS if value <= max(240, horizon * 2)])
    entry = _composed_entry(rng) if family == "composed_signal" else family_defaults(family)
    rules = {
        "engine_version": ENGINE_VERSION,
        "family": family,
        "schedule": _schedule(rng, everyday_bias),
        "environment": _environment(rng, family),
        "entry": entry,
        "risk": {
            "stop_atr": stop,
            "target_atr": target,
            "horizon_minutes": horizon,
            "max_hold_minutes": horizon,
            "cooldown_minutes": cooldown,
            "cost_r": 0.04,
            "risk_percent": 0.25,
            "max_daily_loss_percent": 1.0,
            "max_spread_points": 100,
        },
    }
    digest = strategy_hash(rules)
    schedule = rules["schedule"]
    schedule_label = "Everyday" if schedule["everyday_target"] else "Scheduled"
    rr = target / stop
    if family == "composed_signal":
        name = f"EVE Composite {digest[:6].upper()} · {schedule_label} · {rr:.1f}R"
    else:
        name = f"Benchmark {family.replace('_', ' ').title()} · {schedule_label} · {rr:.1f}R"
    return {
        "candidate_key": f"candidate-{digest[:28]}",
        "generation": generation,
        "family": family,
        "name": name,
        "hypothesis": describe_strategy(rules),
        "rules": rules,
        "status": "queued",
        "priority": 90 if family == "composed_signal" and schedule["everyday_target"] else 75 if family == "composed_signal" else 60,
        "composer_version": ENGINE_VERSION,
    }


def memory_weights(memory: list[dict[str, Any]]) -> dict[str, float]:
    weights: dict[str, float] = {}
    for row in memory:
        if str(row.get("gene")) == "family":
            weights[str(row.get("family"))] = float(row.get("score") or 0.0)
    return weights


def compose_batch(
    count: int,
    generation: int,
    seed: int,
    memory: list[dict[str, Any]] | None = None,
    everyday_bias: float = 0.70,
) -> list[dict[str, Any]]:
    rng = random.Random(seed)
    weights = memory_weights(memory or [])
    unique: dict[str, dict[str, Any]] = {}
    attempts = 0
    while len(unique) < count and attempts < count * 30:
        candidate = create_strategy(rng, generation, weights, everyday_bias)
        unique[candidate["candidate_key"]] = candidate
        attempts += 1
    return list(unique.values())


@dataclass(frozen=True)
class Mutation:
    gene: str
    old: Any
    new: Any
    rules: dict[str, Any]


def _deepcopy(value: dict[str, Any]) -> dict[str, Any]:
    return json.loads(json.dumps(value))


def _available_genes(rules: dict[str, Any]) -> list[str]:
    genes = [
        "stop_atr", "target_atr", "horizon", "cooldown", "weekdays", "months", "sessions", "hours",
        "trend_12", "trend_48", "compression", "alignment", "alignment_sign", "regime",
        "direction_rule", "family",
    ]
    if str(rules.get("family")) == "composed_signal":
        genes.extend(("add_condition", "remove_condition", "replace_condition", "condition_parameter"))
        conditions = list(rules.get("entry", {}).get("conditions") or [])
        if len(conditions) <= 1 and "remove_condition" in genes:
            genes.remove("remove_condition")
        if not any(set(item) - {"type"} for item in conditions) and "condition_parameter" in genes:
            genes.remove("condition_parameter")
    return genes


def _mutate_condition_parameter(condition: dict[str, Any], rng: random.Random) -> tuple[dict[str, Any], dict[str, Any]]:
    old = _deepcopy(condition)
    new = _deepcopy(condition)
    kind = str(new.get("type"))
    if kind == "alignment_abs_min":
        current = int(new.get("min") or 1)
        new["min"] = rng.choice([v for v in (1, 2, 3, 4) if v != current])
    elif kind == "return_3_abs_min":
        current = float(new.get("threshold") or 0.005)
        new["threshold"] = rng.choice([v for v in (0.0025, 0.005, 0.01, 0.02, 0.04) if v != current])
    elif kind == "impulse_1_vs_3":
        current = float(new.get("ratio") or 0.25)
        new["ratio"] = rng.choice([v for v in (0.20, 0.25, 0.33, 0.50, 0.75) if v != current])
    elif kind == "close_location_extreme":
        current = float(new.get("edge") or 0.20)
        new["edge"] = rng.choice([v for v in (0.12, 0.15, 0.20, 0.25, 0.30) if v != current])
    elif kind == "wick_body_ratio_min":
        current = float(new.get("ratio") or 1.5)
        new["ratio"] = rng.choice([v for v in (1.20, 1.50, 1.80, 2.00, 2.50, 3.00) if v != current])
    else:
        raise ValueError("Condition has no mutable parameter")
    return old, new


def mutate_rules(
    parent_rules: dict[str, Any],
    rng: random.Random,
    preferred_genes: list[str] | None = None,
    exploration_rate: float = 0.0,
) -> Mutation:
    rules = _deepcopy(parent_rules)
    available = _available_genes(rules)
    preferred = [gene for gene in (preferred_genes or []) if gene in available]
    if preferred and rng.random() >= max(0.0, min(1.0, exploration_rate)):
        gene = rng.choice(preferred)
    else:
        gene = rng.choice(available)

    if gene == "stop_atr":
        old = float(rules["risk"]["stop_atr"])
        options = [v for v in STOP_GRID if v != old]
        new = min(options, key=lambda v: (abs(v - old), rng.random()))
        rules["risk"]["stop_atr"] = new
    elif gene == "target_atr":
        old = float(rules["risk"]["target_atr"])
        options = [v for v in TARGET_GRID if v != old]
        new = min(options, key=lambda v: (abs(v - old), rng.random()))
        rules["risk"]["target_atr"] = new
    elif gene == "horizon":
        old = int(rules["risk"]["horizon_minutes"])
        new = rng.choice([v for v in HORIZONS if v != old])
        rules["risk"]["horizon_minutes"] = new
        rules["risk"]["max_hold_minutes"] = new
    elif gene == "cooldown":
        old = int(rules["risk"]["cooldown_minutes"])
        new = rng.choice([v for v in COOLDOWNS if v != old])
        rules["risk"]["cooldown_minutes"] = new
    elif gene == "weekdays":
        old = list(rules["schedule"]["weekdays"])
        new = list(rng.choice([v for v in WEEKDAY_PRESETS if list(v) != old]))
        rules["schedule"]["weekdays"] = new
        rules["schedule"]["everyday_target"] = len(new) >= 5 and len(rules["schedule"]["months"]) == 12
    elif gene == "months":
        old = list(rules["schedule"]["months"])
        new = list(rng.choice([v for v in MONTH_PRESETS if list(v) != old]))
        rules["schedule"]["months"] = new
        rules["schedule"]["everyday_target"] = len(rules["schedule"]["weekdays"]) >= 5 and len(new) == 12
    elif gene == "sessions":
        old = list(rules["schedule"]["sessions"])
        new = [] if old else [rng.choice(SESSIONS)]
        rules["schedule"]["sessions"] = new
        if new:
            rules["schedule"]["hours_utc"] = []
            rules["schedule"]["schedule_kind"] = "session"
    elif gene == "hours":
        old = list(rules["schedule"]["hours_utc"])
        start = rng.randrange(0, 23)
        width = rng.choice((1, 2, 3, 4, 6))
        new = list(range(start, min(24, start + width)))
        rules["schedule"]["hours_utc"] = new
        rules["schedule"]["sessions"] = []
        rules["schedule"]["schedule_kind"] = "single_hour" if len(new) == 1 else "hour_window"
    elif gene in {"trend_12", "trend_48"}:
        old = rules["environment"].get(gene, "any")
        new = rng.choice([v for v in ("any", "up", "down", "flat", "directional") if v != old])
        rules["environment"][gene] = new
    elif gene == "compression":
        old = rules["environment"].get("compression", "any")
        new = rng.choice([v for v in ("any", "compressed", "normal", "expanded") if v != old])
        rules["environment"]["compression"] = new
    elif gene == "alignment":
        old = int(rules["environment"].get("min_alignment_abs", 0))
        new = rng.choice([v for v in (0, 1, 2, 3, 4) if v != old])
        rules["environment"]["min_alignment_abs"] = new
    elif gene == "alignment_sign":
        old = str(rules["environment"].get("alignment_sign", "any"))
        new = rng.choice([v for v in ("any", "up", "down") if v != old])
        rules["environment"]["alignment_sign"] = new
    elif gene == "regime":
        old = list(rules["environment"].get("regimes") or [])
        choices = [[], ["trend_up"], ["trend_down"], ["range"], ["compression"], ["high_volatility"]]
        new = rng.choice([value for value in choices if value != old])
        rules["environment"]["regimes"] = new
    elif gene == "direction_rule":
        old = rules["entry"].get("direction_rule", "current_direction")
        new = rng.choice([v for v in DIRECTION_RULES if v != old])
        rules["entry"]["direction_rule"] = new
    elif gene == "add_condition":
        conditions = list(rules["entry"].get("conditions") or [])
        old = _deepcopy(conditions)
        conditions.append(_condition(rng, conditions))
        new = _deepcopy(conditions)
        rules["entry"]["conditions"] = conditions
    elif gene == "remove_condition":
        conditions = list(rules["entry"].get("conditions") or [])
        old = _deepcopy(conditions)
        del conditions[rng.randrange(len(conditions))]
        new = _deepcopy(conditions)
        rules["entry"]["conditions"] = conditions
    elif gene == "replace_condition":
        conditions = list(rules["entry"].get("conditions") or [])
        old = _deepcopy(conditions)
        index = rng.randrange(len(conditions))
        remaining = conditions[:index] + conditions[index + 1:]
        conditions[index] = _condition(rng, remaining)
        new = _deepcopy(conditions)
        rules["entry"]["conditions"] = conditions
    elif gene == "condition_parameter":
        conditions = list(rules["entry"].get("conditions") or [])
        mutable = [index for index, item in enumerate(conditions) if set(item) - {"type"}]
        index = rng.choice(mutable)
        old_condition, new_condition = _mutate_condition_parameter(conditions[index], rng)
        old, new = old_condition, new_condition
        conditions[index] = new_condition
        rules["entry"]["conditions"] = conditions
    else:
        old = rules["family"]
        new = rng.choice([v for v in FAMILIES if v != old])
        rules["family"] = new
        rules["entry"] = _composed_entry(rng) if new == "composed_signal" else family_defaults(new)

    rules["engine_version"] = "eve-discovery-evolution-v2"
    return Mutation(gene=gene, old=old, new=new, rules=rules)


def mutation_batch(
    lineage: dict[str, Any],
    count: int,
    generation: int,
    seed: int,
    memory: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    rng = random.Random(seed)
    family = str(lineage.get("family") or "unknown")
    family_memory = [row for row in (memory or []) if str(row.get("family")) == family]
    preferred = [
        str(row.get("gene"))
        for row in family_memory
        if float(row.get("score") or 0) > 0 and int(row.get("attempts") or 0) >= 2
    ]
    parent_rules = dict(lineage.get("champion_rules") or {})
    unique: dict[str, dict[str, Any]] = {}
    attempts = 0
    while len(unique) < count and attempts < count * 30:
        mutation = mutate_rules(parent_rules, rng, preferred or None, exploration_rate=0.30)
        digest = strategy_hash(mutation.rules)
        key = f"mutation-{digest[:28]}"
        unique[key] = {
            "mutation_key": key,
            "lineage_id": lineage.get("id"),
            "generation": generation,
            "family": mutation.rules.get("family") or family,
            "name": f"{lineage.get('name') or family} · generation {generation} · {mutation.gene}",
            "mutation_gene": mutation.gene,
            "changes": {mutation.gene: {"from": mutation.old, "to": mutation.new}},
            "parent_rules": parent_rules,
            "parent_metrics": lineage.get("champion_metrics") or {},
            "parent_fitness": float(lineage.get("champion_fitness") or 0),
            "rules": mutation.rules,
            "status": "queued",
            "priority": 80,
        }
        attempts += 1
    return list(unique.values())
