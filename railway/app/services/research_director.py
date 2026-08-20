from __future__ import annotations

from copy import deepcopy
import math
import random
from typing import Any

from app.services import backtest_v3 as research
from app.services import intelligence as v1
from app.services import mtf_reasoning as _mtf_reasoning  # noqa: F401 - shared MTF semantics
from app.services import intelligence_v2 as scientist
from app.services.composer import describe_strategy, strategy_hash

RESEARCH_DIRECTOR_VERSION = "eve-research-director-v1"
ABLATION_VERSION = "eve-development-ablation-v1"
INTERACTION_VERSION = "eve-feature-interaction-learning-v1"


def feature_family(feature_key: str) -> str:
    key = str(feature_key or "")
    if key.startswith("condition:mtf_") or key.startswith("direction:mtf_"):
        return "multi_timeframe"
    if any(
        token in key
        for token in (
            "sweep_prior_",
            "break_prior_",
            "prev_day_",
            "session_high_",
            "session_low_",
            "displacement_",
            "range_expansion_",
            "range_position_",
            "compression_release",
            "three_bar_",
            "direction:structure_direction",
            "direction:three_bar_direction",
        )
    ):
        return "market_structure"
    if key.startswith("schedule:"):
        return "time_session"
    if key.startswith("environment:"):
        return "regime_context"
    if key.startswith("direction:"):
        return "direction_model"
    if key.startswith("condition:"):
        return "candle_state"
    return "other"


def interaction_key(left: str, right: str) -> str:
    a, b = sorted((str(left), str(right)))
    return f"interaction:{a}||{b}"


def build_director_memory(memory_rows: list[dict[str, Any]]) -> tuple[dict[str, float], dict[str, Any]]:
    """Shrink noisy feature scores and add cautious family-level steering."""

    base: dict[str, dict[str, float | str]] = {}
    families: dict[str, dict[str, float]] = {}
    for row in memory_rows:
        key = str(row.get("feature_key") or "")
        if not key:
            continue
        trials = max(0, int(v1.number(row.get("trials"))))
        positives = max(0, int(v1.number(row.get("positive_trials"))))
        raw_score = float(v1.number(row.get("score")))
        reliability = math.sqrt(trials / (trials + 8.0)) if trials > 0 else 0.0
        shrunk = v1.clamp(raw_score * reliability, -4.0, 6.0)
        family = feature_family(key)
        base[key] = {
            "family": family,
            "trials": float(trials),
            "positives": float(positives),
            "raw_score": raw_score,
            "reliability": reliability,
            "shrunk_score": shrunk,
        }
        agg = families.setdefault(
            family,
            {"trials": 0.0, "positives": 0.0, "weighted_score": 0.0, "weight": 0.0, "features": 0.0},
        )
        weight = max(1.0, float(trials))
        agg["trials"] += float(trials)
        agg["positives"] += float(positives)
        agg["weighted_score"] += shrunk * weight
        agg["weight"] += weight
        agg["features"] += 1.0

    family_scores: dict[str, float] = {}
    family_plan: list[dict[str, Any]] = []
    for family, agg in families.items():
        mean = agg["weighted_score"] / max(1.0, agg["weight"])
        confidence = min(1.0, agg["trials"] / 12.0)
        score = v1.clamp(mean * confidence, -2.5, 3.0)
        family_scores[family] = score
        family_plan.append(
            {
                "family": family,
                "trials": int(agg["trials"]),
                "features": int(agg["features"]),
                "positive_rate": round(agg["positives"] / max(1.0, agg["trials"]), 4),
                "evidence_score": round(score, 6),
            }
        )

    adjusted: dict[str, float] = {}
    for key, item in base.items():
        family = str(item["family"])
        family_bias = family_scores.get(family, 0.0) * 0.35
        adjusted[key] = v1.clamp(float(item["shrunk_score"]) + family_bias, -4.0, 6.0)

    family_plan.sort(key=lambda item: (float(item["evidence_score"]), int(item["trials"])), reverse=True)
    plan = {
        "version": RESEARCH_DIRECTOR_VERSION,
        "memory_features": len(adjusted),
        "families": family_plan,
        "strongest_families": [item["family"] for item in family_plan if float(item["evidence_score"]) > 0][:3],
        "weakest_families": [item["family"] for item in reversed(family_plan) if float(item["evidence_score"]) < 0][:3],
        "policy": "shrink single-trial evidence; exploit repeated positive families; retain exploration floor",
    }
    return adjusted, plan


def build_interaction_memory(rows: list[dict[str, Any]]) -> tuple[dict[str, float], dict[str, Any]]:
    """Build cautious pairwise priors from selection-only interaction evidence."""

    scores: dict[str, float] = {}
    ranked: list[dict[str, Any]] = []
    for row in rows:
        left = str(row.get("feature_a") or "")
        right = str(row.get("feature_b") or "")
        if not left or not right or left == right:
            continue
        trials = max(0, int(v1.number(row.get("trials"))))
        positives = max(0, int(v1.number(row.get("positive_trials"))))
        raw = float(v1.number(row.get("score")))
        reliability = math.sqrt(trials / (trials + 12.0)) if trials > 0 else 0.0
        shrunk = v1.clamp(raw * reliability, -3.0, 4.0)
        key = interaction_key(left, right)
        scores[key] = shrunk
        ranked.append(
            {
                "feature_a": left,
                "feature_b": right,
                "trials": trials,
                "positive_trials": positives,
                "positive_rate": round(positives / max(1, trials), 4),
                "raw_score": round(raw, 6),
                "evidence_score": round(shrunk, 6),
            }
        )
    ranked.sort(key=lambda item: (abs(float(item["evidence_score"])), int(item["trials"])), reverse=True)
    return scores, {
        "version": INTERACTION_VERSION,
        "interactions": len(scores),
        "top_evidence": ranked[:20],
        "policy": "pairwise selection evidence only; stronger shrinkage than single features; 30% proposal exploration retained",
        "confirmation_holdout_access": "forbidden",
    }


def proposal_interaction_score(rules: dict[str, Any], scores: dict[str, float]) -> float:
    features = sorted(set(v1.rule_feature_keys(rules)))
    hits: list[float] = []
    for i, left in enumerate(features):
        for right in features[i + 1 :]:
            key = interaction_key(left, right)
            if key in scores:
                hits.append(float(scores[key]))
    if not hits:
        return 0.0
    # Normalise so a strategy with more conditions does not win simply because
    # it creates more feature pairs.
    return v1.clamp(sum(hits) / math.sqrt(len(hits)), -4.0, 5.0)


def _feature_keys(rules: dict[str, Any]) -> list[str]:
    keys = list(v1.rule_feature_keys(rules))
    conditions = [item for item in (rules.get("entry") or {}).get("conditions") or [] if isinstance(item, dict)]
    structure_count = sum(str(item.get("type") or "") in research.STRUCTURE_CONDITION_TYPES for item in conditions)
    keys.append(f"scientist:structure_conditions:{structure_count}")
    return keys


def _qualifies(self: Any, metrics: Any) -> bool:
    return (
        metrics.trades >= self.minimum_development_trades
        and metrics.profit_factor >= self.minimum_development_pf
        and metrics.expectancy_r >= self.minimum_development_expectancy
        and metrics.positive_year_rate >= 0.50
    )


def ablate_hypothesis(self: Any, development: list[dict[str, Any]], item: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    """Greedy backward elimination using development data only."""

    working = deepcopy(item)
    current_rules = deepcopy(working["rules"])
    current_metrics = research.evaluate_segment(development, current_rules)
    current_score = float(v1.development_score(current_metrics))
    original_conditions = [dict(x) for x in (current_rules.get("entry") or {}).get("conditions") or [] if isinstance(x, dict)]
    trace: list[dict[str, Any]] = []

    while True:
        conditions = [dict(x) for x in (current_rules.get("entry") or {}).get("conditions") or [] if isinstance(x, dict)]
        if len(conditions) <= 1:
            break
        candidates: list[tuple[float, Any, dict[str, Any], int]] = []
        for index in range(len(conditions)):
            trial_rules = deepcopy(current_rules)
            trial_conditions = [dict(x) for i, x in enumerate(conditions) if i != index]
            trial_rules.setdefault("entry", {})["conditions"] = trial_conditions
            metrics = research.evaluate_segment(development, trial_rules)
            score = float(v1.development_score(metrics))
            if not _qualifies(self, metrics):
                continue
            if metrics.profit_factor < current_metrics.profit_factor - 0.05:
                continue
            if metrics.expectancy_r < current_metrics.expectancy_r - 0.01:
                continue
            if score < current_score - 3.0:
                continue
            candidates.append((score, metrics, trial_rules, index))

        if not candidates:
            break
        candidates.sort(key=lambda value: value[0], reverse=True)
        score, metrics, trial_rules, removed_index = candidates[0]
        removed = conditions[removed_index]
        trace.append(
            {
                "removed": v1.condition_key(removed),
                "before_score": round(current_score, 6),
                "after_score": round(float(score), 6),
                "before_pf": round(float(current_metrics.profit_factor), 6),
                "after_pf": round(float(metrics.profit_factor), 6),
                "before_expectancy_r": round(float(current_metrics.expectancy_r), 6),
                "after_expectancy_r": round(float(metrics.expectancy_r), 6),
            }
        )
        current_rules = trial_rules
        current_metrics = metrics
        current_score = float(score)

    removed_count = max(0, len(original_conditions) - len((current_rules.get("entry") or {}).get("conditions") or []))
    if removed_count:
        digest = strategy_hash(current_rules)
        working["rules"] = current_rules
        working["hypothesis_key"] = f"science-{digest[:32]}"
        working["candidate_key"] = f"candidate-{digest[:28]}"
        working["hypothesis"] = describe_strategy(current_rules)
        working["feature_keys"] = _feature_keys(current_rules)
        working["development_metrics"] = current_metrics.as_dict()
        working["development_score"] = round(current_score, 6)
        working["qualified"] = _qualifies(self, current_metrics)

    summary = {
        "version": ABLATION_VERSION,
        "original_conditions": len(original_conditions),
        "final_conditions": len((current_rules.get("entry") or {}).get("conditions") or []),
        "removed_conditions": removed_count,
        "trace": trace,
        "data_access": "development_only",
        "confirmation_holdout_access": "forbidden",
    }
    return working, summary


class ResearchDirectedIntelligenceDirector(scientist.IntelligenceDirector):
    """Scientist v2 with research steering, interaction learning and ablation."""

    def __init__(self, settings: Any, repo: Any, row_provider: Any) -> None:
        super().__init__(settings, repo, row_provider)
        self.research_director_plan: dict[str, Any] = {"version": RESEARCH_DIRECTOR_VERSION, "families": []}
        self.interaction_scores: dict[str, float] = {}
        self.interaction_memory: dict[str, Any] = {"version": INTERACTION_VERSION, "interactions": 0, "top_evidence": []}
        self.last_ablation_summary: dict[str, Any] = {
            "version": ABLATION_VERSION,
            "hypotheses_checked": 0,
            "hypotheses_simplified": 0,
            "conditions_removed": 0,
        }

    async def _load_interactions(self) -> None:
        try:
            rows = await self.repo.client.get(
                "scientist_interaction_memory",
                params={
                    "select": "feature_a,feature_b,trials,positive_trials,score,mean_validation_pf,mean_validation_expectancy_r",
                    "scientist_version": f"eq.{scientist.INTELLIGENCE_VERSION}",
                    "research_dataset": f"eq.{self.active_dataset}",
                    "order": "trials.desc",
                    "limit": "5000",
                },
            )
        except Exception:
            rows = []
        self.interaction_scores, self.interaction_memory = build_interaction_memory(rows)

    async def _load_memory(self) -> dict[str, float]:
        rows = await self.feature_memory(500)
        self.memory_features = len(rows)
        adjusted, plan = build_director_memory(rows)
        self.research_director_plan = plan
        await self._load_interactions()
        return adjusted

    async def _rebuild_memory(self) -> dict[str, float]:
        await super()._rebuild_memory()
        return await self._load_memory()

    def _proposals(self, memory: dict[str, float], existing: set[str], *, seed: int) -> list[dict[str, Any]]:
        """Oversample then rank by learned pair interactions, retaining exploration."""

        rng = random.Random(seed)
        target = self.proposal_count
        pool_target = min(max(target * 4, target + 12), 500)
        pool: dict[str, dict[str, Any]] = {}
        attempts = 0
        while len(pool) < pool_target and attempts < pool_target * 80:
            attempts += 1
            rules = scientist._proposal_rules(
                rng,
                memory,
                symbol=self.settings.source_symbol,
                timeframe=self.settings.research_timeframe,
                snapshot_interval=self.active_snapshot_interval,
                source_interval=self.active_source_interval,
            )
            rules["market"]["research_dataset"] = self.active_dataset
            if self.active_dataset == scientist.FABRIC_DATASET:
                rules["market"]["fabric_version"] = scientist.FABRIC_VERSION
            digest = strategy_hash(rules)
            key = f"science-{digest[:32]}"
            if key in existing or key in pool:
                continue
            pair_score = proposal_interaction_score(rules, self.interaction_scores)
            conditions = [item for item in (rules.get("entry") or {}).get("conditions") or [] if isinstance(item, dict)]
            structure_count = sum(str(item.get("type") or "") in research.STRUCTURE_CONDITION_TYPES for item in conditions)
            pool[key] = {
                "hypothesis_key": key,
                "candidate_key": f"candidate-{digest[:28]}",
                "rules": rules,
                "hypothesis": describe_strategy(rules),
                "feature_keys": [*v1.rule_feature_keys(rules), f"scientist:structure_conditions:{structure_count}"],
                "interaction_prior_score": round(pair_score, 6),
            }

        candidates = list(pool.values())
        candidates.sort(key=lambda item: float(item.get("interaction_prior_score") or 0.0), reverse=True)
        exploit_count = min(len(candidates), int(round(target * 0.70))) if self.interaction_scores else 0
        selected = candidates[:exploit_count]
        remaining = candidates[exploit_count:]
        rng.shuffle(remaining)
        selected.extend(remaining[: max(0, target - len(selected))])
        return selected[:target]

    def _screen_sync(self, development: list[dict[str, Any]], proposals: list[dict[str, Any]]) -> list[dict[str, Any]]:
        screened = super()._screen_sync(development, proposals)
        qualified = [item for item in screened if item.get("qualified")]
        limit = min(len(qualified), max(4, int(self.promotion_count) * 2))
        summaries: list[dict[str, Any]] = []
        replacements: dict[str, dict[str, Any]] = {}

        for item in qualified[:limit]:
            parent_key = str(item.get("hypothesis_key") or "")
            simplified, summary = ablate_hypothesis(self, development, item)
            summary["parent_hypothesis_key"] = parent_key
            summary["result_hypothesis_key"] = simplified.get("hypothesis_key")
            summaries.append(summary)
            replacements[parent_key] = simplified

        output = [replacements.get(str(item.get("hypothesis_key") or ""), item) for item in screened]
        output.sort(key=lambda item: float(item.get("development_score") or 0.0), reverse=True)
        self.last_ablation_summary = {
            "version": ABLATION_VERSION,
            "hypotheses_checked": len(summaries),
            "hypotheses_simplified": sum(1 for item in summaries if int(item.get("removed_conditions") or 0) > 0),
            "conditions_removed": sum(int(item.get("removed_conditions") or 0) for item in summaries),
            "examples": [item for item in summaries if int(item.get("removed_conditions") or 0) > 0][:5],
            "data_access": "development_only",
            "confirmation_holdout_access": "forbidden",
        }
        return output

    def runtime_status(self) -> dict[str, Any]:
        status = super().runtime_status()
        capabilities = list(status.get("capabilities") or [])
        for capability in (
            "evidence_weighted_research_direction",
            "pairwise_feature_interaction_learning",
            "development_only_ablation",
            "strategy_simplification",
        ):
            if capability not in capabilities:
                capabilities.append(capability)
        status["capabilities"] = capabilities
        status["research_director_version"] = RESEARCH_DIRECTOR_VERSION
        status["research_director"] = self.research_director_plan
        status["interaction_learning_version"] = INTERACTION_VERSION
        status["interaction_memory"] = self.interaction_memory
        status["ablation"] = self.last_ablation_summary
        return status

    async def run_science_once(self, rows: list[dict[str, Any]] | None = None) -> dict[str, Any]:
        result = await super().run_science_once(rows)
        if not result.get("ok"):
            return result
        director = {
            "version": RESEARCH_DIRECTOR_VERSION,
            "plan": self.research_director_plan,
            "interaction_memory": self.interaction_memory,
            "ablation": self.last_ablation_summary,
        }
        result["research_director"] = director
        try:
            strongest = ", ".join(self.research_director_plan.get("strongest_families") or []) or "exploration"
            await self.repo.event(
                "info",
                "research_director",
                (
                    f"Research Director steered this cycle toward {strongest}; used "
                    f"{self.interaction_memory.get('interactions', 0)} learned feature interactions; ablation simplified "
                    f"{self.last_ablation_summary.get('hypotheses_simplified', 0)} hypotheses and removed "
                    f"{self.last_ablation_summary.get('conditions_removed', 0)} redundant conditions."
                ),
                {
                    "research_director_version": RESEARCH_DIRECTOR_VERSION,
                    "interaction_learning_version": INTERACTION_VERSION,
                    "active_dataset": self.active_dataset,
                    "memory_features": self.memory_features,
                    "interaction_memory": self.interaction_memory,
                    "family_plan": self.research_director_plan.get("families") or [],
                    "ablation": self.last_ablation_summary,
                    "confirmation_holdout_access": "forbidden",
                },
            )
        except Exception:
            pass
        return result
