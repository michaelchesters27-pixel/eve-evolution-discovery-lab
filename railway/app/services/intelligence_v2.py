from __future__ import annotations

import math
import random
from datetime import timedelta
from typing import Any

# Import v3 first: it patches the deterministic research engine before the v1
# scientist binds its backtest helpers.
from app.services import backtest_v3 as research
from app.services import intelligence as v1
from app.services.composer import describe_strategy, strategy_hash
from app.services.research_fabric import (
    FABRIC_DATASET,
    FABRIC_SNAPSHOT_INTERVAL,
    FABRIC_SOURCE_INTERVAL,
    FABRIC_VERSION,
    LEGACY_DATASET,
    dataset_state,
    fabric_audit,
    latest_fabric_rows,
    load_fabric_rows,
    resolve_dataset_state,
)

INTELLIGENCE_VERSION = "eve-autonomous-scientist-v2"

STRUCTURE_POOL: tuple[dict[str, Any], ...] = (
    {"type": "sweep_prior_12_high_reclaim"},
    {"type": "sweep_prior_12_low_reclaim"},
    {"type": "break_prior_12_high"},
    {"type": "break_prior_12_low"},
    {"type": "prev_day_high_sweep_reclaim"},
    {"type": "prev_day_low_sweep_reclaim"},
    {"type": "prev_day_high_break"},
    {"type": "prev_day_low_break"},
    {"type": "session_high_sweep_reclaim"},
    {"type": "session_low_sweep_reclaim"},
    {"type": "displacement_atr_min", "min": 0.35},
    {"type": "displacement_atr_min", "min": 0.55},
    {"type": "displacement_atr_min", "min": 0.80},
    {"type": "range_expansion_min", "min": 1.20},
    {"type": "range_expansion_min", "min": 1.50},
    {"type": "range_expansion_min", "min": 2.00},
    {"type": "range_position_high", "min": 0.80},
    {"type": "range_position_high", "min": 0.90},
    {"type": "range_position_low", "max": 0.20},
    {"type": "range_position_low", "max": 0.10},
    {"type": "compression_release"},
    {"type": "three_bar_same_direction"},
)

PAIR_CONFLICTS: dict[str, set[str]] = {
    "sweep_prior_12_high_reclaim": {"sweep_prior_12_low_reclaim"},
    "sweep_prior_12_low_reclaim": {"sweep_prior_12_high_reclaim"},
    "break_prior_12_high": {"break_prior_12_low"},
    "break_prior_12_low": {"break_prior_12_high"},
    "prev_day_high_sweep_reclaim": {"prev_day_low_sweep_reclaim"},
    "prev_day_low_sweep_reclaim": {"prev_day_high_sweep_reclaim"},
    "prev_day_high_break": {"prev_day_low_break"},
    "prev_day_low_break": {"prev_day_high_break"},
    "session_high_sweep_reclaim": {"session_low_sweep_reclaim"},
    "session_low_sweep_reclaim": {"session_high_sweep_reclaim"},
    "range_position_high": {"range_position_low"},
    "range_position_low": {"range_position_high"},
}

DIRECTION_RULES = (*v1.DIRECTION_RULES, "structure_direction", "three_bar_direction")


def _compatible(selected: list[dict[str, Any]], candidate: dict[str, Any]) -> bool:
    kind = str(candidate.get("type") or "")
    selected_types = {str(item.get("type") or "") for item in selected}
    if kind in selected_types:
        return False
    blocked = set(v1.CONDITION_CONFLICTS.get(kind, set())) | set(PAIR_CONFLICTS.get(kind, set()))
    return not any(item in blocked for item in selected_types)


def _proposal_rules(
    rng: random.Random,
    memory: dict[str, float],
    *,
    symbol: str,
    timeframe: str,
    snapshot_interval: str,
    source_interval: str,
) -> dict[str, Any]:
    # Reuse v1's risk/schedule/environment discipline, then replace the entry
    # grammar with the richer observation library.
    rules = v1.proposal_rules(
        rng,
        memory,
        symbol=symbol,
        timeframe=timeframe,
        snapshot_interval=snapshot_interval,
        source_interval=source_interval,
    )
    rules["engine_version"] = INTELLIGENCE_VERSION
    rules["market"]["research_source"] = "causal_market_structure_and_state_mining"

    target_count = rng.choices([2, 3, 4, 5], weights=[26, 38, 27, 9], k=1)[0]
    combined_pool = [dict(item) for item in v1.CONDITION_POOL] + [dict(item) for item in STRUCTURE_POOL]
    selected: list[dict[str, Any]] = []
    attempts = 0
    while len(selected) < target_count and attempts < 150:
        attempts += 1
        available = [item for item in combined_pool if _compatible(selected, item)]
        if not available:
            break
        weights: list[float] = []
        for item in available:
            weight = v1.memory_weight(memory, v1.condition_key(item))
            if str(item.get("type") or "") in research.STRUCTURE_CONDITION_TYPES:
                # Exploration bonus: structure is new, so lack of historical memory
                # must not make EVE ignore it before it has evidence.
                weight *= 1.35
            weights.append(weight)
        selected.append(dict(v1.weighted_choice(rng, available, weights)))

    direction_values = list(DIRECTION_RULES)
    direction_weights = [v1.memory_weight(memory, f"direction:{item}") for item in direction_values]
    # Ensure EVE spends meaningful research budget on context-derived direction.
    for index, item in enumerate(direction_values):
        if item in {"structure_direction", "three_bar_direction"}:
            direction_weights[index] *= 1.25

    rules["entry"] = {
        "direction_rule": str(v1.weighted_choice(rng, direction_values, direction_weights)),
        "condition_mode": "all",
        "conditions": selected,
    }
    return rules


class IntelligenceDirector(v1.IntelligenceDirector):
    """Scientist v2: self-learning hypotheses with causal market structure."""

    def __init__(self, settings: Any, repo: Any, row_provider: Any) -> None:
        super().__init__(settings, repo, row_provider)
        self.active_dataset = LEGACY_DATASET
        self.active_snapshot_interval = str(settings.source_snapshot_interval)
        self.active_source_interval = str(settings.source_candle_interval)
        self.dataset_status = "pending_cutover"
        self.dataset_rows = 0
        self.cutover_at: str | None = None
        self._fabric_rows_cache: list[dict[str, Any]] = []
        self._fabric_cache_at = None

    def runtime_status(self) -> dict[str, Any]:
        status = super().runtime_status()
        status.update(
            {
                "version": INTELLIGENCE_VERSION,
                "observation_version": research.OBSERVATION_VERSION,
                "active_dataset": self.active_dataset,
                "active_snapshot_interval": self.active_snapshot_interval,
                "active_source_interval": self.active_source_interval,
                "dataset_status": self.dataset_status,
                "dataset_rows": self.dataset_rows,
                "cutover_at": self.cutover_at,
                "capabilities": [
                    "rolling_structure",
                    "liquidity_sweep_reclaims",
                    "previous_day_levels",
                    "session_sweeps",
                    "displacement",
                    "range_expansion",
                    "compression_release",
                    "multi_candle_sequences",
                    "moving_block_monte_carlo",
                    "actual_entry_time_locking",
                    "verified_every_m5_fabric",
                ],
            }
        )
        return status

    async def _select_science_rows(self, supplied_rows: list[dict[str, Any]] | None) -> list[dict[str, Any]]:
        audit: dict[str, Any] = {}
        try:
            audit = await fabric_audit(self.repo)
            state = await resolve_dataset_state(self.repo, INTELLIGENCE_VERSION, audit)
        except Exception:
            # A temporary audit read failure must not erase a previously verified
            # cutover. Use the persisted authority row; hard failures are written
            # there as suspended_integrity when the audit is available again.
            state = await dataset_state(self.repo, INTELLIGENCE_VERSION)

        use_fabric = (
            str(state.get("active_dataset") or "") == FABRIC_DATASET
            and str(state.get("status") or "") == "active"
        )
        self.dataset_status = str(state.get("status") or "pending_cutover")
        self.cutover_at = str(state.get("cutover_at") or "") or None

        if use_fabric:
            fresh_until = (self._fabric_cache_at or v1.utc_now() - timedelta(days=1)) + timedelta(
                minutes=self.settings.row_cache_minutes
            )
            if not self._fabric_rows_cache or v1.utc_now() >= fresh_until:
                self._fabric_rows_cache = await load_fabric_rows(
                    self.repo,
                    self.settings.source_symbol,
                    complete_only=True,
                )
                research.enrich_market_observations(self._fabric_rows_cache)
                self._fabric_cache_at = v1.utc_now()
            self.active_dataset = FABRIC_DATASET
            self.active_snapshot_interval = FABRIC_SNAPSHOT_INTERVAL
            self.active_source_interval = FABRIC_SOURCE_INTERVAL
            self.dataset_rows = len(self._fabric_rows_cache)
            return self._fabric_rows_cache

        rows = supplied_rows if supplied_rows is not None else await self.row_provider()
        research.enrich_market_observations(rows)
        self.active_dataset = LEGACY_DATASET
        self.active_snapshot_interval = str(self.settings.source_snapshot_interval)
        self.active_source_interval = str(self.settings.source_candle_interval)
        self.dataset_rows = len(rows)
        return rows

    async def _rebuild_memory(self) -> dict[str, float]:
        rows = await self.repo.client.get(
            "strategy_candidates",
            params={
                "select": "candidate_key,rules,result_status,fitness_score,metrics",
                "composer_version": f"eq.{INTELLIGENCE_VERSION}",
                "research_stage": "eq.selection",
                "status": "eq.complete",
                "order": "finished_at.desc",
                "limit": "2500",
            },
        )
        aggregates: dict[str, dict[str, float]] = {}
        for row in rows:
            rules = dict(row.get("rules") or {})
            market = dict(rules.get("market") or {})
            row_dataset = str(market.get("research_dataset") or LEGACY_DATASET)
            if row_dataset != self.active_dataset:
                continue
            metrics = dict(row.get("metrics") or {})
            validation = dict(metrics.get("validation") or {})
            pf = float(v1.number(validation.get("profit_factor")))
            expectancy = float(v1.number(validation.get("expectancy_r")))
            trades = float(v1.number(validation.get("trades")))
            result_status = str(row.get("result_status") or "rejected")
            status_bonus = {
                "elite": 3.5,
                "validated": 2.5,
                "promising": 1.25,
                "rejected": -0.5,
            }.get(result_status, -0.25)
            contribution = v1.clamp((pf - 1.0) * 2.0 + expectancy * 10.0 + status_bonus, -4.0, 6.0)
            for feature in v1.rule_feature_keys(rules):
                item = aggregates.setdefault(
                    feature,
                    {"trials": 0.0, "positive_trials": 0.0, "sum_score": 0.0, "sum_pf": 0.0, "sum_exp": 0.0, "sum_trades": 0.0},
                )
                item["trials"] += 1.0
                item["positive_trials"] += 1.0 if contribution > 0 else 0.0
                item["sum_score"] += contribution
                item["sum_pf"] += pf
                item["sum_exp"] += expectancy
                item["sum_trades"] += trades

        memory_rows: list[dict[str, Any]] = []
        for feature, item in aggregates.items():
            trials = max(1.0, item["trials"])
            memory_rows.append(
                {
                    "feature_key": feature,
                    "scientist_version": INTELLIGENCE_VERSION,
                    "trials": int(item["trials"]),
                    "positive_trials": int(item["positive_trials"]),
                    "score": round(item["sum_score"] / trials, 6),
                    "mean_validation_pf": round(item["sum_pf"] / trials, 6),
                    "mean_validation_expectancy_r": round(item["sum_exp"] / trials, 6),
                    "mean_validation_trades": round(item["sum_trades"] / trials, 3),
                    "metadata": {
                        "research_dataset": self.active_dataset,
                        "snapshot_interval": self.active_snapshot_interval,
                    },
                    "updated_at": v1.utc_now().isoformat(),
                }
            )
        if memory_rows:
            for start in range(0, len(memory_rows), 250):
                await self.repo.client.upsert(
                    "scientist_feature_memory",
                    memory_rows[start : start + 250],
                    on_conflict="feature_key",
                )
        self.memory_features = len(memory_rows)
        return {row["feature_key"]: float(row["score"]) for row in memory_rows}

    async def _load_memory(self) -> dict[str, float]:
        rows = await self.feature_memory(500)
        self.memory_features = len(rows)
        return {str(row.get("feature_key")): float(v1.number(row.get("score"))) for row in rows}

    def _proposals(
        self,
        memory: dict[str, float],
        existing: set[str],
        *,
        seed: int,
    ) -> list[dict[str, Any]]:
        rng = random.Random(seed)
        proposals: list[dict[str, Any]] = []
        seen = set(existing)
        attempts = 0
        target = self.proposal_count
        while len(proposals) < target and attempts < target * 60:
            attempts += 1
            rules = _proposal_rules(
                rng,
                memory,
                symbol=self.settings.source_symbol,
                timeframe=self.settings.research_timeframe,
                snapshot_interval=self.active_snapshot_interval,
                source_interval=self.active_source_interval,
            )
            rules["market"]["research_dataset"] = self.active_dataset
            if self.active_dataset == FABRIC_DATASET:
                rules["market"]["fabric_version"] = FABRIC_VERSION
            digest = strategy_hash(rules)
            key = f"science-{digest[:32]}"
            if key in seen:
                continue
            seen.add(key)
            structure_count = sum(
                str(item.get("type") or "") in research.STRUCTURE_CONDITION_TYPES
                for item in (rules.get("entry") or {}).get("conditions") or []
                if isinstance(item, dict)
            )
            proposals.append(
                {
                    "hypothesis_key": key,
                    "candidate_key": f"candidate-{digest[:28]}",
                    "rules": rules,
                    "hypothesis": describe_strategy(rules),
                    "feature_keys": [
                        *v1.rule_feature_keys(rules),
                        f"scientist:structure_conditions:{structure_count}",
                    ],
                }
            )
        return proposals

    async def run_science_once(self, rows: list[dict[str, Any]] | None = None) -> dict[str, Any]:
        rows = await self._select_science_rows(rows)

        # v1's persisted-version field is still module-level. Scope the v2 value
        # to this one scientist cycle and restore it immediately so importing v2
        # never mutates v1 behaviour or its tests/processes globally.
        previous_version = v1.INTELLIGENCE_VERSION
        v1.INTELLIGENCE_VERSION = INTELLIGENCE_VERSION
        try:
            result = await super().run_science_once(rows)
        finally:
            v1.INTELLIGENCE_VERSION = previous_version
        result["scientist_version"] = INTELLIGENCE_VERSION
        result["observation_version"] = research.OBSERVATION_VERSION
        result["research_dataset"] = self.active_dataset
        result["snapshot_interval"] = self.active_snapshot_interval
        result["dataset_rows"] = self.dataset_rows
        return result

    async def _latest_snapshot(self) -> dict[str, Any] | None:
        # A structure-aware live state needs recent history, not an isolated row.
        state = await dataset_state(self.repo, INTELLIGENCE_VERSION)
        use_fabric = (
            str(state.get("active_dataset") or "") == FABRIC_DATASET
            and str(state.get("status") or "") == "active"
        )
        if use_fabric:
            rows = await latest_fabric_rows(self.repo, self.settings.source_symbol, limit=120)
            if not rows:
                return None
            enriched = research.enrich_market_observations(list(reversed(rows)))
            return dict(enriched[-1]) if enriched else None

        rows = await self.repo.client.get(
            "source_snapshots",
            params={
                "select": "*",
                "symbol": f"eq.{self.settings.source_symbol}",
                "snapshot_interval": f"eq.{self.settings.source_snapshot_interval}",
                "source_interval": f"eq.{self.settings.source_candle_interval}",
                "order": "candle_time.desc",
                "limit": "120",
            },
        )
        if not rows:
            return None
        enriched = research.enrich_market_observations(list(reversed(rows)))
        return dict(enriched[-1]) if enriched else None

    async def feature_memory(self, limit: int = 100) -> list[dict[str, Any]]:
        rows = await self.repo.client.get(
            "scientist_feature_memory",
            params={
                "select": "*",
                "scientist_version": f"eq.{INTELLIGENCE_VERSION}",
                "order": "score.desc",
                "limit": "1000",
            },
        )
        if self.active_dataset == FABRIC_DATASET:
            rows = [
                row for row in rows
                if str((row.get("metadata") or {}).get("research_dataset") or "") == FABRIC_DATASET
            ]
        return rows[: max(1, min(500, int(limit)))]

    async def dashboard(self) -> dict[str, Any]:
        payload = await super().dashboard()
        payload["scientist"] = self.runtime_status()
        memory = payload.get("top_learned_features") or []
        structure_memory = [
            item for item in memory
            if any(token in str(item.get("feature_key") or "") for token in (
                "sweep_", "break_", "prev_day_", "session_", "displacement_", "range_", "compression_release", "three_bar"
            ))
        ]
        payload["structure_memory"] = structure_memory[:25]
        return payload
