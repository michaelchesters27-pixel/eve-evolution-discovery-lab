from __future__ import annotations

import math
import random
from typing import Any

from app.services import intelligence as v1
from app.services import intelligence_v2 as scientist
from app.services.composer import describe_strategy, strategy_hash
from app.services.evidence_miner import FDR_GATE, YEAR_STABILITY_GATE

EVIDENCE_SEEDER_VERSION = "eve-evidence-hypothesis-seeder-v1"
SEED_SHARE = 0.55
SUPPORTED_TRADE_HORIZONS = (15, 30, 60, 240)
SEED_Q_GATE = min(FDR_GATE, 0.05)
SEED_YEAR_STABILITY_GATE = max(YEAR_STABILITY_GATE, 0.75)
SEED_MIN_SAMPLES = 500
SEED_MIN_SCORE = 0.75


def _number(value: Any, default: float = 0.0) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return default
    return parsed if math.isfinite(parsed) else default


def stored_signal_is_verified(row: dict[str, Any]) -> bool:
    return (
        str(row.get("status") or "") == "signal"
        and _number(row.get("q_value"), 1.0) <= FDR_GATE
        and _number(row.get("year_stability"), 0.0) >= YEAR_STABILITY_GATE
        and abs(_number(row.get("standardized_effect"), 0.0)) >= 0.03
        and int(_number(row.get("sample_count"), 0.0)) > 0
        and _number(row.get("evidence_score"), 0.0) > 0.0
    )


def verified_evidence_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    result = [dict(row) for row in rows if stored_signal_is_verified(row)]
    result.sort(key=lambda row: (_number(row.get("evidence_score")), -_number(row.get("q_value"), 1.0)), reverse=True)
    return result


def _scalar(raw: str) -> Any:
    value = str(raw).strip()
    try:
        return float(value) if any(token in value.lower() for token in (".", "e")) else int(value)
    except ValueError:
        return value


def condition_from_feature_key(feature_key: str) -> dict[str, Any] | None:
    key = str(feature_key or "")
    if not key.startswith("condition:"):
        return None
    payload = key.removeprefix("condition:")
    kind, separator, parameters = payload.partition(":")
    if not kind:
        return None
    result: dict[str, Any] = {"type": kind}
    if separator:
        for item in parameters.split(","):
            name, equals, value = item.partition("=")
            if equals and name:
                result[name] = _scalar(value)
    return result


def _schedule() -> dict[str, Any]:
    return {"weekdays": [1, 2, 3, 4, 5], "months": list(range(1, 13)), "sessions": [], "hours_utc": list(range(24)), "schedule_kind": "all_day", "everyday_target": True}


def _environment() -> dict[str, Any]:
    return {"regimes": [], "trend_12": "any", "trend_48": "any", "compression": "any", "min_alignment_abs": 0, "alignment_sign": "any", "streak": "any"}


def _constraints(row: dict[str, Any]) -> tuple[list[dict[str, Any]], dict[str, Any], dict[str, Any], list[str]]:
    conditions: list[dict[str, Any]] = []
    schedule = _schedule()
    environment = _environment()
    unsupported: list[str] = []
    seen_types: set[str] = set()
    for raw in row.get("feature_keys") or []:
        key = str(raw or "")
        condition = condition_from_feature_key(key)
        if condition is not None:
            kind = str(condition.get("type") or "")
            if kind in seen_types:
                unsupported.append(key)
            else:
                seen_types.add(kind)
                conditions.append(condition)
        elif key.startswith("schedule:session:"):
            session = key.removeprefix("schedule:session:")
            schedule["sessions"] = [session]
            schedule["hours_utc"] = []
            schedule["schedule_kind"] = "session"
        elif key.startswith("environment:regime:"):
            environment["regimes"] = [key.removeprefix("environment:regime:")]
        else:
            unsupported.append(key)
    return conditions, schedule, environment, unsupported


def seed_eligibility(row: dict[str, Any]) -> tuple[bool, str]:
    if not stored_signal_is_verified(row):
        return False, "stored_gate_not_verified"
    if str(row.get("direction") or "").lower() not in {"up", "down"}:
        return False, "no_direction"
    if int(_number(row.get("horizon_minutes"))) not in SUPPORTED_TRADE_HORIZONS:
        return False, "unsupported_trade_horizon"
    if _number(row.get("q_value"), 1.0) > SEED_Q_GATE:
        return False, "seed_q_gate"
    if _number(row.get("year_stability")) < SEED_YEAR_STABILITY_GATE:
        return False, "seed_year_stability_gate"
    if int(_number(row.get("sample_count"))) < SEED_MIN_SAMPLES:
        return False, "seed_sample_gate"
    if _number(row.get("evidence_score")) < SEED_MIN_SCORE:
        return False, "seed_score_gate"
    conditions, _, _, unsupported = _constraints(row)
    if unsupported:
        return False, "unsupported_feature_translation"
    if not conditions:
        return False, "no_entry_condition"
    return True, "eligible"


def proposal_from_signal(row: dict[str, Any], rng: random.Random, *, symbol: str, timeframe: str, snapshot_interval: str, source_interval: str, research_dataset: str, fabric_version: str | None = None) -> dict[str, Any] | None:
    eligible, _ = seed_eligibility(row)
    if not eligible:
        return None
    conditions, schedule, environment, _ = _constraints(row)
    horizon = int(_number(row.get("horizon_minutes")))
    direction = str(row.get("direction") or "").lower()
    rules = v1.proposal_rules(rng, {}, symbol=symbol, timeframe=timeframe, snapshot_interval=snapshot_interval, source_interval=source_interval)
    rules["engine_version"] = scientist.INTELLIGENCE_VERSION
    rules["market"]["research_source"] = "evidence_miner_targeted_hypothesis"
    rules["market"]["research_dataset"] = research_dataset
    rules["market"]["evidence_seed_version"] = EVIDENCE_SEEDER_VERSION
    rules["market"]["mt5_export_gate"] = "advanced_rule_parity_required"
    if fabric_version:
        rules["market"]["fabric_version"] = fabric_version
    rules["schedule"] = schedule
    rules["environment"] = environment
    rules["entry"] = {"direction_rule": "evidence_long" if direction == "up" else "evidence_short", "condition_mode": "all", "conditions": conditions}
    risk = dict(rules.get("risk") or {})
    risk["horizon_minutes"] = horizon
    risk["max_hold_minutes"] = horizon
    risk["cooldown_minutes"] = int(rng.choice([value for value in v1.COOLDOWNS if value <= horizon] or [5]))
    rules["risk"] = risk
    digest = strategy_hash(rules)
    return {
        "hypothesis_key": f"science-{digest[:32]}",
        "candidate_key": f"candidate-{digest[:28]}",
        "rules": rules,
        "hypothesis": f"Evidence-seeded {direction.upper()} {horizon}m hypothesis from {int(_number(row.get('sample_count'))):,} development occurrences: {describe_strategy(rules)}",
        "feature_keys": [*v1.rule_feature_keys(rules), "scientist:evidence_seed"],
    }


def build_seeded_proposals(rows: list[dict[str, Any]], existing: set[str], *, target: int, seed: int, symbol: str, timeframe: str, snapshot_interval: str, source_interval: str, research_dataset: str, fabric_version: str | None = None) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    verified = verified_evidence_rows(rows)
    rng = random.Random(seed ^ 0xE71D3CE)
    seen = set(existing)
    proposals: list[dict[str, Any]] = []
    skipped: dict[str, int] = {}
    feature_sets: dict[tuple[str, ...], int] = {}
    eligible_count = 0
    for row in verified:
        eligible, reason = seed_eligibility(row)
        if not eligible:
            skipped[reason] = skipped.get(reason, 0) + 1
            continue
        eligible_count += 1
        feature_set = tuple(sorted(str(item) for item in row.get("feature_keys") or []))
        if feature_sets.get(feature_set, 0) >= 2:
            skipped["feature_set_diversity_cap"] = skipped.get("feature_set_diversity_cap", 0) + 1
            continue
        feature_sets[feature_set] = feature_sets.get(feature_set, 0) + 1
        if len(proposals) >= target:
            break
        created = None
        for _ in range(6):
            candidate = proposal_from_signal(row, rng, symbol=symbol, timeframe=timeframe, snapshot_interval=snapshot_interval, source_interval=source_interval, research_dataset=research_dataset, fabric_version=fabric_version)
            if candidate and candidate["hypothesis_key"] not in seen:
                created = candidate
                break
        if created is None:
            skipped["already_tested_rule"] = skipped.get("already_tested_rule", 0) + 1
            continue
        seen.add(created["hypothesis_key"])
        proposals.append(created)
    return proposals, {
        "version": EVIDENCE_SEEDER_VERSION,
        "stored_signals_seen": len(rows),
        "verified_signals": len(verified),
        "seed_eligible_signals": eligible_count,
        "seeded_hypotheses": len(proposals),
        "target": target,
        "seed_share_cap": SEED_SHARE,
        "skipped": skipped,
        "generation_data": "development_only",
        "validation_access": "forbidden",
        "confirmation_holdout_access": "forbidden",
        "mt5_export_status": "advanced_rule_parity_required",
    }
