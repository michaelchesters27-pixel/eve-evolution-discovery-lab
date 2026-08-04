from __future__ import annotations

import copy
import hashlib
import json
import math
import random
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Iterable, Literal

ResearchStage = Literal["selection", "final"]
RESEARCH_INTEGRITY_VERSION = "eve-research-integrity-v2.0"

_DATASET_CACHE_ROWS: list[dict[str, Any]] | None = None
_DATASET_CACHE_VALUE: dict[str, Any] | None = None


def number(value: Any, default: float = 0.0) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return default
    return parsed if math.isfinite(parsed) else default


def as_utc(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        return value.astimezone(timezone.utc) if value.tzinfo else value.replace(tzinfo=timezone.utc)
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed.astimezone(timezone.utc) if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


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


def candle_body(row: dict[str, Any]) -> float:
    """Absolute candle body, matching generated MT5 feature calculation."""
    return max(abs(number(row.get("body_price"))), 1e-9)


def recipe_condition_matches(row: dict[str, Any], condition: dict[str, Any]) -> bool:
    kind = str(condition.get("type") or "")
    direction = sign(row.get("direction"))
    trend12 = sign(row.get("trend_12_atr"))
    trend48 = sign(row.get("trend_48_atr"))
    alignment = sign(row.get("alignment_score"))
    return_1 = number(row.get("return_1_pct"))
    return_3 = number(row.get("return_3_pct"))
    close_location = number(row.get("close_location"), 0.5)
    upper = max(0.0, number(row.get("upper_wick")))
    lower = max(0.0, number(row.get("lower_wick")))
    body = candle_body(row)

    if kind == "direction_matches_trend12":
        return direction != 0 and trend12 != 0 and direction == trend12
    if kind == "direction_opposes_trend12":
        return direction != 0 and trend12 != 0 and direction == -trend12
    if kind == "alignment_abs_min":
        return abs(int(number(row.get("alignment_score")))) >= int(number(condition.get("min"), 1))
    if kind == "alignment_matches_direction":
        return alignment != 0 and direction != 0 and alignment == direction
    if kind == "alignment_opposes_direction":
        return alignment != 0 and direction != 0 and alignment == -direction
    if kind == "return_3_abs_min":
        return abs(return_3) >= number(condition.get("threshold"), 0.005)
    if kind == "return_3_matches_direction":
        return direction != 0 and sign(return_3) == direction
    if kind == "impulse_1_vs_3":
        return abs(return_3) > 1e-12 and abs(return_1) >= abs(return_3) * number(condition.get("ratio"), 0.25)
    if kind == "close_location_extreme":
        edge = max(0.01, min(0.49, number(condition.get("edge"), 0.20)))
        return close_location <= edge or close_location >= 1.0 - edge
    if kind == "wick_body_ratio_min":
        return max(upper, lower) / body >= number(condition.get("ratio"), 1.5)
    if kind == "trend12_trend48_agree":
        return trend12 != 0 and trend48 != 0 and trend12 == trend48
    return False


def recipe_matches(row: dict[str, Any], rules: dict[str, Any]) -> bool:
    entry = dict(rules.get("entry") or {})
    conditions = [dict(item) for item in entry.get("conditions") or [] if isinstance(item, dict)]
    if not conditions:
        return False
    mode = str(entry.get("condition_mode") or "all")
    matches = [recipe_condition_matches(row, condition) for condition in conditions]
    return any(matches) if mode == "any" else all(matches)


def family_matches(row: dict[str, Any], rules: dict[str, Any]) -> bool:
    family = str(rules.get("family") or "momentum_continuation")
    direction = sign(row.get("direction"))
    trend = sign(row.get("trend_12_atr"))
    alignment = sign(row.get("alignment_score"))
    close_location = number(row.get("close_location"), 0.5)
    upper = max(0.0, number(row.get("upper_wick")))
    lower = max(0.0, number(row.get("lower_wick")))
    body = candle_body(row)

    if family == "momentum_continuation":
        return direction != 0 and trend != 0 and direction == trend and abs(number(row.get("return_3_pct"))) > 0.005
    if family == "alignment_continuation":
        minimum = int(number(rules.get("environment", {}).get("min_alignment_abs"), 1))
        return alignment != 0 and abs(int(number(row.get("alignment_score")))) >= minimum
    if family == "pullback_continuation":
        return trend != 0 and direction != 0 and direction == -trend
    if family == "volatility_breakout":
        return direction != 0 and abs(number(row.get("return_1_pct"))) > abs(number(row.get("return_3_pct"))) / 4.0
    if family == "mean_reversion":
        return direction != 0 and (close_location <= 0.20 or close_location >= 0.80)
    if family == "candle_reversal":
        ratio = number(rules.get("entry", {}).get("wick_ratio_min"), 1.5)
        return max(upper, lower) / body >= ratio
    if family == "composed_signal":
        return recipe_matches(row, rules)
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
    market = dict(rules.get("market") or {})
    required_symbol = str(market.get("symbol") or "")
    required_snapshot = str(market.get("snapshot_interval") or "")
    required_source = str(market.get("source_interval") or "")
    if required_symbol and row.get("symbol") and str(row.get("symbol")) != required_symbol:
        return False
    if required_snapshot and row.get("snapshot_interval") and str(row.get("snapshot_interval")) != required_snapshot:
        return False
    if required_source and row.get("source_interval") and str(row.get("source_interval")) != required_source:
        return False
    return (
        schedule_matches(row, dict(rules.get("schedule") or {}))
        and environment_matches(row, dict(rules.get("environment") or {}))
        and family_matches(row, rules)
    )


def trade_r(row: dict[str, Any], direction: int, risk: dict[str, Any], *, cost_r: float | None = None) -> float | None:
    horizon = int(number(risk.get("horizon_minutes"), 60))
    outcome = outcome_for(row, horizon)
    if not outcome or direction == 0:
        return None

    stop_atr = max(0.1, number(risk.get("stop_atr"), 1.0))
    target_atr = max(0.1, number(risk.get("target_atr"), 2.0))
    applied_cost = max(0.0, number(risk.get("cost_r"), 0.04) if cost_r is None else cost_r)
    if direction > 0:
        favourable = number(outcome.get("max_up_atr"))
        adverse = number(outcome.get("max_down_atr"))
    else:
        favourable = number(outcome.get("max_down_atr"))
        adverse = number(outcome.get("max_up_atr"))

    # With no tick path, count the stop first whenever both barriers were reachable.
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
    return gross - applied_cost


@dataclass(frozen=True)
class TradeRecord:
    time: datetime
    pnl_r: float
    weekday: int
    session: str
    regime: str


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
    regime_expectancy: dict[str, float]
    yearly_trades: dict[str, int]
    weekday_trades: dict[str, int]
    session_trades: dict[str, int]
    regime_trades: dict[str, int]
    trading_days: int
    trades_per_day: float

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
            "regime_expectancy": {k: round(v, 6) for k, v in self.regime_expectancy.items()},
            "yearly_trades": self.yearly_trades,
            "weekday_trades": self.weekday_trades,
            "session_trades": self.session_trades,
            "regime_trades": self.regime_trades,
            "trading_days": self.trading_days,
            "trades_per_day": round(self.trades_per_day, 6),
        }


def _trade_records(rows: Iterable[dict[str, Any]], rules: dict[str, Any], *, cost_r: float | None = None) -> list[TradeRecord]:
    risk = dict(rules.get("risk") or {})
    cooldown = max(1, int(number(risk.get("cooldown_minutes"), 0)))
    max_hold = max(1, int(number(risk.get("max_hold_minutes"), risk.get("horizon_minutes") or 60)))
    # The generated EA has one-position-at-a-time semantics. Lock entries for the
    # full potential holding window even when the configured cooldown is shorter.
    entry_lock = max(cooldown, max_hold)
    next_allowed: datetime | None = None
    records: list[TradeRecord] = []

    ordered = sorted(rows, key=lambda item: str(item.get("candle_time") or ""))
    for row in ordered:
        time = as_utc(row.get("candle_time"))
        if not time or (next_allowed and time < next_allowed):
            continue
        if not row_is_eligible(row, rules):
            continue
        direction = candidate_direction(row, rules)
        pnl = trade_r(row, direction, risk, cost_r=cost_r)
        if pnl is None:
            continue
        records.append(
            TradeRecord(
                time=time,
                pnl_r=pnl,
                weekday=int(number(row.get("weekday"))),
                session=str(row.get("session") or "unknown"),
                regime=str(row.get("regime") or "unknown"),
            )
        )
        next_allowed = time + timedelta(minutes=entry_lock)
    return records


def _metrics(records: list[TradeRecord]) -> SegmentMetrics:
    pnls = [item.pnl_r for item in records]
    wins = sum(1 for value in pnls if value > 0)
    losses = sum(1 for value in pnls if value < 0)
    gross_profit = sum(value for value in pnls if value > 0)
    gross_loss = abs(sum(value for value in pnls if value < 0))
    pf = gross_profit / gross_loss if gross_loss > 1e-12 else (99.0 if gross_profit > 0 else 0.0)
    equity = peak = drawdown = 0.0
    yearly: dict[str, list[float]] = defaultdict(list)
    weekdays: dict[str, list[float]] = defaultdict(list)
    sessions: dict[str, list[float]] = defaultdict(list)
    regimes: dict[str, list[float]] = defaultdict(list)
    days: set[str] = set()
    for item in records:
        equity += item.pnl_r
        peak = max(peak, equity)
        drawdown = max(drawdown, peak - equity)
        yearly[str(item.time.year)].append(item.pnl_r)
        weekdays[str(item.weekday)].append(item.pnl_r)
        sessions[item.session].append(item.pnl_r)
        regimes[item.regime].append(item.pnl_r)
        days.add(item.time.date().isoformat())
    yearly_exp = {key: sum(values) / len(values) for key, values in yearly.items() if values}
    positive_year_rate = sum(1 for value in yearly_exp.values() if value > 0) / len(yearly_exp) if yearly_exp else 0.0
    return SegmentMetrics(
        trades=len(pnls),
        wins=wins,
        losses=losses,
        win_rate=wins / len(pnls) * 100.0 if pnls else 0.0,
        net_r=sum(pnls),
        expectancy_r=sum(pnls) / len(pnls) if pnls else 0.0,
        profit_factor=pf,
        max_drawdown_r=drawdown,
        positive_year_rate=positive_year_rate,
        yearly_expectancy=yearly_exp,
        weekday_expectancy={key: sum(values) / len(values) for key, values in weekdays.items() if values},
        session_expectancy={key: sum(values) / len(values) for key, values in sessions.items() if values},
        regime_expectancy={key: sum(values) / len(values) for key, values in regimes.items() if values},
        yearly_trades={key: len(values) for key, values in yearly.items()},
        weekday_trades={key: len(values) for key, values in weekdays.items()},
        session_trades={key: len(values) for key, values in sessions.items()},
        regime_trades={key: len(values) for key, values in regimes.items()},
        trading_days=len(days),
        trades_per_day=len(pnls) / len(days) if days else 0.0,
    )


def evaluate_segment(rows: Iterable[dict[str, Any]], rules: dict[str, Any], *, cost_r: float | None = None) -> SegmentMetrics:
    return _metrics(_trade_records(rows, rules, cost_r=cost_r))


def chronological_segments(rows: list[dict[str, Any]]) -> dict[str, Any]:
    ordered = sorted(rows, key=lambda row: str(row.get("candle_time") or ""))
    by_year: dict[int, list[dict[str, Any]]] = defaultdict(list)
    for row in ordered:
        time = as_utc(row.get("candle_time"))
        if time:
            by_year[time.year].append(row)
    years = sorted(by_year)
    if len(years) >= 6:
        return {
            "development": [row for year in years[:-3] for row in by_year[year]],
            "validation": list(by_year[years[-3]]),
            "confirmation": list(by_year[years[-2]]),
            "holdout": list(by_year[years[-1]]),
            "years": years,
            "method": "calendar_year_four_stage",
        }

    n = len(ordered)
    a, b, c = int(n * 0.50), int(n * 0.70), int(n * 0.85)
    return {
        "development": ordered[:a],
        "validation": ordered[a:b],
        "confirmation": ordered[b:c],
        "holdout": ordered[c:],
        "years": years,
        "method": "chronological_fraction_four_stage",
    }


def rolling_validation(rows: list[dict[str, Any]], rules: dict[str, Any]) -> dict[str, Any]:
    """Anchored, chronological next-year tests of the fixed candidate rules.

    Candidate parameters are never re-selected inside a fold. The report therefore
    measures stability across successive unseen years without pretending that the
    system fitted a different model in each fold.
    """
    by_year: dict[int, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        time = as_utc(row.get("candle_time"))
        if time:
            by_year[time.year].append(row)
    years = sorted(by_year)
    folds: list[dict[str, Any]] = []
    for index in range(2, len(years)):
        train_years = years[:index]
        test_year = years[index]
        metrics = evaluate_segment(by_year[test_year], rules)
        if metrics.trades:
            folds.append({
                "development_years": train_years,
                "test_year": test_year,
                **metrics.as_dict(),
            })
    positive = sum(1 for item in folds if number(item.get("expectancy_r")) > 0)
    return {
        "method": "anchored_next_year_fixed_rules",
        "folds": folds,
        # Backward-compatible alias used by the v1 frontend.
        "years": [{"year": item["test_year"], **{k: v for k, v in item.items() if k not in {"test_year", "development_years"}}} for item in folds],
        "positive_folds": positive,
        "positive_years": positive,
        "tested_folds": len(folds),
        "tested_years": len(folds),
        "stability": positive / len(folds) if folds else 0.0,
    }


def fitness(metrics: dict[str, SegmentMetrics], everyday_target: bool) -> float:
    """Selection fitness uses development and validation only.

    Confirmation and final holdout are deliberately absent so repeated mutation
    cannot learn from them indirectly.
    """
    development = metrics["development"]
    validation = metrics["validation"]
    sample = min(1.0, (development.trades + validation.trades) / 300.0)
    coverage = 3.0 if everyday_target else 0.0
    return (
        min(development.profit_factor, 3.0) * 5.0
        + development.expectancy_r * 25.0
        + min(validation.profit_factor, 3.0) * 18.0
        + validation.expectancy_r * 120.0
        + validation.positive_year_rate * 6.0
        + sample * 8.0
        + coverage
        - validation.max_drawdown_r * 0.55
    )


def robustness_neighbours(rows: list[dict[str, Any]], rules: dict[str, Any], *, minimum_trades: int = 30) -> dict[str, Any]:
    risk = dict(rules.get("risk") or {})
    stop = number(risk.get("stop_atr"), 1.0)
    target = number(risk.get("target_atr"), 2.0)
    variants: list[dict[str, Any]] = []
    for label, stop_mult, target_mult in (
        ("stop_minus_10", 0.9, 1.0),
        ("stop_plus_10", 1.1, 1.0),
        ("target_minus_10", 1.0, 0.9),
        ("target_plus_10", 1.0, 1.1),
        ("both_tighter", 0.9, 0.9),
        ("both_wider", 1.1, 1.1),
    ):
        variant = copy.deepcopy(rules)
        variant.setdefault("risk", {})["stop_atr"] = round(max(0.25, stop * stop_mult), 4)
        variant["risk"]["target_atr"] = round(max(0.25, target * target_mult), 4)
        metrics = evaluate_segment(rows, variant)
        variants.append({
            "label": label,
            "stop_atr": variant["risk"]["stop_atr"],
            "target_atr": variant["risk"]["target_atr"],
            **metrics.as_dict(),
        })
    passing = [
        item for item in variants
        if item["trades"] >= minimum_trades and item["expectancy_r"] > 0 and item["profit_factor"] >= 1.02
    ]
    return {
        "variants": variants,
        "passing": len(passing),
        "total": len(variants),
        "pass_rate": len(passing) / len(variants) if variants else 0.0,
    }


def cost_stress(rows: list[dict[str, Any]], rules: dict[str, Any]) -> dict[str, Any]:
    base = max(0.0, number(rules.get("risk", {}).get("cost_r"), 0.04))
    profiles = {
        "standard": max(0.03, base),
        "elevated": max(0.06, base * 2.0),
        "severe": max(0.10, base * 3.0),
    }
    return {
        name: {"cost_r": cost, **evaluate_segment(rows, rules, cost_r=cost).as_dict()}
        for name, cost in profiles.items()
    }


def monte_carlo_sequence(rows: list[dict[str, Any]], rules: dict[str, Any], *, simulations: int = 400) -> dict[str, Any]:
    records = _trade_records(rows, rules)
    pnls = [record.pnl_r for record in records]
    if len(pnls) < 20:
        return {"simulations": 0, "trades": len(pnls), "pass_rate": 0.0, "p05_expectancy_r": 0.0, "p95_max_drawdown_r": 0.0}
    digest = hashlib.sha256(json.dumps(rules, sort_keys=True, default=str).encode()).hexdigest()
    rng = random.Random(int(digest[:16], 16))
    expectancies: list[float] = []
    drawdowns: list[float] = []
    positive = 0
    for _ in range(simulations):
        sample = [pnls[rng.randrange(len(pnls))] for _ in pnls]
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
        "simulations": simulations,
        "trades": len(pnls),
        "pass_rate": positive / simulations,
        "p05_expectancy_r": round(p05, 6),
        "p95_max_drawdown_r": round(p95_dd, 6),
    }


def dataset_fingerprint(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Hash the evidence actually used by the research engine.

    The current rows object is cached because the autonomous worker reuses one
    immutable in-memory dataset for many candidates. A new source sync replaces
    the list and therefore forces a new content hash.
    """
    global _DATASET_CACHE_ROWS, _DATASET_CACHE_VALUE
    if _DATASET_CACHE_ROWS is rows and _DATASET_CACHE_VALUE is not None:
        return dict(_DATASET_CACHE_VALUE)

    ordered = sorted(rows, key=lambda row: str(row.get("candle_time") or ""))
    first = ordered[0] if ordered else {}
    last = ordered[-1] if ordered else {}
    feature_versions = sorted({str(row.get("feature_version") or "unknown") for row in ordered})
    content = hashlib.sha256()
    for row in ordered:
        research_record = [
            row.get("symbol"), row.get("snapshot_interval"), row.get("source_interval"),
            row.get("candle_time"), row.get("open"), row.get("high"), row.get("low"), row.get("close"),
            row.get("direction"), row.get("body_price"), row.get("upper_wick"), row.get("lower_wick"),
            row.get("atr_14"), row.get("compression_ratio"), row.get("return_1_pct"), row.get("return_3_pct"),
            row.get("trend_12_atr"), row.get("trend_48_atr"), row.get("regime"), row.get("alignment_score"),
            row.get("outcomes"), row.get("outcome_complete"), row.get("feature_version"),
        ]
        content.update(json.dumps(research_record, separators=(",", ":"), sort_keys=True, default=str).encode())
        content.update(b"\n")
    digest = content.hexdigest()
    payload = {
        "rows": len(ordered),
        "from": first.get("candle_time"),
        "to": last.get("candle_time"),
        "symbols": sorted({str(row.get("symbol") or "unknown") for row in ordered}),
        "snapshot_intervals": sorted({str(row.get("snapshot_interval") or "unknown") for row in ordered}),
        "feature_versions": feature_versions,
        "content_sha256": digest,
        "version": f"dataset-{digest[:16]}",
        "sha256": digest,
    }
    _DATASET_CACHE_ROWS = rows
    _DATASET_CACHE_VALUE = dict(payload)
    return payload


def _sealed_segment(label: str) -> dict[str, Any]:
    return {"sealed": True, "label": label, "message": "Not opened during strategy selection or mutation."}


def selection_ready_for_final(result: dict[str, Any]) -> bool:
    validation = dict(result.get("metrics", {}).get("validation") or {})
    robustness = dict(result.get("robustness") or {})
    mc = dict(result.get("monte_carlo") or {})
    rolling = dict(result.get("walk_forward") or {})
    return (
        result.get("research_stage") == "selection"
        and result.get("result_status") == "promising"
        and number(validation.get("profit_factor")) >= 1.15
        and number(validation.get("expectancy_r")) >= 0.05
        and number(robustness.get("pass_rate")) >= 0.60
        and number(rolling.get("stability")) >= 0.60
        and number(mc.get("pass_rate")) >= 0.80
    )


def evaluate_strategy(
    candidate: dict[str, Any],
    rows: list[dict[str, Any]],
    *,
    min_validation_trades: int = 60,
    min_locked_trades: int = 80,
    stage: ResearchStage = "final",
) -> dict[str, Any]:
    rules = dict(candidate.get("rules") or {})
    market = dict(rules.get("market") or {})
    symbol = str(market.get("symbol") or "")
    snapshot_interval = str(market.get("snapshot_interval") or "")
    source_interval = str(market.get("source_interval") or "")
    research_rows = [
        row for row in rows
        if (not symbol or not row.get("symbol") or str(row.get("symbol")) == symbol)
        and (not snapshot_interval or not row.get("snapshot_interval") or str(row.get("snapshot_interval")) == snapshot_interval)
        and (not source_interval or not row.get("source_interval") or str(row.get("source_interval")) == source_interval)
    ]
    segments = chronological_segments(research_rows)
    development = evaluate_segment(segments["development"], rules)
    validation = evaluate_segment(segments["validation"], rules)
    selection_metrics = {"development": development, "validation": validation}
    score = fitness(selection_metrics, bool(rules.get("schedule", {}).get("everyday_target")))
    rolling = rolling_validation(segments["development"] + segments["validation"], rules)
    robustness = robustness_neighbours(segments["validation"], rules, minimum_trades=max(20, min_validation_trades // 2))
    monte_carlo = monte_carlo_sequence(segments["validation"], rules)

    validation_sample = validation.trades >= min_validation_trades
    selection_gates = {
        "validation_sample": validation_sample,
        "validation_edge": validation.profit_factor >= 1.08 and validation.expectancy_r >= 0.03,
        "rolling_stability": rolling["stability"] >= 0.60,
        "parameter_neighbourhood": robustness["pass_rate"] >= 0.50,
        "monte_carlo_confidence": monte_carlo["pass_rate"] >= 0.70 and monte_carlo["p05_expectancy_r"] > -0.03,
    }
    selection_passed = all(selection_gates.values())

    confirmation: SegmentMetrics | None = None
    holdout: SegmentMetrics | None = None
    execution_costs: dict[str, Any] = {}
    final_gates: dict[str, bool] = {}
    if stage == "final":
        confirmation = evaluate_segment(segments["confirmation"], rules)
        holdout = evaluate_segment(segments["holdout"], rules)
        combined_final = segments["confirmation"] + segments["holdout"]
        execution_costs = cost_stress(combined_final, rules)
        final_robustness = robustness_neighbours(combined_final, rules, minimum_trades=max(25, min_locked_trades // 3))
        final_gates = {
            "confirmation_sample": confirmation.trades >= min_locked_trades,
            "holdout_sample": holdout.trades >= max(20, min_locked_trades // 3),
            "confirmation_edge": confirmation.profit_factor >= 1.15 and confirmation.expectancy_r >= 0.04,
            "holdout_no_collapse": holdout.profit_factor >= 1.00 and holdout.expectancy_r >= -0.01,
            "elevated_cost_survival": number(execution_costs.get("elevated", {}).get("expectancy_r")) > 0,
            "final_parameter_neighbourhood": final_robustness["pass_rate"] >= 0.50,
        }
        robustness = {
            **robustness,
            "selection": robustness,
            "final": final_robustness,
            "pass_rate": min(robustness["pass_rate"], final_robustness["pass_rate"]),
        }

    if stage == "selection":
        status = "promising" if selection_passed else "rejected"
    elif selection_passed and all(final_gates.values()):
        assert confirmation is not None and holdout is not None
        elite = (
            validation.profit_factor >= 1.20
            and validation.expectancy_r >= 0.07
            and confirmation.profit_factor >= 1.30
            and confirmation.expectancy_r >= 0.09
            and holdout.profit_factor >= 1.08
            and holdout.expectancy_r >= 0.02
            and number(execution_costs.get("elevated", {}).get("profit_factor")) >= 1.05
            and robustness["pass_rate"] >= 0.75
        )
        status = "elite" if elite else "validated"
    elif selection_passed:
        status = "promising"
    else:
        status = "rejected"

    gate_checks = {**selection_gates, **final_gates}
    failed_gates = [name for name, passed in gate_checks.items() if not passed]
    all_metrics: dict[str, Any] = {
        "development": development.as_dict(),
        "validation": validation.as_dict(),
    }
    if confirmation is not None and holdout is not None:
        all_metrics.update({
            "confirmation": confirmation.as_dict(),
            "holdout": holdout.as_dict(),
            # v1 aliases retained for existing UI/data consumers.
            "locked": confirmation.as_dict(),
            "recent": holdout.as_dict(),
        })
    else:
        all_metrics.update({
            "confirmation": _sealed_segment("confirmation"),
            "holdout": _sealed_segment("final_holdout"),
            "locked": _sealed_segment("confirmation"),
            "recent": _sealed_segment("final_holdout"),
        })

    reference = confirmation if confirmation is not None else validation
    data = dataset_fingerprint(research_rows)
    summary = (
        f"{candidate.get('name')} completed {stage} research on {data['rows']:,} immutable market states. "
        f"Validation PF {validation.profit_factor:.2f}, expectancy {validation.expectancy_r:+.3f}R. "
        + (
            f"Confirmation PF {confirmation.profit_factor:.2f}; final holdout PF {holdout.profit_factor:.2f}."
            if confirmation is not None and holdout is not None
            else "Confirmation and final holdout remain sealed during selection."
        )
    )
    result = {
        "research_stage": stage,
        "research_integrity_version": RESEARCH_INTEGRITY_VERSION,
        "result_status": status,
        "rows_scanned": len(research_rows),
        "trades_total": validation.trades + (confirmation.trades if confirmation else 0) + (holdout.trades if holdout else 0),
        "profit_factor": round(reference.profit_factor, 8),
        "expectancy_r": round(reference.expectancy_r, 8),
        "max_drawdown_r": round(reference.max_drawdown_r, 8),
        "win_rate": round(reference.win_rate, 8),
        "stability_score": round(rolling["stability"] * 100.0, 8),
        "fitness_score": round(score, 8),
        "metrics": all_metrics,
        "walk_forward": rolling,
        "robustness": robustness,
        "monte_carlo": monte_carlo,
        "execution_costs": execution_costs,
        "dataset_version": data["version"],
        "evidence": {
            "summary": summary,
            "dataset": data,
            "data_split": {
                "method": segments["method"],
                "years": segments.get("years") or [],
                "development_rows": len(segments["development"]),
                "validation_rows": len(segments["validation"]),
                "confirmation_rows": len(segments["confirmation"]),
                "holdout_rows": len(segments["holdout"]),
                "holdout_policy": "Selection and mutation never use confirmation or final holdout. Finalists open them once, after rules are fixed.",
            },
            "decision": {
                "stage": stage,
                "status": status,
                "gate_checks": gate_checks,
                "failed_gates": failed_gates,
                "plain_reason": "All gates for this stage passed." if not failed_gates else "Failed: " + ", ".join(failed_gates),
            },
            "execution_parity": {
                "position_model": "one position at a time",
                "entry_lock_minutes": max(
                    int(number(rules.get("risk", {}).get("cooldown_minutes"), 0)),
                    int(number(rules.get("risk", {}).get("max_hold_minutes"), rules.get("risk", {}).get("horizon_minutes") or 60)),
                ),
                "candle_body": "absolute close minus open, identical to generated EA",
                "ambiguous_bar": "stop first",
            },
            "caveats": [
                "Research-grade replay uses completed market-state outcomes; final M1 replay remains mandatory before package promotion.",
                "Same-horizon stop/target ambiguity is resolved conservatively as a stop.",
                "MetaEditor compilation and demo forward testing remain mandatory.",
            ],
        },
    }
    result["ready_for_final"] = selection_ready_for_final(result)
    return result


def compare_child_to_parent(
    child_result: dict[str, Any],
    parent_metrics_payload: dict[str, Any],
    parent_fitness: float,
) -> dict[str, Any]:
    """Select mutations using selection validation only; holdout cannot influence breeding."""
    child_fitness = number(child_result.get("fitness_score"))
    parent_validation = dict(parent_metrics_payload.get("validation") or {})
    child_validation = dict(child_result.get("metrics", {}).get("validation") or {})
    validation_delta = number(child_validation.get("expectancy_r")) - number(parent_validation.get("expectancy_r"))
    pf_delta = number(child_validation.get("profit_factor")) - number(parent_validation.get("profit_factor"))
    drawdown_delta = number(child_validation.get("max_drawdown_r")) - number(parent_validation.get("max_drawdown_r"))
    promoted = (
        child_result.get("research_stage") == "selection"
        and child_result.get("result_status") == "promising"
        and child_fitness > parent_fitness + 0.25
        and (validation_delta > 0.005 or pf_delta > 0.02)
        and drawdown_delta <= max(3.0, number(parent_validation.get("max_drawdown_r")) * 0.50)
    )
    reason = (
        f"Promoted using selection validation only: expectancy {validation_delta:+.3f}R, PF {pf_delta:+.2f}, drawdown {drawdown_delta:+.2f}R."
        if promoted
        else f"Rejected as champion using selection validation only: fitness {child_fitness-parent_fitness:+.2f}, expectancy {validation_delta:+.3f}R, PF {pf_delta:+.2f}."
    )
    return {
        **child_result,
        "promoted": promoted,
        "selection_reason": reason,
        "fitness_delta": round(child_fitness - parent_fitness, 8),
        "validation_expectancy_delta": round(validation_delta, 8),
        "validation_pf_delta": round(pf_delta, 8),
        "validation_drawdown_delta": round(drawdown_delta, 8),
        # Retained for v1 database compatibility; no holdout is opened here.
        "locked_veto": False,
        "holdout_used_for_selection": False,
    }
