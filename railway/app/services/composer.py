from __future__ import annotations

import hashlib
import json
import random
from dataclasses import dataclass
from typing import Any, Iterable

ENGINE_VERSION = "eve-discovery-composer-v1"

FAMILIES = (
    "momentum_continuation",
    "alignment_continuation",
    "pullback_continuation",
    "volatility_breakout",
    "mean_reversion",
    "candle_reversal",
)
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
        weights=[20 if everyday else 5, 40, 30, 10],
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


def create_strategy(rng: random.Random, generation: int, family_weights: dict[str, float] | None = None,
                    everyday_bias: float = 0.70) -> dict[str, Any]:
    family = weighted_choice(rng, FAMILIES, family_weights)
    stop = rng.choice(STOP_GRID)
    viable_targets = [value for value in TARGET_GRID if value / stop >= 0.8]
    target = rng.choice(viable_targets)
    horizon = rng.choice(HORIZONS)
    cooldown = rng.choice([value for value in COOLDOWNS if value <= max(240, horizon * 2)])
    rules = {
        "engine_version": ENGINE_VERSION,
        "family": family,
        "schedule": _schedule(rng, everyday_bias),
        "environment": _environment(rng, family),
        "entry": family_defaults(family),
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
    family_label = family.replace("_", " ").title()
    rr = target / stop
    return {
        "candidate_key": f"candidate-{digest[:28]}",
        "generation": generation,
        "family": family,
        "name": f"{schedule_label} {family_label} · {rr:.1f}R",
        "hypothesis": (
            f"Test a newly composed {family_label.lower()} strategy across chronological, walk-forward and locked data. "
            f"The target is broad weekday coverage without forcing daily trades."
        ),
        "rules": rules,
        "status": "queued",
        "priority": 85 if schedule["everyday_target"] else 65,
        "composer_version": ENGINE_VERSION,
    }


def memory_weights(memory: list[dict[str, Any]]) -> dict[str, float]:
    weights: dict[str, float] = {}
    for row in memory:
        if str(row.get("gene")) == "family":
            weights[str(row.get("family"))] = float(row.get("score") or 0.0)
    return weights


def compose_batch(count: int, generation: int, seed: int, memory: list[dict[str, Any]] | None = None,
                  everyday_bias: float = 0.70) -> list[dict[str, Any]]:
    rng = random.Random(seed)
    weights = memory_weights(memory or [])
    unique: dict[str, dict[str, Any]] = {}
    attempts = 0
    while len(unique) < count and attempts < count * 20:
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


def mutate_rules(parent_rules: dict[str, Any], rng: random.Random, preferred_genes: list[str] | None = None) -> Mutation:
    rules = _deepcopy(parent_rules)
    genes = preferred_genes or [
        "stop_atr", "target_atr", "horizon", "cooldown", "weekdays", "sessions", "hours", "trend_12",
        "trend_48", "compression", "alignment", "direction_rule", "family",
    ]
    gene = rng.choice(genes)

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
        key = gene
        old = rules["environment"].get(key, "any")
        new = rng.choice([v for v in ("any", "up", "down", "flat", "directional") if v != old])
        rules["environment"][key] = new
    elif gene == "compression":
        old = rules["environment"].get("compression", "any")
        new = rng.choice([v for v in ("any", "compressed", "normal", "expanded") if v != old])
        rules["environment"]["compression"] = new
    elif gene == "alignment":
        old = int(rules["environment"].get("min_alignment_abs", 0))
        new = rng.choice([v for v in (0, 1, 2, 3, 4) if v != old])
        rules["environment"]["min_alignment_abs"] = new
    elif gene == "direction_rule":
        old = rules["entry"].get("direction_rule", "current_direction")
        new = rng.choice([v for v in ("current_direction", "alignment_direction", "trend_direction", "reverse_current", "wick_reversal") if v != old])
        rules["entry"]["direction_rule"] = new
    else:
        old = rules["family"]
        new = rng.choice([v for v in FAMILIES if v != old])
        rules["family"] = new
        rules["entry"] = family_defaults(new)

    rules["engine_version"] = "eve-discovery-evolution-v1"
    return Mutation(gene=gene, old=old, new=new, rules=rules)


def mutation_batch(lineage: dict[str, Any], count: int, generation: int, seed: int,
                   memory: list[dict[str, Any]] | None = None) -> list[dict[str, Any]]:
    rng = random.Random(seed)
    family = str(lineage.get("family") or "unknown")
    family_memory = [row for row in (memory or []) if str(row.get("family")) == family]
    preferred = [str(row.get("gene")) for row in family_memory if float(row.get("score") or 0) > 0]
    parent_rules = dict(lineage.get("champion_rules") or {})
    unique: dict[str, dict[str, Any]] = {}
    attempts = 0
    while len(unique) < count and attempts < count * 20:
        mutation = mutate_rules(parent_rules, rng, preferred or None)
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
