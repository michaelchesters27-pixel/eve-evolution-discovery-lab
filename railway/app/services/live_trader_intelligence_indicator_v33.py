from __future__ import annotations

import math
from datetime import datetime, timedelta, timezone
from typing import Any

from app.services import live_trader as core
from app.services import live_trader_historical_learning_v29 as academy

SCORE_VERSION = "eve-live-intelligence-index-v1"
SNAPSHOT_MINUTES = 15
SUMMARY_CACHE_SECONDS = 15

# Architecture is deliberately capped below 10/10. Passing a capability checklist
# means the system contains the mechanism; it does not prove perfect trading skill.
ARCHITECTURE_CAPABILITIES = (
    "causal_multi_timeframe_fabric",
    "live_feed_freshness_guard",
    "supply_demand_location",
    "liquidity_sweep_fakeout_reasoning",
    "multi_timeframe_bias",
    "causal_m1_outcome_scoring",
    "stable_semantic_learning_families",
    "bayesian_confidence_calibration",
    "mature_family_learning_governor",
    "one_trade_campaign_lock",
    "broker_market_hours_guard",
    "historical_academy_and_challengers",
)

_current_learning_summary = core.LiveTrader.learning_summary
_current_academy_cycle = academy.LiveTraderHistoricalLearner.learn_cycle


def _number(value: Any, default: float = 0.0) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return default
    return number if math.isfinite(number) else default


def _sat(value: Any, target: float) -> float:
    amount = max(0.0, _number(value))
    if target <= 0:
        return 1.0
    return min(1.0, math.log1p(amount) / math.log1p(target))


def _score_level(score: float) -> str:
    if score < 4.0:
        return "FOUNDATIONAL"
    if score < 6.0:
        return "DEVELOPING"
    if score < 7.5:
        return "LEARNING"
    if score < 8.5:
        return "ADAPTIVE"
    if score < 9.3:
        return "EXPERIENCED"
    return "ELITE"


def _next_target(current: int, thresholds: tuple[int, ...]) -> int:
    for target in thresholds:
        if current < target:
            return target
    return thresholds[-1]


def score_intelligence(metrics: dict[str, Any]) -> dict[str, Any]:
    forward_scored = int(_number(metrics.get("forward_scored")))
    forward_days = int(_number(metrics.get("forward_days")))
    historical_scored = int(_number(metrics.get("historical_scored")))
    challenger_runs = int(_number(metrics.get("challenger_runs")))
    combined_families = int(_number(metrics.get("combined_families")))
    mature_forward = int(_number(metrics.get("mature_forward_families")))
    historical_seed = int(_number(metrics.get("historical_seed_families")))
    deep_historical = int(_number(metrics.get("historically_deep_families")))
    execution_discoveries = int(_number(metrics.get("execution_discoveries")))

    capability_ratio = len(ARCHITECTURE_CAPABILITIES) / len(ARCHITECTURE_CAPABILITIES)
    brain = 5.0 + 4.0 * capability_ratio  # 9.0 maximum for architecture alone.

    experience = 10.0 * (
        0.35 * _sat(forward_scored, 1000)
        + 0.15 * _sat(forward_days, 180)
        + 0.20 * _sat(historical_scored, 20000)
        + 0.15 * _sat(challenger_runs, 50000)
        + 0.15 * _sat(combined_families, 400)
    )

    applied = 10.0 * (
        0.45 * _sat(mature_forward, 20)
        + 0.20 * _sat(execution_discoveries, 20)
        + 0.15 * _sat(historical_seed, 30)
        + 0.10 * _sat(deep_historical, 50)
        + 0.10 * min(1.0, forward_scored / 120.0)
    )

    overall = 0.45 * brain + 0.25 * experience + 0.30 * applied
    level = _score_level(overall)

    if mature_forward == 0:
        explanation = (
            "EVE's architecture is strong and Historical Academy is building useful execution knowledge, "
            "but no setup family has enough independent forward-live days yet to count as mature."
        )
    elif applied < 6.0:
        explanation = (
            "EVE has begun applying mature evidence to live decisions. More independent forward-live families "
            "are still needed before adaptive learning carries broad authority."
        )
    else:
        explanation = (
            "EVE has substantial evidence depth and multiple mature learning families influencing live decisions."
        )

    milestone_specs = (
        ("Forward scored outcomes", forward_scored, (50, 100, 250, 500, 1000)),
        ("Mature forward families", mature_forward, (1, 3, 5, 10, 20)),
        ("Historical scored episodes", historical_scored, (500, 1000, 2500, 5000, 10000, 20000)),
        ("Execution discoveries", execution_discoveries, (1, 3, 5, 10, 20, 40)),
    )
    milestones: list[dict[str, Any]] = []
    for label, current, thresholds in milestone_specs:
        target = _next_target(current, thresholds)
        milestones.append(
            {
                "label": label,
                "current": current,
                "target": target,
                "progress": round(min(1.0, current / max(target, 1)), 3),
                "complete": current >= thresholds[-1],
            }
        )

    return {
        "version": SCORE_VERSION,
        "overall": round(overall, 2),
        "brain": round(brain, 2),
        "experience": round(experience, 2),
        "applied_learning": round(applied, 2),
        "level": level,
        "architecture_capabilities": len(ARCHITECTURE_CAPABILITIES),
        "architecture_capability_names": list(ARCHITECTURE_CAPABILITIES),
        "weights": {"brain": 0.45, "experience": 0.25, "applied_learning": 0.30},
        "metrics": {
            key: int(_number(value))
            for key, value in metrics.items()
            if isinstance(value, (int, float)) or str(value).replace(".", "", 1).isdigit()
        },
        "milestones": milestones,
        "explanation": explanation,
        "meaning": (
            "This index measures EVE's adaptive capability, valid evidence depth and maturity of applied learning. "
            "It is not a profitability score or a promise of future trading performance."
        ),
    }


async def _fetch_metrics(client: Any, symbol: str) -> dict[str, Any]:
    result = await client.rpc("get_live_trader_intelligence_metrics", {"p_symbol": symbol})
    if isinstance(result, dict):
        return result
    if isinstance(result, list) and result and isinstance(result[0], dict):
        return dict(result[0])
    return {}


def _parse_time(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _bucket(now: datetime) -> datetime:
    minute = (now.minute // SNAPSHOT_MINUTES) * SNAPSHOT_MINUTES
    return now.replace(minute=minute, second=0, microsecond=0)


async def _record_snapshot(client: Any, symbol: str, intelligence: dict[str, Any]) -> None:
    now = core.utc_now()
    bucket = _bucket(now)
    key = f"{symbol}|{SCORE_VERSION}|{bucket.isoformat()}"
    await client.upsert(
        "live_trader_intelligence_snapshots",
        {
            "snapshot_key": key,
            "symbol": symbol,
            "captured_at": now.isoformat(),
            "overall_score": intelligence["overall"],
            "brain_score": intelligence["brain"],
            "experience_score": intelligence["experience"],
            "applied_score": intelligence["applied_learning"],
            "level": intelligence["level"],
            "score_version": SCORE_VERSION,
            "metrics": intelligence.get("metrics") or {},
        },
        on_conflict="snapshot_key",
        return_rows=False,
    )


async def _trend(client: Any, symbol: str, current: dict[str, Any]) -> dict[str, Any]:
    try:
        rows = await client.get(
            "live_trader_intelligence_snapshots",
            params={
                "select": "captured_at,overall_score",
                "symbol": f"eq.{symbol}",
                "score_version": f"eq.{SCORE_VERSION}",
                "order": "captured_at.desc",
                "limit": "5000",
            },
        )
    except Exception:
        rows = []
    now = core.utc_now()
    parsed = [
        (_parse_time(row.get("captured_at")), _number(row.get("overall_score")))
        for row in rows
    ]
    parsed = [(stamp, score) for stamp, score in parsed if stamp is not None]

    def delta_for(age: timedelta) -> float | None:
        threshold = now - age
        candidate = next(((stamp, score) for stamp, score in parsed if stamp <= threshold), None)
        if candidate is None:
            return None
        return round(_number(current.get("overall")) - candidate[1], 2)

    earliest = parsed[-1] if parsed else None
    return {
        "since_baseline": round(_number(current.get("overall")) - earliest[1], 2) if earliest else 0.0,
        "baseline_at": earliest[0].isoformat() if earliest else now.isoformat(),
        "hours_24": delta_for(timedelta(hours=24)),
        "days_7": delta_for(timedelta(days=7)),
        "days_30": delta_for(timedelta(days=30)),
    }


async def _current_intelligence(self: core.LiveTrader) -> dict[str, Any]:
    now = core.utc_now()
    cached_at = getattr(self, "_intelligence_cache_at_v33", None)
    cached = getattr(self, "_intelligence_cache_v33", None)
    if isinstance(cached_at, datetime) and isinstance(cached, dict):
        if (now - cached_at).total_seconds() < SUMMARY_CACHE_SECONDS:
            return dict(cached)

    metrics = await _fetch_metrics(self.repo.client, self.symbol)
    intelligence = score_intelligence(metrics)
    try:
        await _record_snapshot(self.repo.client, self.symbol, intelligence)
        intelligence["trend"] = await _trend(self.repo.client, self.symbol, intelligence)
    except Exception as exc:
        intelligence["trend"] = {
            "since_baseline": 0.0,
            "hours_24": None,
            "days_7": None,
            "days_30": None,
        }
        intelligence["snapshot_warning"] = str(exc)[:240]
    self._intelligence_cache_at_v33 = now
    self._intelligence_cache_v33 = dict(intelligence)
    return intelligence


def _academy_runtime(self: core.LiveTrader) -> dict[str, Any]:
    learner = getattr(self, "_historical_academy_v30", None)
    if learner is None:
        return {}
    try:
        return dict(learner.runtime_status())
    except Exception:
        return {}


def _explain_with_academy_status(intelligence: dict[str, Any], caught_up: bool) -> dict[str, Any]:
    result = dict(intelligence)
    result["historical_academy_caught_up"] = bool(caught_up)
    if not caught_up:
        return result

    mature_forward = int(_number((result.get("metrics") or {}).get("mature_forward_families")))
    applied = _number(result.get("applied_learning"))
    if mature_forward == 0:
        result["explanation"] = (
            "EVE's architecture is strong and Historical Academy has completed the available causal archive. "
            "Her next major intelligence gains now depend on newly completed market data and independent forward-live experience; "
            "no setup family has enough forward-live days to count as mature yet."
        )
    elif applied < 6.0:
        result["explanation"] = (
            "Historical Academy has completed the available causal archive and remains on watch for new completed data. "
            "EVE has begun applying mature forward evidence, but more independent live families are still needed before adaptive learning carries broad authority."
        )
    else:
        result["explanation"] = (
            "Historical Academy is caught up with the available causal archive and continuously monitors for new completed data. "
            "EVE also has multiple mature forward-live families influencing current decisions."
        )
    return result


async def _learning_summary_v33(self: core.LiveTrader) -> dict[str, Any]:
    summary = dict(await _current_learning_summary(self))
    academy_runtime = _academy_runtime(self)
    historical = dict(summary.get("historical_learning") or {})
    caught_up = bool(academy_runtime.get("caught_up"))
    if academy_runtime:
        historical.update(
            {
                "caught_up": caught_up,
                "running": bool(academy_runtime.get("running", True)),
                "runtime_last_cycle_at": academy_runtime.get("last_cycle_at"),
                "runtime_last_error": academy_runtime.get("last_error"),
                "status": "caught_up" if caught_up else "replaying",
            }
        )
        summary["historical_learning"] = historical
    try:
        intelligence = await _current_intelligence(self)
        summary["intelligence"] = _explain_with_academy_status(intelligence, caught_up)
    except Exception as exc:
        summary["intelligence"] = {
            "version": SCORE_VERSION,
            "status": "unavailable",
            "error": str(exc)[:240],
        }
    return summary


async def _academy_cycle_v33(self: academy.LiveTraderHistoricalLearner) -> dict[str, Any]:
    result = await _current_academy_cycle(self)
    now = core.utc_now()
    last_bucket = getattr(self, "_intelligence_snapshot_bucket_v33", None)
    bucket = _bucket(now)
    if last_bucket != bucket:
        try:
            metrics = await _fetch_metrics(self.repo.client, self.settings.live_trader_symbol)
            intelligence = score_intelligence(metrics)
            await _record_snapshot(self.repo.client, self.settings.live_trader_symbol, intelligence)
            self._intelligence_snapshot_bucket_v33 = bucket
        except Exception as exc:
            core.logger.warning("Historical Academy could not persist intelligence snapshot: %s", exc)
    return result


core.LiveTrader.learning_summary = _learning_summary_v33  # type: ignore[method-assign]
academy.LiveTraderHistoricalLearner.learn_cycle = _academy_cycle_v33  # type: ignore[method-assign]
