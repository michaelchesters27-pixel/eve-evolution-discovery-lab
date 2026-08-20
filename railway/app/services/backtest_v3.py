from __future__ import annotations

import hashlib
import json
import math
import random
from collections import deque
from datetime import timedelta
from typing import Any, Iterable

from app.services import backtest as legacy

RESEARCH_INTEGRITY_VERSION = "eve-research-integrity-v3.0"
OBSERVATION_VERSION = "eve-market-observations-v2"

# Preserve the deterministic v2 implementations for conditions/directions that
# do not belong to the richer scientist observation layer.
_V2_RECIPE_CONDITION_MATCHES = legacy.recipe_condition_matches
_V2_CANDIDATE_DIRECTION = legacy.candidate_direction

STRUCTURE_CONDITION_TYPES = {
    "sweep_prior_12_high_reclaim",
    "sweep_prior_12_low_reclaim",
    "break_prior_12_high",
    "break_prior_12_low",
    "prev_day_high_sweep_reclaim",
    "prev_day_low_sweep_reclaim",
    "prev_day_high_break",
    "prev_day_low_break",
    "session_high_sweep_reclaim",
    "session_low_sweep_reclaim",
    "displacement_atr_min",
    "range_expansion_min",
    "range_position_high",
    "range_position_low",
    "compression_release",
    "three_bar_same_direction",
}


def timeframe_minutes(rules: dict[str, Any]) -> int:
    timeframe = str((rules.get("market") or {}).get("execution_timeframe") or (rules.get("market") or {}).get("timeframe") or "M5").upper()
    return {"M1": 1, "M5": 5, "M15": 15, "M30": 30, "H1": 60, "H4": 240}.get(timeframe, 5)


def has_structure_conditions(rules: dict[str, Any]) -> bool:
    entry = dict(rules.get("entry") or {})
    return any(
        str(item.get("type") or "") in STRUCTURE_CONDITION_TYPES
        for item in entry.get("conditions") or []
        if isinstance(item, dict)
    ) or str(entry.get("direction_rule") or "") == "structure_direction"


def _safe_high(rows: list[dict[str, Any]]) -> float | None:
    values = [legacy.number(row.get("high")) for row in rows if legacy.number(row.get("high")) > 0]
    return max(values) if values else None


def _safe_low(rows: list[dict[str, Any]]) -> float | None:
    values = [legacy.number(row.get("low")) for row in rows if legacy.number(row.get("low")) > 0]
    return min(values) if values else None


def enrich_market_observations(rows: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    """Add causal, past-only market-structure observations to research rows.

    The fabric and orchestrator already supply chronological lists. Avoid copying
    and sorting hundreds of thousands of rows again when the observations are
    already present; this function is called repeatedly during Scientist screens.
    If a raw tail has been appended, verify chronology in O(n) and recompute once.
    """
    source = rows if isinstance(rows, list) else list(rows)
    if not source:
        return source

    sample_indexes = {0, len(source) - 1, len(source) // 2}
    if all(source[index].get("observation_version") == OBSERVATION_VERSION for index in sample_indexes):
        return source

    chronological = all(
        str(source[index - 1].get("candle_time") or "") <= str(source[index].get("candle_time") or "")
        for index in range(1, len(source))
    )
    ordered = source if chronological else sorted(source, key=lambda row: str(row.get("candle_time") or ""))

    history: deque[dict[str, Any]] = deque(maxlen=48)
    current_day: str | None = None
    day_high: float | None = None
    day_low: float | None = None
    previous_day_high: float | None = None
    previous_day_low: float | None = None
    session_highs: dict[tuple[str, str], float] = {}
    session_lows: dict[tuple[str, str], float] = {}
    previous_row: dict[str, Any] | None = None

    for row in ordered:
        timestamp = legacy.as_utc(row.get("candle_time"))
        if timestamp is None:
            continue
        day = timestamp.date().isoformat()
        high = legacy.number(row.get("high"))
        low = legacy.number(row.get("low"))
        close = legacy.number(row.get("close"))
        open_price = legacy.number(row.get("open"))
        atr = max(legacy.number(row.get("atr_14")), 1e-9)

        if current_day != day:
            if current_day is not None:
                previous_day_high = day_high
                previous_day_low = day_low
            current_day = day
            day_high = None
            day_low = None

        prior = list(history)
        prior4 = prior[-4:]
        prior12 = prior[-12:]
        prior48 = prior[-48:]
        p4h, p4l = _safe_high(prior4), _safe_low(prior4)
        p12h, p12l = _safe_high(prior12), _safe_low(prior12)
        p48h, p48l = _safe_high(prior48), _safe_low(prior48)

        row["observation_version"] = OBSERVATION_VERSION
        row["obs_prior_4_high"] = p4h
        row["obs_prior_4_low"] = p4l
        row["obs_prior_12_high"] = p12h
        row["obs_prior_12_low"] = p12l
        row["obs_prior_48_high"] = p48h
        row["obs_prior_48_low"] = p48l

        sweep12_high = bool(p12h is not None and high > p12h and close < p12h)
        sweep12_low = bool(p12l is not None and low < p12l and close > p12l)
        break12_high = bool(p12h is not None and close > p12h)
        break12_low = bool(p12l is not None and close < p12l)
        row["obs_sweep_prior_12_high"] = sweep12_high
        row["obs_sweep_prior_12_low"] = sweep12_low
        row["obs_break_prior_12_high"] = break12_high
        row["obs_break_prior_12_low"] = break12_low

        if p12h is not None and p12l is not None and p12h > p12l:
            row["obs_range_position_12"] = (close - p12l) / (p12h - p12l)
            row["obs_distance_prior_12_high_atr"] = abs(p12h - close) / atr
            row["obs_distance_prior_12_low_atr"] = abs(close - p12l) / atr
        else:
            row["obs_range_position_12"] = None
            row["obs_distance_prior_12_high_atr"] = None
            row["obs_distance_prior_12_low_atr"] = None

        row["obs_previous_day_high"] = previous_day_high
        row["obs_previous_day_low"] = previous_day_low
        pdh_sweep = bool(previous_day_high is not None and high > previous_day_high and close < previous_day_high)
        pdl_sweep = bool(previous_day_low is not None and low < previous_day_low and close > previous_day_low)
        pdh_break = bool(previous_day_high is not None and close > previous_day_high)
        pdl_break = bool(previous_day_low is not None and close < previous_day_low)
        row["obs_prev_day_high_sweep"] = pdh_sweep
        row["obs_prev_day_low_sweep"] = pdl_sweep
        row["obs_prev_day_high_break"] = pdh_break
        row["obs_prev_day_low_break"] = pdl_break

        session = str(row.get("session") or "unknown")
        session_key = (day, session)
        prior_session_high = session_highs.get(session_key)
        prior_session_low = session_lows.get(session_key)
        row["obs_session_prior_high"] = prior_session_high
        row["obs_session_prior_low"] = prior_session_low
        row["obs_session_high_sweep"] = bool(prior_session_high is not None and high > prior_session_high and close < prior_session_high)
        row["obs_session_low_sweep"] = bool(prior_session_low is not None and low < prior_session_low and close > prior_session_low)

        avg_range = max(legacy.number(row.get("average_range_12")), 1e-9)
        range_price = max(0.0, legacy.number(row.get("range_price"), high - low))
        row["obs_displacement_atr"] = abs(close - open_price) / atr
        row["obs_range_expansion"] = range_price / avg_range
        previous_compression = legacy.number((previous_row or {}).get("compression_ratio"), 1.0)
        current_compression = legacy.number(row.get("compression_ratio"), 1.0)
        row["obs_compression_release"] = bool(previous_compression < 0.72 and current_compression >= 0.95)

        last_two = prior[-2:]
        directions = [legacy.sign(item.get("direction")) for item in last_two] + [legacy.sign(row.get("direction"))]
        same_three = len(directions) == 3 and directions[0] != 0 and all(value == directions[0] for value in directions)
        row["obs_three_bar_same_direction"] = same_three
        row["obs_three_bar_direction"] = directions[0] if same_three else 0

        bullish = [pdl_sweep, sweep12_low, pdh_break, break12_high]
        bearish = [pdh_sweep, sweep12_high, pdl_break, break12_low]
        if any(bullish) and not any(bearish):
            row["obs_structure_direction"] = 1
        elif any(bearish) and not any(bullish):
            row["obs_structure_direction"] = -1
        else:
            row["obs_structure_direction"] = 0

        day_high = high if day_high is None else max(day_high, high)
        day_low = low if day_low is None else min(day_low, low)
        session_highs[session_key] = high if prior_session_high is None else max(prior_session_high, high)
        session_lows[session_key] = low if prior_session_low is None else min(prior_session_low, low)
        history.append(row)
        previous_row = row

    return ordered


def recipe_condition_matches(row: dict[str, Any], condition: dict[str, Any]) -> bool:
    kind = str(condition.get("type") or "")
    if kind == "sweep_prior_12_high_reclaim":
        return bool(row.get("obs_sweep_prior_12_high"))
    if kind == "sweep_prior_12_low_reclaim":
        return bool(row.get("obs_sweep_prior_12_low"))
    if kind == "break_prior_12_high":
        return bool(row.get("obs_break_prior_12_high"))
    if kind == "break_prior_12_low":
        return bool(row.get("obs_break_prior_12_low"))
    if kind == "prev_day_high_sweep_reclaim":
        return bool(row.get("obs_prev_day_high_sweep"))
    if kind == "prev_day_low_sweep_reclaim":
        return bool(row.get("obs_prev_day_low_sweep"))
    if kind == "prev_day_high_break":
        return bool(row.get("obs_prev_day_high_break"))
    if kind == "prev_day_low_break":
        return bool(row.get("obs_prev_day_low_break"))
    if kind == "session_high_sweep_reclaim":
        return bool(row.get("obs_session_high_sweep"))
    if kind == "session_low_sweep_reclaim":
        return bool(row.get("obs_session_low_sweep"))
    if kind == "displacement_atr_min":
        return legacy.number(row.get("obs_displacement_atr")) >= legacy.number(condition.get("min"), 0.5)
    if kind == "range_expansion_min":
        return legacy.number(row.get("obs_range_expansion")) >= legacy.number(condition.get("min"), 1.5)
    if kind == "range_position_high":
        return legacy.number(row.get("obs_range_position_12"), -99.0) >= legacy.number(condition.get("min"), 0.8)
    if kind == "range_position_low":
        return legacy.number(row.get("obs_range_position_12"), 99.0) <= legacy.number(condition.get("max"), 0.2)
    if kind == "compression_release":
        return bool(row.get("obs_compression_release"))
    if kind == "three_bar_same_direction":
        return bool(row.get("obs_three_bar_same_direction"))
    return _V2_RECIPE_CONDITION_MATCHES(row, condition)


def candidate_direction(row: dict[str, Any], rules: dict[str, Any]) -> int:
    rule = str((rules.get("entry") or {}).get("direction_rule") or "current_direction")
    if rule == "structure_direction":
        return legacy.sign(row.get("obs_structure_direction"))
    if rule == "three_bar_direction":
        return legacy.sign(row.get("obs_three_bar_direction"))
    return _V2_CANDIDATE_DIRECTION(row, rules)


def _trade_records_v3(rows: Iterable[dict[str, Any]], rules: dict[str, Any], *, cost_r: float | None = None) -> list[Any]:
    risk = dict(rules.get("risk") or {})
    cooldown = max(1, int(legacy.number(risk.get("cooldown_minutes"), 0)))
    max_hold = max(1, int(legacy.number(risk.get("max_hold_minutes"), risk.get("horizon_minutes") or 60)))
    entry_lock = max(cooldown, max_hold)
    execution_delay = timeframe_minutes(rules)
    next_allowed = None
    records: list[Any] = []

    ordered = enrich_market_observations(rows)
    for row in ordered:
        signal_time = legacy.as_utc(row.get("candle_time"))
        if not signal_time:
            continue
        entry_time = signal_time + timedelta(minutes=execution_delay)
        if next_allowed and entry_time < next_allowed:
            continue
        if not legacy.row_is_eligible(row, rules):
            continue
        direction = legacy.candidate_direction(row, rules)
        pnl = legacy.trade_r(row, direction, risk, cost_r=cost_r)
        if pnl is None:
            continue
        records.append(
            legacy.TradeRecord(
                time=entry_time,
                pnl_r=pnl,
                weekday=entry_time.isoweekday(),
                hour_utc=entry_time.hour,
                session=str(row.get("session") or "unknown"),
                regime=str(row.get("regime") or "unknown"),
            )
        )
        # Coarse selection does not know the exact early exit time. Using actual
        # entry + full potential hold is conservative and can never open a second
        # trade while the corresponding M1/live position could still be active.
        next_allowed = entry_time + timedelta(minutes=entry_lock)
    return records


def monte_carlo_sequence_v3(rows: list[dict[str, Any]], rules: dict[str, Any], *, simulations: int = 400) -> dict[str, Any]:
    """Moving-block bootstrap that preserves short winning/losing clusters."""
    records = _trade_records_v3(rows, rules)
    pnls = [record.pnl_r for record in records]
    if len(pnls) < 20:
        return {
            "method": "moving_block_bootstrap",
            "simulations": 0,
            "trades": len(pnls),
            "block_size": 0,
            "pass_rate": 0.0,
            "p05_expectancy_r": 0.0,
            "p95_max_drawdown_r": 0.0,
        }
    digest = hashlib.sha256(json.dumps(rules, sort_keys=True, default=str).encode()).hexdigest()
    rng = random.Random(int(digest[:16], 16))
    block_size = max(3, min(12, int(round(math.sqrt(len(pnls)) / 2.0))))
    expectancies: list[float] = []
    drawdowns: list[float] = []
    positive = 0
    max_start = max(0, len(pnls) - block_size)
    for _ in range(simulations):
        sample: list[float] = []
        while len(sample) < len(pnls):
            start = rng.randrange(max_start + 1) if max_start else 0
            sample.extend(pnls[start : start + block_size])
        sample = sample[: len(pnls)]
        expectancy = sum(sample) / len(sample)
        equity = peak = drawdown = 0.0
        for value in sample:
            equity += value
            peak = max(peak, equity)
            drawdown = max(drawdown, peak - equity)
        expectancies.append(expectancy)
        drawdowns.append(drawdown)
        positive += int(expectancy > 0)
    expectancies.sort()
    drawdowns.sort()
    p05 = expectancies[max(0, int(len(expectancies) * 0.05) - 1)]
    p95_dd = drawdowns[min(len(drawdowns) - 1, int(len(drawdowns) * 0.95))]
    return {
        "method": "moving_block_bootstrap",
        "simulations": simulations,
        "trades": len(pnls),
        "block_size": block_size,
        "pass_rate": positive / simulations,
        "p05_expectancy_r": round(p05, 6),
        "p95_max_drawdown_r": round(p95_dd, 6),
    }


# Patch the deterministic engine in one place so all existing evaluation,
# robustness, walk-forward and M1 intent code sees identical rule semantics.
legacy.RESEARCH_INTEGRITY_VERSION = RESEARCH_INTEGRITY_VERSION
legacy.recipe_condition_matches = recipe_condition_matches
legacy.candidate_direction = candidate_direction
legacy._trade_records = _trade_records_v3
legacy.monte_carlo_sequence = monte_carlo_sequence_v3

# Public re-exports used by the v3 orchestrator and scientist.
compare_child_to_parent = legacy.compare_child_to_parent
evaluate_strategy = legacy.evaluate_strategy
number = legacy.number
selection_ready_for_final = legacy.selection_ready_for_final
as_utc = legacy.as_utc
chronological_segments = legacy.chronological_segments
environment_matches = legacy.environment_matches
evaluate_segment = legacy.evaluate_segment
row_is_eligible = legacy.row_is_eligible
schedule_matches = legacy.schedule_matches
