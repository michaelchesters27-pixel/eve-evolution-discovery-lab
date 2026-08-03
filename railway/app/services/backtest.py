from __future__ import annotations

import copy
import math
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Iterable


def number(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def as_utc(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        return value.astimezone(timezone.utc) if value.tzinfo else value.replace(tzinfo=timezone.utc)
    if not value:
        return None
    text = str(value).replace("Z", "+00:00")
    try:
        result = datetime.fromisoformat(text)
        return result.astimezone(timezone.utc) if result.tzinfo else result.replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def sign(value: Any) -> int:
    parsed = number(value)
    return 1 if parsed > 0 else -1 if parsed < 0 else 0


def trend_band(value: Any) -> str:
    parsed = number(value)
    if parsed >= 0.18:
        return "up"
    if parsed <= -0.18:
        return "down"
    return "flat"


def compression_band(value: Any) -> str:
    parsed = number(value, 1.0)
    if parsed < 0.72:
        return "compressed"
    if parsed > 1.35:
        return "expanded"
    return "normal"


def outcome_for(row: dict[str, Any], horizon: int) -> dict[str, Any] | None:
    outcomes = row.get("outcomes") or {}
    result = outcomes.get(str(horizon)) if isinstance(outcomes, dict) else None
    return dict(result) if isinstance(result, dict) else None


def schedule_matches(row: dict[str, Any], schedule: dict[str, Any]) -> bool:
    weekdays = [int(v) for v in schedule.get("weekdays") or []]
    months = [int(v) for v in schedule.get("months") or []]
    sessions = [str(v) for v in schedule.get("sessions") or []]
    hours = [int(v) for v in schedule.get("hours_utc") or []]
    if weekdays and int(number(row.get("weekday"))) not in weekdays:
        return False
    if months and int(number(row.get("month"))) not in months:
        return False
    if sessions and str(row.get("session") or "") not in sessions:
        return False
    if hours and int(number(row.get("hour_utc"))) not in hours:
        return False
    return True


def environment_matches(row: dict[str, Any], environment: dict[str, Any]) -> bool:
    regimes = [str(v) for v in environment.get("regimes") or []]
    if regimes and str(row.get("regime") or "unknown") not in regimes:
        return False

    for key, column in (("trend_12", "trend_12_atr"), ("trend_48", "trend_48_atr")):
        required = str(environment.get(key) or "any")
        actual = trend_band(row.get(column))
        if required == "directional" and actual == "flat":
            return False
        if required not in {"any", "directional"} and actual != required:
            return False

    required_compression = str(environment.get("compression") or "any")
    if required_compression != "any" and compression_band(row.get("compression_ratio")) != required_compression:
        return False

    min_alignment = int(number(environment.get("min_alignment_abs")))
    if abs(int(number(row.get("alignment_score")))) < min_alignment:
        return False

    alignment_sign = str(environment.get("alignment_sign") or "any")
    score_sign = sign(row.get("alignment_score"))
    if alignment_sign == "up" and score_sign <= 0:
        return False
    if alignment_sign == "down" and score_sign >= 0:
        return False

    streak = str(environment.get("streak") or "any")
    streak_value = int(number(row.get("streak")))
    if streak == "up3" and streak_value < 3:
        return False
    if streak == "down3" and streak_value > -3:
        return False
    return True


def family_matches(row: dict[str, Any], rules: dict[str, Any]) -> bool:
    family = str(rules.get("family") or "momentum_continuation")
    direction = sign(row.get("direction"))
    trend = sign(row.get("trend_12_atr"))
    alignment = sign(row.get("alignment_score"))
    close_location = number(row.get("close_location"), 0.5)
    upper = number(row.get("upper_wick"))
    lower = number(row.get("lower_wick"))
    body = max(number(row.get("body_price")), 1e-9)

    if family == "momentum_continuation":
        return direction != 0 and trend != 0 and direction == trend and abs(number(row.get("return_3_pct"))) > 0.005
    if family == "alignment_continuation":
        return alignment != 0 and abs(int(number(row.get("alignment_score")))) >= int(number(rules.get("environment", {}).get("min_alignment_abs"), 1))
    if family == "pullback_continuation":
        return trend != 0 and direction != 0 and direction == -trend
    if family == "volatility_breakout":
        return direction != 0 and abs(number(row.get("return_1_pct"))) > abs(number(row.get("return_3_pct"))) / 4.0
    if family == "mean_reversion":
        return direction != 0 and (close_location <= 0.20 or close_location >= 0.80)
    if family == "candle_reversal":
        ratio = number(rules.get("entry", {}).get("wick_ratio_min"), 1.5)
        return max(upper, lower) / body >= ratio
    return False


def candidate_direction(row: dict[str, Any], rules: dict[str, Any]) -> int:
    rule = str(rules.get("entry", {}).get("direction_rule") or "current_direction")
    if rule == "current_direction":
        return sign(row.get("direction"))
    if rule == "alignment_direction":
        return sign(row.get("alignment_score"))
    if rule == "trend_direction":
        return sign(row.get("trend_12_atr"))
    if rule == "reverse_current":
        return -sign(row.get("direction"))
    if rule == "wick_reversal":
        upper = number(row.get("upper_wick"))
        lower = number(row.get("lower_wick"))
        if lower > upper:
            return 1
        if upper > lower:
            return -1
    return 0


def row_is_eligible(row: dict[str, Any], rules: dict[str, Any]) -> bool:
    return (
        schedule_matches(row, dict(rules.get("schedule") or {}))
        and environment_matches(row, dict(rules.get("environment") or {}))
        and family_matches(row, rules)
    )


def trade_r(row: dict[str, Any], direction: int, risk: dict[str, Any]) -> float | None:
    horizon = int(number(risk.get("horizon_minutes"), 60))
    outcome = outcome_for(row, horizon)
    if not outcome or direction == 0:
        return None

    stop_atr = max(0.1, number(risk.get("stop_atr"), 1.0))
    target_atr = max(0.1, number(risk.get("target_atr"), 2.0))
    cost_r = max(0.0, number(risk.get("cost_r"), 0.04))
    if direction > 0:
        favourable = number(outcome.get("max_up_atr"))
        adverse = number(outcome.get("max_down_atr"))
    else:
        favourable = number(outcome.get("max_down_atr"))
        adverse = number(outcome.get("max_up_atr"))

    # Conservative ordering: if both barriers were reachable, assume the stop hit first.
    if adverse >= stop_atr:
        gross = -1.0
    elif favourable >= target_atr:
        gross = target_atr / stop_atr
    else:
        close = number(row.get("close"))
        atr = number(row.get("atr_14"))
        move_pct = number(outcome.get("close_return_pct")) / 100.0
        move_atr = (close * move_pct / atr) if close and atr else 0.0
        gross = max(-1.0, min(target_atr / stop_atr, direction * move_atr / stop_atr))
    return gross - cost_r


@dataclass(frozen=True)
class SegmentMetrics:
    trades: int
    wins: int
    losses: int
    win_rate: float
    net_r: float
    expectancy_r: float
    profit_factor: float
    max_drawdown_r: float
    positive_year_rate: float
    yearly_expectancy: dict[str, float]
    weekday_expectancy: dict[str, float]
    session_expectancy: dict[str, float]

    def as_dict(self) -> dict[str, Any]:
        return {
            "trades": self.trades,
            "wins": self.wins,
            "losses": self.losses,
            "win_rate": round(self.win_rate, 5),
            "net_r": round(self.net_r, 6),
            "expectancy_r": round(self.expectancy_r, 6),
            "profit_factor": round(self.profit_factor, 6),
            "max_drawdown_r": round(self.max_drawdown_r, 6),
            "positive_year_rate": round(self.positive_year_rate, 6),
            "yearly_expectancy": {k: round(v, 6) for k, v in self.yearly_expectancy.items()},
            "weekday_expectancy": {k: round(v, 6) for k, v in self.weekday_expectancy.items()},
            "session_expectancy": {k: round(v, 6) for k, v in self.session_expectancy.items()},
        }


def evaluate_segment(rows: Iterable[dict[str, Any]], rules: dict[str, Any]) -> SegmentMetrics:
    risk = dict(rules.get("risk") or {})
    cooldown = max(5, int(number(risk.get("cooldown_minutes"), risk.get("horizon_minutes") or 60)))
    next_allowed: datetime | None = None
    records: list[tuple[datetime, float, int, str]] = []

    for row in rows:
        time = as_utc(row.get("candle_time"))
        if not time or (next_allowed and time < next_allowed):
            continue
        if not row_is_eligible(row, rules):
            continue
        direction = candidate_direction(row, rules)
        pnl = trade_r(row, direction, risk)
        if pnl is None:
            continue
        records.append((time, pnl, int(number(row.get("weekday"))), str(row.get("session") or "unknown")))
        next_allowed = time + timedelta(minutes=cooldown)

    pnls = [item[1] for item in records]
    wins = sum(1 for value in pnls if value > 0)
    losses = sum(1 for value in pnls if value < 0)
    gross_profit = sum(value for value in pnls if value > 0)
    gross_loss = abs(sum(value for value in pnls if value < 0))
    pf = gross_profit / gross_loss if gross_loss > 1e-12 else (99.0 if gross_profit > 0 else 0.0)
    equity = peak = drawdown = 0.0
    yearly: dict[str, list[float]] = defaultdict(list)
    weekdays: dict[str, list[float]] = defaultdict(list)
    sessions: dict[str, list[float]] = defaultdict(list)
    for time, pnl, weekday, session in records:
        equity += pnl
        peak = max(peak, equity)
        drawdown = max(drawdown, peak - equity)
        yearly[str(time.year)].append(pnl)
        weekdays[str(weekday)].append(pnl)
        sessions[session].append(pnl)
    yearly_exp = {key: sum(values) / len(values) for key, values in yearly.items() if values}
    positive_year_rate = sum(1 for value in yearly_exp.values() if value > 0) / len(yearly_exp) if yearly_exp else 0.0
    return SegmentMetrics(
        trades=len(pnls), wins=wins, losses=losses,
        win_rate=wins / len(pnls) * 100.0 if pnls else 0.0,
        net_r=sum(pnls), expectancy_r=sum(pnls) / len(pnls) if pnls else 0.0,
        profit_factor=pf, max_drawdown_r=drawdown, positive_year_rate=positive_year_rate,
        yearly_expectancy=yearly_exp,
        weekday_expectancy={key: sum(values) / len(values) for key, values in weekdays.items() if values},
        session_expectancy={key: sum(values) / len(values) for key, values in sessions.items() if values},
    )


def chronological_segments(rows: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    ordered = sorted(rows, key=lambda row: str(row.get("candle_time") or ""))
    by_year: dict[int, list[dict[str, Any]]] = defaultdict(list)
    for row in ordered:
        time = as_utc(row.get("candle_time"))
        if time:
            by_year[time.year].append(row)
    years = sorted(by_year)
    if len(years) >= 6:
        development_years = years[:-3]
        validation_years = [years[-3]]
        locked_years = [years[-2]]
        recent_years = [years[-1]]
        return {
            "development": [row for year in development_years for row in by_year[year]],
            "validation": [row for year in validation_years for row in by_year[year]],
            "locked": [row for year in locked_years for row in by_year[year]],
            "recent": [row for year in recent_years for row in by_year[year]],
            "years": years,
        }

    n = len(ordered)
    a, b, c = int(n * 0.55), int(n * 0.72), int(n * 0.87)
    return {
        "development": ordered[:a],
        "validation": ordered[a:b],
        "locked": ordered[b:c],
        "recent": ordered[c:],
        "years": years,
    }


def walk_forward(rows: list[dict[str, Any]], rules: dict[str, Any]) -> dict[str, Any]:
    by_year: dict[int, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        time = as_utc(row.get("candle_time"))
        if time:
            by_year[time.year].append(row)
    results: list[dict[str, Any]] = []
    for year in sorted(by_year):
        metrics = evaluate_segment(by_year[year], rules)
        if metrics.trades:
            results.append({"year": year, **metrics.as_dict()})
    positive = sum(1 for item in results if number(item.get("expectancy_r")) > 0)
    return {
        "years": results,
        "positive_years": positive,
        "tested_years": len(results),
        "stability": positive / len(results) if results else 0.0,
    }


def fitness(metrics: dict[str, SegmentMetrics], everyday_target: bool) -> float:
    validation = metrics["validation"]
    locked = metrics["locked"]
    recent = metrics["recent"]
    sample = min(1.0, (validation.trades + locked.trades + recent.trades) / 300.0)
    coverage = 4.0 if everyday_target else 0.0
    return (
        min(validation.profit_factor, 3.0) * 12.0
        + validation.expectancy_r * 80.0
        + min(locked.profit_factor, 3.0) * 14.0
        + locked.expectancy_r * 100.0
        + min(recent.profit_factor, 3.0) * 8.0
        + recent.expectancy_r * 55.0
        + (locked.positive_year_rate + recent.positive_year_rate) * 8.0
        + sample * 8.0
        + coverage
        - locked.max_drawdown_r * 0.45
        - recent.max_drawdown_r * 0.30
    )


def robustness_neighbours(rows: list[dict[str, Any]], rules: dict[str, Any]) -> dict[str, Any]:
    risk = dict(rules.get("risk") or {})
    stop = number(risk.get("stop_atr"), 1.0)
    target = number(risk.get("target_atr"), 2.0)
    variants: list[dict[str, Any]] = []
    for stop_mult, target_mult in ((0.9, 1.0), (1.1, 1.0), (1.0, 0.9), (1.0, 1.1)):
        variant = copy.deepcopy(rules)
        variant["risk"]["stop_atr"] = round(max(0.25, stop * stop_mult), 4)
        variant["risk"]["target_atr"] = round(max(0.25, target * target_mult), 4)
        metrics = evaluate_segment(rows, variant)
        variants.append({
            "stop_atr": variant["risk"]["stop_atr"],
            "target_atr": variant["risk"]["target_atr"],
            **metrics.as_dict(),
        })
    passing = [item for item in variants if item["trades"] >= 30 and item["expectancy_r"] > 0 and item["profit_factor"] >= 1.02]
    return {"variants": variants, "passing": len(passing), "total": len(variants), "pass_rate": len(passing) / len(variants)}


def evaluate_strategy(candidate: dict[str, Any], rows: list[dict[str, Any]], *, min_validation_trades: int = 60,
                      min_locked_trades: int = 80) -> dict[str, Any]:
    rules = dict(candidate.get("rules") or {})
    segments = chronological_segments(rows)
    metrics = {
        name: evaluate_segment(segments[name], rules)
        for name in ("development", "validation", "locked", "recent")
    }
    wf = walk_forward(rows, rules)
    robustness = robustness_neighbours(segments["locked"] + segments["recent"], rules)
    score = fitness(metrics, bool(rules.get("schedule", {}).get("everyday_target")))

    validation = metrics["validation"]
    locked = metrics["locked"]
    recent = metrics["recent"]
    enough = validation.trades >= min_validation_trades and locked.trades >= min_locked_trades
    recent_enough = recent.trades >= max(20, min_locked_trades // 3)
    no_collapse = recent.expectancy_r > -0.02 and recent.profit_factor >= 0.95
    stable = wf["stability"] >= 0.60

    if (
        enough and recent_enough and stable and no_collapse and robustness["pass_rate"] >= 0.75
        and validation.profit_factor >= 1.20 and locked.profit_factor >= 1.30
        and validation.expectancy_r >= 0.07 and locked.expectancy_r >= 0.09
    ):
        status = "elite"
    elif (
        enough and recent_enough and stable and no_collapse and robustness["pass_rate"] >= 0.50
        and validation.profit_factor >= 1.08 and locked.profit_factor >= 1.15
        and validation.expectancy_r >= 0.03 and locked.expectancy_r >= 0.04
    ):
        status = "validated"
    elif (
        validation.trades >= 35 and locked.trades >= 40
        and validation.expectancy_r > 0 and locked.expectancy_r > 0
        and validation.profit_factor >= 1.02 and locked.profit_factor >= 1.03
    ):
        status = "promising"
    else:
        status = "rejected"

    all_metrics = {name: value.as_dict() for name, value in metrics.items()}
    summary = (
        f"{candidate.get('name')} tested across {len(segments.get('years') or [])} calendar years. "
        f"Validation PF {validation.profit_factor:.2f}, locked PF {locked.profit_factor:.2f}, "
        f"recent PF {recent.profit_factor:.2f}, locked expectancy {locked.expectancy_r:+.3f}R, "
        f"walk-forward stability {wf['stability'] * 100:.0f}%."
    )
    return {
        "result_status": status,
        "rows_scanned": len(rows),
        "trades_total": validation.trades + locked.trades + recent.trades,
        "profit_factor": round(locked.profit_factor, 8),
        "expectancy_r": round(locked.expectancy_r, 8),
        "max_drawdown_r": round(locked.max_drawdown_r, 8),
        "win_rate": round(locked.win_rate, 8),
        "stability_score": round(wf["stability"] * 100.0, 8),
        "fitness_score": round(score, 8),
        "metrics": all_metrics,
        "walk_forward": wf,
        "robustness": robustness,
        "evidence": {
            "summary": summary,
            "data_split": {
                "method": "calendar-year chronological split when six or more years are available",
                "years": segments.get("years") or [],
                "development_rows": len(segments["development"]),
                "validation_rows": len(segments["validation"]),
                "locked_rows": len(segments["locked"]),
                "recent_rows": len(segments["recent"]),
            },
            "caveats": [
                "This stage uses EVE's completed market-state outcomes, not broker tick execution.",
                "When stop and target were both reachable during the horizon, the stop is counted first.",
                "Transaction costs are represented by a fixed R deduction.",
                "MT5-ready status still requires compile and demo forward testing.",
            ],
        },
    }


def compare_child_to_parent(child_result: dict[str, Any], parent_metrics_payload: dict[str, Any], parent_fitness: float) -> dict[str, Any]:
    child_fitness = number(child_result.get("fitness_score"))
    parent_validation = dict(parent_metrics_payload.get("validation") or {})
    parent_locked = dict(parent_metrics_payload.get("locked") or parent_metrics_payload.get("locked_test") or {})
    child_validation = dict(child_result.get("metrics", {}).get("validation") or {})
    child_locked = dict(child_result.get("metrics", {}).get("locked") or {})

    validation_delta = number(child_validation.get("expectancy_r")) - number(parent_validation.get("expectancy_r"))
    pf_delta = number(child_validation.get("profit_factor")) - number(parent_validation.get("profit_factor"))
    locked_veto = (
        number(child_locked.get("expectancy_r")) < -0.02
        or number(child_locked.get("profit_factor")) < 0.95
        or number(child_locked.get("max_drawdown_r")) > max(8.0, number(parent_locked.get("max_drawdown_r")) * 1.75)
    )
    promoted = (
        not locked_veto
        and child_result.get("result_status") in {"promising", "validated", "elite"}
        and child_fitness > parent_fitness + 0.25
        and (validation_delta > 0.005 or pf_delta > 0.02)
    )
    reason = (
        f"Promoted: validation expectancy changed {validation_delta:+.3f}R and validation PF changed {pf_delta:+.2f}."
        if promoted else
        f"Rejected as champion: fitness delta {child_fitness - parent_fitness:+.2f}, validation expectancy delta {validation_delta:+.3f}R, locked veto={locked_veto}."
    )
    return {
        **child_result,
        "promoted": promoted,
        "selection_reason": reason,
        "fitness_delta": round(child_fitness - parent_fitness, 8),
        "validation_expectancy_delta": round(validation_delta, 8),
        "validation_pf_delta": round(pf_delta, 8),
        "locked_veto": locked_veto,
    }
