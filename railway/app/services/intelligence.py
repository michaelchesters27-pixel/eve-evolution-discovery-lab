from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import math
import os
import random
from datetime import datetime, timedelta, timezone
from typing import Any, Awaitable, Callable

from app.services.backtest import (
    candidate_direction,
    chronological_segments,
    environment_matches,
    evaluate_segment,
    number,
    recipe_condition_matches,
    row_is_eligible,
    schedule_matches,
)
from app.services.composer import describe_strategy, strategy_hash
from app.services.repository import DiscoveryRepository

logger = logging.getLogger(__name__)

INTELLIGENCE_VERSION = "eve-autonomous-scientist-v1"

CONDITION_CONFLICTS = {
    "direction_matches_trend12": {"direction_opposes_trend12"},
    "direction_opposes_trend12": {"direction_matches_trend12"},
    "alignment_matches_direction": {"alignment_opposes_direction"},
    "alignment_opposes_direction": {"alignment_matches_direction"},
}

CONDITION_POOL: tuple[dict[str, Any], ...] = (
    {"type": "direction_matches_trend12"},
    {"type": "direction_opposes_trend12"},
    {"type": "alignment_abs_min", "min": 1},
    {"type": "alignment_abs_min", "min": 2},
    {"type": "alignment_abs_min", "min": 3},
    {"type": "alignment_matches_direction"},
    {"type": "alignment_opposes_direction"},
    {"type": "return_3_abs_min", "threshold": 0.0025},
    {"type": "return_3_abs_min", "threshold": 0.005},
    {"type": "return_3_abs_min", "threshold": 0.01},
    {"type": "return_3_abs_min", "threshold": 0.02},
    {"type": "return_3_matches_direction"},
    {"type": "impulse_1_vs_3", "ratio": 0.25},
    {"type": "impulse_1_vs_3", "ratio": 0.50},
    {"type": "impulse_1_vs_3", "ratio": 0.75},
    {"type": "close_location_extreme", "edge": 0.12},
    {"type": "close_location_extreme", "edge": 0.20},
    {"type": "close_location_extreme", "edge": 0.30},
    {"type": "wick_body_ratio_min", "ratio": 1.20},
    {"type": "wick_body_ratio_min", "ratio": 1.50},
    {"type": "wick_body_ratio_min", "ratio": 2.00},
    {"type": "wick_body_ratio_min", "ratio": 2.50},
    {"type": "trend12_trend48_agree"},
)

DIRECTION_RULES = (
    "current_direction",
    "alignment_direction",
    "trend_direction",
    "reverse_current",
    "wick_reversal",
)

STOP_GRID = (0.65, 0.75, 0.90, 1.00, 1.15, 1.25, 1.50)
TARGET_GRID = (1.00, 1.25, 1.50, 1.75, 2.00, 2.50, 3.00)
HORIZONS = (15, 60, 240)
COOLDOWNS = (5, 15, 30, 60, 120, 240)


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def canonical(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)


def clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def env_int(name: str, default: int, low: int, high: int) -> int:
    try:
        value = int(os.getenv(name, str(default)))
    except (TypeError, ValueError):
        value = default
    return max(low, min(high, value))


def env_float(name: str, default: float, low: float, high: float) -> float:
    try:
        value = float(os.getenv(name, str(default)))
    except (TypeError, ValueError):
        value = default
    return max(low, min(high, value))


def condition_key(condition: dict[str, Any]) -> str:
    kind = str(condition.get("type") or "unknown")
    params = [(key, condition[key]) for key in sorted(condition) if key != "type"]
    suffix = ",".join(f"{key}={value}" for key, value in params)
    return f"condition:{kind}" + (f":{suffix}" if suffix else "")


def rule_feature_keys(rules: dict[str, Any]) -> list[str]:
    entry = dict(rules.get("entry") or {})
    schedule = dict(rules.get("schedule") or {})
    environment = dict(rules.get("environment") or {})
    features = [f"direction:{entry.get('direction_rule') or 'current_direction'}"]

    for condition in entry.get("conditions") or []:
        if isinstance(condition, dict):
            features.append(condition_key(condition))

    sessions = [str(item) for item in schedule.get("sessions") or []]
    hours = [int(number(item)) for item in schedule.get("hours_utc") or []]
    if sessions:
        features.append(f"schedule:session:{sessions[0]}")
    elif hours and len(hours) < 24:
        features.append(f"schedule:hours:{min(hours)}-{max(hours)}")
    else:
        features.append("schedule:all_day")

    trend12 = str(environment.get("trend_12") or "any")
    trend48 = str(environment.get("trend_48") or "any")
    compression = str(environment.get("compression") or "any")
    regimes = [str(item) for item in environment.get("regimes") or []]
    if trend12 != "any":
        features.append(f"environment:trend12:{trend12}")
    if trend48 != "any":
        features.append(f"environment:trend48:{trend48}")
    if compression != "any":
        features.append(f"environment:compression:{compression}")
    if regimes:
        features.append(f"environment:regime:{regimes[0]}")
    return features


def weighted_choice(rng: random.Random, values: list[Any], weights: list[float]) -> Any:
    return rng.choices(values, weights=weights, k=1)[0]


def memory_weight(memory: dict[str, float], key: str) -> float:
    score = clamp(float(memory.get(key, 0.0)), -4.0, 6.0)
    return clamp(math.exp(score * 0.24), 0.25, 4.25)


def conditions_compatible(selected: list[dict[str, Any]], candidate: dict[str, Any]) -> bool:
    kind = str(candidate.get("type") or "")
    selected_types = {str(item.get("type") or "") for item in selected}
    if kind in selected_types:
        return False
    blocked = CONDITION_CONFLICTS.get(kind, set())
    return not any(item in blocked for item in selected_types)


def schedule_options() -> list[dict[str, Any]]:
    weekdays = [1, 2, 3, 4, 5]
    months = list(range(1, 13))
    return [
        {
            "weekdays": weekdays,
            "months": months,
            "sessions": [],
            "hours_utc": list(range(24)),
            "schedule_kind": "all_day",
            "everyday_target": True,
        },
        {
            "weekdays": weekdays,
            "months": months,
            "sessions": ["london"],
            "hours_utc": [],
            "schedule_kind": "session",
            "everyday_target": True,
        },
        {
            "weekdays": weekdays,
            "months": months,
            "sessions": ["new_york"],
            "hours_utc": [],
            "schedule_kind": "session",
            "everyday_target": True,
        },
        {
            "weekdays": weekdays,
            "months": months,
            "sessions": ["asia"],
            "hours_utc": [],
            "schedule_kind": "session",
            "everyday_target": True,
        },
        {
            "weekdays": weekdays,
            "months": months,
            "sessions": [],
            "hours_utc": [6, 7, 8, 9, 10],
            "schedule_kind": "hour_window",
            "everyday_target": True,
        },
        {
            "weekdays": weekdays,
            "months": months,
            "sessions": [],
            "hours_utc": [12, 13, 14, 15, 16],
            "schedule_kind": "hour_window",
            "everyday_target": True,
        },
        {
            "weekdays": weekdays,
            "months": months,
            "sessions": [],
            "hours_utc": [17, 18, 19, 20, 21],
            "schedule_kind": "hour_window",
            "everyday_target": True,
        },
    ]


def schedule_feature(schedule: dict[str, Any]) -> str:
    sessions = schedule.get("sessions") or []
    hours = schedule.get("hours_utc") or []
    if sessions:
        return f"schedule:session:{sessions[0]}"
    if hours and len(hours) < 24:
        return f"schedule:hours:{min(hours)}-{max(hours)}"
    return "schedule:all_day"


def choose_schedule(rng: random.Random, memory: dict[str, float]) -> dict[str, Any]:
    options = schedule_options()
    weights = [memory_weight(memory, schedule_feature(item)) for item in options]
    weights[0] *= 1.8
    return dict(weighted_choice(rng, options, weights))


def choose_environment(rng: random.Random, memory: dict[str, float]) -> dict[str, Any]:
    environment: dict[str, Any] = {
        "regimes": [],
        "trend_12": "any",
        "trend_48": "any",
        "compression": "any",
        "min_alignment_abs": 0,
        "alignment_sign": "any",
        "streak": "any",
    }
    options: list[tuple[str, str, Any]] = [
        ("trend_12", "environment:trend12:directional", "directional"),
        ("trend_12", "environment:trend12:flat", "flat"),
        ("trend_48", "environment:trend48:directional", "directional"),
        ("compression", "environment:compression:compressed", "compressed"),
        ("compression", "environment:compression:expanded", "expanded"),
        ("regimes", "environment:regime:trend_up", ["trend_up"]),
        ("regimes", "environment:regime:trend_down", ["trend_down"]),
        ("regimes", "environment:regime:range", ["range"]),
        ("regimes", "environment:regime:high_volatility", ["high_volatility"]),
    ]
    if rng.random() < 0.55:
        return environment
    keys = [item[1] for item in options]
    weights = [memory_weight(memory, key) for key in keys]
    field, _, value = weighted_choice(rng, options, weights)
    environment[field] = value
    return environment


def proposal_rules(
    rng: random.Random,
    memory: dict[str, float],
    *,
    symbol: str,
    timeframe: str,
    snapshot_interval: str,
    source_interval: str,
) -> dict[str, Any]:
    count = rng.choices([2, 3, 4], weights=[45, 40, 15], k=1)[0]
    selected: list[dict[str, Any]] = []
    attempts = 0
    while len(selected) < count and attempts < 100:
        attempts += 1
        candidates = [dict(item) for item in CONDITION_POOL if conditions_compatible(selected, item)]
        if not candidates:
            break
        weights = [memory_weight(memory, condition_key(item)) for item in candidates]
        selected.append(dict(weighted_choice(rng, candidates, weights)))

    direction_values = list(DIRECTION_RULES)
    direction_weights = [memory_weight(memory, f"direction:{item}") for item in direction_values]
    direction_rule = str(weighted_choice(rng, direction_values, direction_weights))

    stop = rng.choice(STOP_GRID)
    target_values = [target for target in TARGET_GRID if target / stop >= 0.9]
    target = rng.choice(target_values)
    horizon = rng.choice(HORIZONS)
    cooldown = rng.choice([item for item in COOLDOWNS if item <= max(240, horizon * 2)])

    return {
        "engine_version": INTELLIGENCE_VERSION,
        "market": {
            "symbol": symbol,
            "timeframe": timeframe,
            "execution_timeframe": timeframe,
            "snapshot_interval": snapshot_interval,
            "source_interval": source_interval,
            "research_source": "scientist_development_only_market_state_mining",
        },
        "family": "composed_signal",
        "schedule": choose_schedule(rng, memory),
        "environment": choose_environment(rng, memory),
        "entry": {
            "direction_rule": direction_rule,
            "condition_mode": "all",
            "conditions": selected,
        },
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


def development_score(metrics: Any) -> float:
    trades = float(metrics.trades)
    pf = min(float(metrics.profit_factor), 4.0)
    expectancy = float(metrics.expectancy_r)
    positive_year_rate = float(metrics.positive_year_rate)
    drawdown = float(metrics.max_drawdown_r)
    sample = min(1.0, trades / 400.0)
    return (
        (pf - 1.0) * 30.0
        + expectancy * 220.0
        + positive_year_rate * 12.0
        + sample * 8.0
        - drawdown * 0.20
    )


class IntelligenceDirector:
    """Self-improving research controller layered on top of the deterministic lab.

    The scientist is deliberately prevented from mining confirmation or final holdout.
    It may use development data to generate hypotheses and completed *selection-stage*
    validation results to learn where future research budget should be spent.
    """

    def __init__(
        self,
        settings: Any,
        repo: DiscoveryRepository,
        row_provider: Callable[[], Awaitable[list[dict[str, Any]]]],
    ) -> None:
        self.settings = settings
        self.repo = repo
        self.row_provider = row_provider
        self._stop = asyncio.Event()
        self.science_interval_seconds = env_int("EVE_SCIENTIST_INTERVAL_SECONDS", 3600, 300, 86400)
        self.live_interval_seconds = env_int("EVE_LIVE_WATCH_INTERVAL_SECONDS", 60, 30, 3600)
        self.proposal_count = env_int("EVE_SCIENTIST_PROPOSALS", 36, 8, 200)
        self.promotion_count = env_int("EVE_SCIENTIST_PROMOTIONS", 8, 1, 40)
        self.minimum_development_trades = env_int("EVE_SCIENTIST_MIN_DEV_TRADES", 120, 30, 2000)
        self.minimum_development_pf = env_float("EVE_SCIENTIST_MIN_DEV_PF", 1.03, 0.8, 3.0)
        self.minimum_development_expectancy = env_float("EVE_SCIENTIST_MIN_DEV_EXPECTANCY_R", 0.01, -0.2, 1.0)

        self.last_science_at: str | None = None
        self.last_live_watch_at: str | None = None
        self.last_error: str | None = None
        self.science_cycles = 0
        self.live_cycles = 0
        self.hypotheses_screened = 0
        self.hypotheses_queued = 0
        self.memory_features = 0
        self.live_status_counts: dict[str, int] = {}

    async def stop(self) -> None:
        self._stop.set()

    def runtime_status(self) -> dict[str, Any]:
        return {
            "version": INTELLIGENCE_VERSION,
            "science_interval_seconds": self.science_interval_seconds,
            "live_watch_interval_seconds": self.live_interval_seconds,
            "last_science_at": self.last_science_at,
            "last_live_watch_at": self.last_live_watch_at,
            "last_error": self.last_error,
            "science_cycles": self.science_cycles,
            "live_cycles": self.live_cycles,
            "hypotheses_screened": self.hypotheses_screened,
            "hypotheses_queued": self.hypotheses_queued,
            "memory_features": self.memory_features,
            "live_status_counts": dict(self.live_status_counts),
            "integrity_rule": "development generates hypotheses; selection validation teaches; confirmation and final holdout never teach",
        }

    async def _existing_hypothesis_keys(self) -> set[str]:
        rows = await self.repo.client.get(
            "scientist_hypotheses",
            params={"select": "hypothesis_key", "limit": "10000"},
        )
        return {str(row.get("hypothesis_key")) for row in rows if row.get("hypothesis_key")}

    async def _load_memory(self) -> dict[str, float]:
        rows = await self.repo.client.get(
            "scientist_feature_memory",
            params={"select": "feature_key,score", "order": "score.desc", "limit": "5000"},
        )
        self.memory_features = len(rows)
        return {str(row.get("feature_key")): float(number(row.get("score"))) for row in rows}

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
            metrics = dict(row.get("metrics") or {})
            validation = dict(metrics.get("validation") or {})
            pf = float(number(validation.get("profit_factor")))
            expectancy = float(number(validation.get("expectancy_r")))
            trades = float(number(validation.get("trades")))
            result_status = str(row.get("result_status") or "rejected")
            status_bonus = {
                "elite": 3.5,
                "validated": 2.5,
                "promising": 1.25,
                "rejected": -0.5,
            }.get(result_status, -0.25)
            contribution = clamp((pf - 1.0) * 2.0 + expectancy * 10.0 + status_bonus, -4.0, 6.0)
            for feature in rule_feature_keys(rules):
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
                    "updated_at": utc_now().isoformat(),
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
        while len(proposals) < target and attempts < target * 40:
            attempts += 1
            rules = proposal_rules(
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
            proposals.append(
                {
                    "hypothesis_key": key,
                    "candidate_key": f"candidate-{digest[:28]}",
                    "rules": rules,
                    "hypothesis": describe_strategy(rules),
                    "feature_keys": rule_feature_keys(rules),
                }
            )
        return proposals

    def _screen_sync(self, development: list[dict[str, Any]], proposals: list[dict[str, Any]]) -> list[dict[str, Any]]:
        results: list[dict[str, Any]] = []
        for proposal in proposals:
            metrics = evaluate_segment(development, proposal["rules"])
            score = development_score(metrics)
            qualified = (
                metrics.trades >= self.minimum_development_trades
                and metrics.profit_factor >= self.minimum_development_pf
                and metrics.expectancy_r >= self.minimum_development_expectancy
                and metrics.positive_year_rate >= 0.50
            )
            results.append(
                {
                    **proposal,
                    "development_metrics": metrics.as_dict(),
                    "development_score": round(score, 6),
                    "qualified": qualified,
                }
            )
        return sorted(results, key=lambda item: float(item["development_score"]), reverse=True)

    async def run_science_once(self, rows: list[dict[str, Any]] | None = None) -> dict[str, Any]:
        rows = rows if rows is not None else await self.row_provider()
        if len(rows) < 500:
            return {"ok": False, "reason": "not_enough_research_rows", "rows": len(rows)}

        segments = chronological_segments(rows)
        development = list(segments.get("development") or [])
        if len(development) < 250:
            return {"ok": False, "reason": "not_enough_development_rows", "rows": len(development)}

        memory = await self._rebuild_memory()
        if not memory:
            memory = await self._load_memory()
        existing = await self._existing_hypothesis_keys()
        seed = int(utc_now().timestamp()) // max(300, self.science_interval_seconds)
        proposals = self._proposals(memory, existing, seed=seed)
        screened = await asyncio.to_thread(self._screen_sync, development, proposals)

        qualified = [item for item in screened if item["qualified"]]
        promoted = qualified[: self.promotion_count]
        promoted_keys = {str(item["hypothesis_key"]) for item in promoted}
        now = utc_now().isoformat()

        hypothesis_rows: list[dict[str, Any]] = []
        for item in screened:
            hypothesis_rows.append(
                {
                    "hypothesis_key": item["hypothesis_key"],
                    "candidate_key": item["candidate_key"],
                    "scientist_version": INTELLIGENCE_VERSION,
                    "state": "queued_for_selection" if item["hypothesis_key"] in promoted_keys else "rejected_development",
                    "symbol": self.settings.source_symbol,
                    "timeframe": self.settings.research_timeframe,
                    "hypothesis": item["hypothesis"],
                    "rules": item["rules"],
                    "feature_keys": item["feature_keys"],
                    "development_metrics": item["development_metrics"],
                    "development_score": item["development_score"],
                    "evidence": {
                        "generation_data": "development_only",
                        "split_method": segments.get("method"),
                        "all_years": segments.get("years") or [],
                        "confirmation_holdout_access": "forbidden",
                    },
                    "updated_at": now,
                }
            )

        if hypothesis_rows:
            for start in range(0, len(hypothesis_rows), 200):
                await self.repo.client.upsert(
                    "scientist_hypotheses",
                    hypothesis_rows[start : start + 200],
                    on_conflict="hypothesis_key",
                )

        candidate_rows: list[dict[str, Any]] = []
        generation = self.science_cycles + 1
        for rank, item in enumerate(promoted, start=1):
            candidate_rows.append(
                {
                    "candidate_key": item["candidate_key"],
                    "generation": generation,
                    "symbol": self.settings.source_symbol,
                    "timeframe": self.settings.research_timeframe,
                    "research_stage": "selection",
                    "family": "composed_signal",
                    "name": f"EVE Scientist {item['candidate_key'][-6:].upper()} · Rank {rank}",
                    "hypothesis": item["hypothesis"],
                    "rules": item["rules"],
                    "status": "queued",
                    "priority": max(91, 100 - rank),
                    "composer_version": INTELLIGENCE_VERSION,
                }
            )
        await self.repo.seed_candidates(candidate_rows)

        self.science_cycles += 1
        self.hypotheses_screened += len(screened)
        self.hypotheses_queued += len(candidate_rows)
        self.last_science_at = now
        self.last_error = None

        await self.repo.event(
            "success" if candidate_rows else "info",
            "autonomous_scientist",
            (
                f"EVE Scientist screened {len(screened)} development-only hypotheses and promoted "
                f"{len(candidate_rows)} to sealed selection validation."
            ),
            {
                "scientist_version": INTELLIGENCE_VERSION,
                "development_rows": len(development),
                "screened": len(screened),
                "qualified": len(qualified),
                "promoted": len(candidate_rows),
                "memory_features": self.memory_features,
                "confirmation_holdout_access": "forbidden",
            },
        )
        return {
            "ok": True,
            "screened": len(screened),
            "qualified": len(qualified),
            "promoted": len(candidate_rows),
            "development_rows": len(development),
            "top": [
                {
                    "hypothesis_key": item["hypothesis_key"],
                    "score": item["development_score"],
                    "metrics": item["development_metrics"],
                    "hypothesis": item["hypothesis"],
                }
                for item in promoted[:5]
            ],
        }

    async def _latest_snapshot(self) -> dict[str, Any] | None:
        rows = await self.repo.client.get(
            "source_snapshots",
            params={
                "select": "*",
                "symbol": f"eq.{self.settings.source_symbol}",
                "snapshot_interval": f"eq.{self.settings.source_snapshot_interval}",
                "source_interval": f"eq.{self.settings.source_candle_interval}",
                "order": "candle_time.desc",
                "limit": "1",
            },
        )
        return dict(rows[0]) if rows else None

    async def run_live_watch_once(self) -> dict[str, Any]:
        snapshot = await self._latest_snapshot()
        if not snapshot:
            return {"ok": False, "reason": "no_snapshot"}

        strategies = await self.repo.client.get(
            "frozen_strategies",
            params={
                "select": "id,strategy_code,name,symbol,timeframe,status,rules,result_status,metrics,m1_replay",
                "order": "created_at.desc",
                "limit": "500",
            },
        )
        existing_rows = await self.repo.client.get(
            "live_setups",
            params={"select": "frozen_strategy_id,status", "limit": "1000"},
        )
        previous = {str(row.get("frozen_strategy_id")): str(row.get("status") or "idle") for row in existing_rows}

        now = utc_now().isoformat()
        live_rows: list[dict[str, Any]] = []
        transitions: list[dict[str, Any]] = []
        counts: dict[str, int] = {}

        for strategy in strategies:
            if not strategy.get("id"):
                continue
            rules = dict(strategy.get("rules") or {})
            market = dict(rules.get("market") or {})
            if market.get("symbol") and str(market.get("symbol")) != str(snapshot.get("symbol")):
                continue

            family = str(rules.get("family") or "")
            entry = dict(rules.get("entry") or {})
            conditions = [dict(item) for item in entry.get("conditions") or [] if isinstance(item, dict)]
            schedule_ok = schedule_matches(snapshot, dict(rules.get("schedule") or {}))
            environment_ok = environment_matches(snapshot, dict(rules.get("environment") or {}))
            direction = candidate_direction(snapshot, rules)

            if family == "composed_signal" and conditions:
                matches = [recipe_condition_matches(snapshot, condition) for condition in conditions]
                matched = sum(1 for item in matches if item)
                total = len(matches)
                similarity = (matched / total * 100.0) if total else 0.0
                if not schedule_ok or not environment_ok:
                    status = "idle"
                    similarity *= 0.35
                elif matched == total and direction != 0 and row_is_eligible(snapshot, rules):
                    status = "triggered"
                elif total >= 2 and matched >= total - 1 and direction != 0:
                    status = "armed"
                elif matched >= max(1, math.ceil(total * 0.50)):
                    status = "watching"
                else:
                    status = "idle"
            else:
                exact = row_is_eligible(snapshot, rules)
                matched = 1 if exact else 0
                total = 1
                similarity = 100.0 if exact else 0.0
                status = "triggered" if exact and direction != 0 else "idle"

            frozen_id = str(strategy.get("id"))
            old_status = previous.get(frozen_id, "idle")
            if old_status != status and status in {"armed", "triggered"}:
                transitions.append(
                    {
                        "frozen_strategy_id": frozen_id,
                        "strategy_code": strategy.get("strategy_code"),
                        "name": strategy.get("name"),
                        "from": old_status,
                        "to": status,
                        "direction": "buy" if direction > 0 else "sell" if direction < 0 else "none",
                        "snapshot_time": snapshot.get("candle_time"),
                        "similarity": round(similarity, 2),
                    }
                )

            counts[status] = counts.get(status, 0) + 1
            live_rows.append(
                {
                    "frozen_strategy_id": frozen_id,
                    "strategy_code": strategy.get("strategy_code"),
                    "name": strategy.get("name"),
                    "symbol": strategy.get("symbol") or snapshot.get("symbol"),
                    "timeframe": strategy.get("timeframe") or market.get("timeframe"),
                    "status": status,
                    "direction": "buy" if direction > 0 else "sell" if direction < 0 else "none",
                    "similarity": round(similarity, 3),
                    "matched_conditions": matched,
                    "total_conditions": total,
                    "snapshot_time": snapshot.get("candle_time"),
                    "details": {
                        "schedule_ok": schedule_ok,
                        "environment_ok": environment_ok,
                        "research_result_status": strategy.get("result_status"),
                        "research_snapshot_interval": self.settings.source_snapshot_interval,
                        "note": (
                            "This watcher uses the latest completed research snapshot. "
                            "Real-time every-M5 parity feed is the next live-execution layer."
                        ),
                    },
                    "updated_at": now,
                    "triggered_at": now if status == "triggered" and old_status != "triggered" else None,
                }
            )

        if live_rows:
            for start in range(0, len(live_rows), 200):
                await self.repo.client.upsert(
                    "live_setups",
                    live_rows[start : start + 200],
                    on_conflict="frozen_strategy_id",
                )

        for transition in transitions[:20]:
            await self.repo.event(
                "warning" if transition["to"] == "triggered" else "info",
                "live_pattern_watcher",
                (
                    f"{transition['name'] or transition['strategy_code']} is {transition['to'].upper()} "
                    f"({transition['direction'].upper()}, {transition['similarity']:.0f}% conditions)."
                ),
                transition,
            )

        self.live_cycles += 1
        self.last_live_watch_at = now
        self.live_status_counts = counts
        self.last_error = None
        return {
            "ok": True,
            "snapshot_time": snapshot.get("candle_time"),
            "strategies_checked": len(live_rows),
            "status_counts": counts,
            "transitions": transitions,
        }

    async def recent_hypotheses(self, limit: int = 100) -> list[dict[str, Any]]:
        return await self.repo.client.get(
            "scientist_hypotheses",
            params={
                "select": "*",
                "order": "created_at.desc",
                "limit": str(max(1, min(500, int(limit)))),
            },
        )

    async def live_setups(self, limit: int = 100) -> list[dict[str, Any]]:
        return await self.repo.client.get(
            "live_setups",
            params={
                "select": "*",
                "order": "updated_at.desc",
                "limit": str(max(1, min(500, int(limit)))),
            },
        )

    async def feature_memory(self, limit: int = 100) -> list[dict[str, Any]]:
        return await self.repo.client.get(
            "scientist_feature_memory",
            params={
                "select": "*",
                "order": "score.desc",
                "limit": str(max(1, min(500, int(limit)))),
            },
        )

    async def dashboard(self) -> dict[str, Any]:
        hypotheses, setups, memory = await asyncio.gather(
            self.recent_hypotheses(20),
            self.live_setups(100),
            self.feature_memory(30),
        )
        return {
            "runtime": self.runtime_status(),
            "recent_hypotheses": hypotheses,
            "live_setups": setups,
            "top_learned_features": memory,
        }

    async def run_forever(self) -> None:
        try:
            await asyncio.wait_for(self._stop.wait(), timeout=5.0)
            return
        except asyncio.TimeoutError:
            pass

        next_science = utc_now()
        next_live = utc_now()
        while not self._stop.is_set():
            now = utc_now()
            try:
                if now >= next_live:
                    await self.run_live_watch_once()
                    next_live = utc_now() + timedelta(seconds=self.live_interval_seconds)
                if now >= next_science:
                    rows = await self.row_provider()
                    await self.run_science_once(rows)
                    next_science = utc_now() + timedelta(seconds=self.science_interval_seconds)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                self.last_error = str(exc)
                logger.exception("Autonomous scientist cycle failed")
                try:
                    await self.repo.event(
                        "error",
                        "autonomous_scientist",
                        "EVE Scientist cycle failed; the primary research worker remains isolated and running.",
                        {"error": str(exc)[:1500], "scientist_version": INTELLIGENCE_VERSION},
                    )
                except Exception:
                    logger.exception("Failed to record autonomous scientist error event")

            try:
                await asyncio.wait_for(self._stop.wait(), timeout=5.0)
            except asyncio.TimeoutError:
                pass
