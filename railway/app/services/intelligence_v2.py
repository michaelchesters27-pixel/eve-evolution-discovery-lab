from __future__ import annotations

import math
import random
from typing import Any

# Import v3 first: it patches the deterministic research engine before the v1
# scientist binds its backtest helpers.
from app.services import backtest_v3 as research
from app.services import intelligence as v1
from app.services.composer import describe_strategy, strategy_hash

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

    def runtime_status(self) -> dict[str, Any]:
        status = super().runtime_status()
        status.update(
            {
                "version": INTELLIGENCE_VERSION,
                "observation_version": research.OBSERVATION_VERSION,
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
                ],
            }
        )
        return status

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
                snapshot_interval=self.settings.source_snapshot_interval,
                source_interval=self.settings.source_candle_interval,
            )
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
        if rows is None:
            rows = await self.row_provider()
        research.enrich_market_observations(rows)

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
        return result

    async def _latest_snapshot(self) -> dict[str, Any] | None:
        # A structure-aware live state needs recent history, not an isolated row.
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

    async def dashboard(self) -> dict[str, Any]:
        payload = await super().dashboard()
        payload["scientist"] = self.runtime_status()
        memory = payload.get("memory") or []
        structure_memory = [
            item for item in memory
            if any(token in str(item.get("feature_key") or "") for token in (
                "sweep_", "break_", "prev_day_", "session_", "displacement_", "range_", "compression_release", "three_bar"
            ))
        ]
        payload["structure_memory"] = structure_memory[:25]
        return payload
