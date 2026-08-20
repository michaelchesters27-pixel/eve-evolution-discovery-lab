from __future__ import annotations

from typing import Any

from app.services import intelligence as v1

LEARNING_VERSION = "eve-scientist-learning-loop-v1"


def _selection_result(candidate: dict[str, Any], result: dict[str, Any]) -> bool:
    return str(candidate.get("research_stage") or "selection") == "selection" and bool(candidate.get("candidate_key"))


def learning_feature_keys(rules: dict[str, Any]) -> list[str]:
    features = list(v1.rule_feature_keys(rules))
    entry = dict(rules.get("entry") or {})
    conditions = [dict(item) for item in entry.get("conditions") or [] if isinstance(item, dict)]
    kinds = [str(item.get("type") or "") for item in conditions]

    if any(kind.startswith("mtf_") for kind in kinds) or str(entry.get("direction_rule") or "").startswith("mtf_"):
        features.append("scientist:research_family:multitimeframe")
    if any(token in kind for kind in kinds for token in ("sweep", "break_prior", "prev_day", "session_")):
        features.append("scientist:research_family:structure_liquidity")
    if any(kind in {"displacement_atr_min", "range_expansion_min", "compression_release"} for kind in kinds):
        features.append("scientist:research_family:volatility_transition")
    if any(kind.startswith("mtf_m1_") for kind in kinds):
        features.append("scientist:research_family:m1_microstructure")

    count = len(conditions)
    features.append(f"scientist:condition_count:{min(5, count)}")
    return list(dict.fromkeys(str(item) for item in features if item))


def selection_contribution(result: dict[str, Any]) -> float:
    metrics = dict(result.get("metrics") or {})
    validation = dict(metrics.get("validation") or {})
    pf = float(v1.number(validation.get("profit_factor")))
    expectancy = float(v1.number(validation.get("expectancy_r")))
    trades = float(v1.number(validation.get("trades")))
    result_status = str(result.get("result_status") or "rejected")

    status_bonus = {
        "elite": 3.5,
        "validated": 2.5,
        "promising": 1.25,
        "rejected": -0.50,
    }.get(result_status, -0.25)

    decision = dict((result.get("evidence") or {}).get("decision") or {})
    failed = {str(item) for item in decision.get("failed_gates") or []}
    gate_penalty = 0.0
    gate_penalty += 0.55 if "validation_edge" in failed else 0.0
    gate_penalty += 0.45 if "monte_carlo_confidence" in failed else 0.0
    gate_penalty += 0.35 if "rolling_stability" in failed else 0.0
    gate_penalty += 0.30 if "parameter_neighbourhood" in failed else 0.0
    gate_penalty += 0.20 if "validation_sample" in failed else 0.0

    raw = (pf - 1.0) * 2.0 + expectancy * 10.0 + status_bonus - gate_penalty
    sample_weight = v1.clamp(trades / 120.0, 0.35, 1.0)
    return round(v1.clamp(raw * sample_weight, -4.0, 6.0), 6)


def hypothesis_state(result_status: str) -> str:
    return "passed_selection" if result_status in {"promising", "validated", "elite"} else "rejected_selection"


async def _sync_hypothesis(repo: Any, candidate: dict[str, Any], result: dict[str, Any]) -> bool:
    candidate_key = str(candidate.get("candidate_key") or "")
    if not candidate_key:
        return False
    rows = await repo.client.get(
        "scientist_hypotheses",
        params={
            "select": "hypothesis_key,evidence",
            "candidate_key": f"eq.{candidate_key}",
            "limit": "1",
        },
    )
    if not rows:
        return False

    row = dict(rows[0])
    evidence = dict(row.get("evidence") or {})
    metrics = dict(result.get("metrics") or {})
    validation = dict(metrics.get("validation") or {})
    decision = dict((result.get("evidence") or {}).get("decision") or {})
    evidence["selection"] = {
        "result_status": result.get("result_status"),
        "fitness_score": result.get("fitness_score"),
        "validation": validation,
        "failed_gates": list(decision.get("failed_gates") or []),
        "plain_reason": decision.get("plain_reason"),
        "confirmation_holdout_access": "forbidden",
    }
    await repo.client.patch(
        "scientist_hypotheses",
        {
            "state": hypothesis_state(str(result.get("result_status") or "rejected")),
            "evidence": evidence,
            "updated_at": v1.utc_now().isoformat(),
        },
        filters={"hypothesis_key": f"eq.{row.get('hypothesis_key')}"},
    )
    return True


def _event_payload(candidate: dict[str, Any], result: dict[str, Any], scientist_version: str) -> dict[str, Any]:
    rules = dict(candidate.get("rules") or {})
    market = dict(rules.get("market") or {})
    metrics = dict(result.get("metrics") or {})
    validation = dict(metrics.get("validation") or {})
    decision = dict((result.get("evidence") or {}).get("decision") or {})
    return {
        "candidate_key": str(candidate.get("candidate_key") or ""),
        "scientist_version": scientist_version,
        "research_dataset": str(market.get("research_dataset") or "legacy_15m"),
        "result_status": str(result.get("result_status") or "rejected"),
        "contribution": selection_contribution(result),
        "validation_pf": round(float(v1.number(validation.get("profit_factor"))), 6),
        "validation_expectancy_r": round(float(v1.number(validation.get("expectancy_r"))), 6),
        "validation_trades": int(v1.number(validation.get("trades"))),
        "fitness_score": round(float(v1.number(result.get("fitness_score"))), 6),
        "failed_gates": list(decision.get("failed_gates") or []),
        "feature_keys": learning_feature_keys(rules),
        "learned_at": str(candidate.get("finished_at") or v1.utc_now().isoformat()),
        "updated_at": v1.utc_now().isoformat(),
    }


async def rebuild_memory_from_ledger(
    repo: Any,
    scientist_version: str,
    research_dataset: str,
) -> dict[str, float]:
    events = await repo.client.get(
        "scientist_learning_events",
        params={
            "select": "candidate_key,contribution,validation_pf,validation_expectancy_r,validation_trades,feature_keys",
            "scientist_version": f"eq.{scientist_version}",
            "research_dataset": f"eq.{research_dataset}",
            "order": "learned_at.desc",
            "limit": "10000",
        },
    )
    aggregates: dict[str, dict[str, float]] = {}
    for event in events:
        contribution = float(v1.number(event.get("contribution")))
        pf = float(v1.number(event.get("validation_pf")))
        expectancy = float(v1.number(event.get("validation_expectancy_r")))
        trades = float(v1.number(event.get("validation_trades")))
        for feature in event.get("feature_keys") or []:
            key = str(feature)
            item = aggregates.setdefault(
                key,
                {
                    "trials": 0.0,
                    "positive_trials": 0.0,
                    "sum_score": 0.0,
                    "sum_pf": 0.0,
                    "sum_exp": 0.0,
                    "sum_trades": 0.0,
                },
            )
            item["trials"] += 1.0
            item["positive_trials"] += 1.0 if contribution > 0 else 0.0
            item["sum_score"] += contribution
            item["sum_pf"] += pf
            item["sum_exp"] += expectancy
            item["sum_trades"] += trades

    now = v1.utc_now().isoformat()
    memory_rows: list[dict[str, Any]] = []
    for feature, item in aggregates.items():
        trials = max(1.0, item["trials"])
        raw_mean = item["sum_score"] / trials
        # Bayesian-style shrinkage toward neutral prevents one lucky/awful test
        # from dominating the next research cycle.
        confidence = trials / (trials + 3.0)
        score = raw_mean * confidence
        memory_rows.append(
            {
                "feature_key": feature,
                "scientist_version": scientist_version,
                "trials": int(item["trials"]),
                "positive_trials": int(item["positive_trials"]),
                "score": round(score, 6),
                "mean_validation_pf": round(item["sum_pf"] / trials, 6),
                "mean_validation_expectancy_r": round(item["sum_exp"] / trials, 6),
                "mean_validation_trades": round(item["sum_trades"] / trials, 3),
                "metadata": {
                    "research_dataset": research_dataset,
                    "learning_version": LEARNING_VERSION,
                    "confidence": round(confidence, 6),
                    "raw_mean_score": round(raw_mean, 6),
                    "selection_only": True,
                    "confirmation_holdout_access": "forbidden",
                },
                "updated_at": now,
            }
        )

    if memory_rows:
        for start in range(0, len(memory_rows), 250):
            await repo.client.upsert(
                "scientist_feature_memory",
                memory_rows[start : start + 250],
                on_conflict="feature_key",
            )
    return {str(row["feature_key"]): float(row["score"]) for row in memory_rows}


async def capture_completed_selection(
    repo: Any,
    candidate: dict[str, Any],
    result: dict[str, Any],
    *,
    scientist_version: str,
) -> dict[str, Any]:
    rules = dict(candidate.get("rules") or {})
    engine_version = str(rules.get("engine_version") or candidate.get("composer_version") or "")
    if engine_version != scientist_version or not _selection_result(candidate, result):
        return {"learned": False, "reason": "not_scientist_selection"}

    payload = _event_payload(candidate, result, scientist_version)
    await repo.client.upsert("scientist_learning_events", payload, on_conflict="candidate_key")
    hypothesis_synced = await _sync_hypothesis(repo, candidate, result)
    memory = await rebuild_memory_from_ledger(repo, scientist_version, payload["research_dataset"])
    return {
        "learned": True,
        "candidate_key": payload["candidate_key"],
        "research_dataset": payload["research_dataset"],
        "contribution": payload["contribution"],
        "memory_features": len(memory),
        "hypothesis_synced": hypothesis_synced,
        "result_status": payload["result_status"],
    }


async def backfill_completed_selections(
    repo: Any,
    *,
    scientist_version: str,
    research_dataset: str,
) -> dict[str, float]:
    candidates = await repo.client.get(
        "strategy_candidates",
        params={
            "select": "candidate_key,composer_version,research_stage,rules,result_status,fitness_score,metrics,evidence,finished_at",
            "composer_version": f"eq.{scientist_version}",
            "research_stage": "eq.selection",
            "status": "eq.complete",
            "order": "finished_at.desc",
            "limit": "5000",
        },
    )
    existing = await repo.client.get(
        "scientist_learning_events",
        params={
            "select": "candidate_key",
            "scientist_version": f"eq.{scientist_version}",
            "research_dataset": f"eq.{research_dataset}",
            "limit": "10000",
        },
    )
    known = {str(row.get("candidate_key") or "") for row in existing}

    for candidate in candidates:
        rules = dict(candidate.get("rules") or {})
        market = dict(rules.get("market") or {})
        if str(market.get("research_dataset") or "legacy_15m") != research_dataset:
            continue
        candidate_key = str(candidate.get("candidate_key") or "")
        result = {
            "result_status": candidate.get("result_status"),
            "fitness_score": candidate.get("fitness_score"),
            "metrics": candidate.get("metrics") or {},
            "evidence": candidate.get("evidence") or {},
        }
        if candidate_key not in known:
            await repo.client.upsert(
                "scientist_learning_events",
                _event_payload(candidate, result, scientist_version),
                on_conflict="candidate_key",
            )
            known.add(candidate_key)
        await _sync_hypothesis(repo, candidate, result)

    return await rebuild_memory_from_ledger(repo, scientist_version, research_dataset)
