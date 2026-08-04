from __future__ import annotations

import asyncio
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

from app.services.backtest import (
    as_utc,
    candidate_direction,
    chronological_segments,
    number,
    row_is_eligible,
)
from app.services.repository import SourceRepository

M1_REPLAY_VERSION = "eve-m1-replay-v2.0"


@dataclass(frozen=True)
class Intent:
    snapshot_time: datetime
    entry_time: datetime
    direction: int
    atr: float
    segment: str
    session: str
    regime: str


@dataclass(frozen=True)
class ReplayTrade:
    pnl_r: float
    exit_reason: str
    entry_time: datetime
    exit_time: datetime
    segment: str
    session: str
    regime: str


def timeframe_minutes(rules: dict[str, Any]) -> int:
    timeframe = str((rules.get("market") or {}).get("timeframe") or "M5").upper()
    mapping = {"M1": 1, "M5": 5, "M15": 15, "M30": 30, "H1": 60, "H4": 240}
    return mapping.get(timeframe, 5)


def build_intents(rows: list[dict[str, Any]], rules: dict[str, Any], segment: str) -> list[Intent]:
    """Build every eligible completed-candle signal without pre-skipping overlaps.

    The sequential replay applies the EA's actual one-position and cooldown rules
    after each M1-resolved exit. This avoids both overlapping positions and the
    overly coarse assumption that every trade remains open for its maximum hold.
    """
    source_minutes = timeframe_minutes(rules)
    result: list[Intent] = []
    for row in sorted(rows, key=lambda item: str(item.get("candle_time") or "")):
        snapshot = as_utc(row.get("candle_time"))
        if snapshot is None or not row_is_eligible(row, rules):
            continue
        direction = candidate_direction(row, rules)
        atr = number(row.get("atr_14"))
        if direction == 0 or atr <= 0:
            continue
        result.append(
            Intent(
                snapshot_time=snapshot,
                entry_time=snapshot + timedelta(minutes=source_minutes),
                direction=direction,
                atr=atr,
                segment=segment,
                session=str(row.get("session") or "unknown"),
                regime=str(row.get("regime") or "unknown"),
            )
        )
    return result


def replay_intent(
    intent: Intent,
    candles: list[dict[str, Any]],
    *,
    stop_atr: float,
    target_atr: float,
    hold_minutes: int,
    cost_r: float,
) -> ReplayTrade | None:
    parsed: list[tuple[datetime, dict[str, Any]]] = []
    for candle in candles:
        timestamp = as_utc(candle.get("candle_time"))
        if timestamp and timestamp >= intent.entry_time:
            parsed.append((timestamp, candle))
    parsed.sort(key=lambda item: item[0])
    if not parsed or parsed[0][0] > intent.entry_time + timedelta(minutes=2):
        return None

    entry_time, first = parsed[0]
    entry = number(first.get("open"))
    risk_price = max(1e-9, stop_atr * intent.atr)
    if entry <= 0:
        return None
    stop = entry - risk_price if intent.direction > 0 else entry + risk_price
    target = entry + target_atr * intent.atr if intent.direction > 0 else entry - target_atr * intent.atr
    end_time = entry_time + timedelta(minutes=max(1, hold_minutes))
    last_time = entry_time
    last_close = entry
    gross: float | None = None
    reason = "time_exit"

    for timestamp, candle in parsed:
        if timestamp >= end_time:
            break
        bar_open = number(candle.get("open"))
        high = number(candle.get("high"))
        low = number(candle.get("low"))
        close = number(candle.get("close"))
        last_time = timestamp
        last_close = close
        if intent.direction > 0:
            if bar_open <= stop:
                gross = (bar_open - entry) / risk_price
                reason = "gap_stop"
                break
            if bar_open >= target:
                gross = target_atr / stop_atr
                reason = "target"
                break
            hit_stop, hit_target = low <= stop, high >= target
        else:
            if bar_open >= stop:
                gross = (entry - bar_open) / risk_price
                reason = "gap_stop"
                break
            if bar_open <= target:
                gross = target_atr / stop_atr
                reason = "target"
                break
            hit_stop, hit_target = high >= stop, low <= target
        # A single M1 bar can still be ambiguous. Count the stop first.
        if hit_stop:
            gross = -1.0
            reason = "stop"
            break
        if hit_target:
            gross = target_atr / stop_atr
            reason = "target"
            break

    if gross is None:
        if last_time < end_time - timedelta(minutes=2):
            return None
        gross = intent.direction * (last_close - entry) / risk_price
        gross = max(-2.5, min(target_atr / stop_atr, gross))
        last_time = end_time
    return ReplayTrade(
        pnl_r=gross - max(0.0, cost_r),
        exit_reason=reason,
        entry_time=entry_time,
        exit_time=last_time,
        segment=intent.segment,
        session=intent.session,
        regime=intent.regime,
    )


def metrics(trades: list[ReplayTrade], unresolved: int) -> dict[str, Any]:
    pnls = [trade.pnl_r for trade in trades]
    wins = sum(value > 0 for value in pnls)
    gross_profit = sum(value for value in pnls if value > 0)
    gross_loss = abs(sum(value for value in pnls if value < 0))
    pf = gross_profit / gross_loss if gross_loss > 1e-12 else (99.0 if gross_profit > 0 else 0.0)
    equity = peak = drawdown = 0.0
    sessions: dict[str, list[float]] = defaultdict(list)
    regimes: dict[str, list[float]] = defaultdict(list)
    years: dict[str, list[float]] = defaultdict(list)
    for trade in trades:
        equity += trade.pnl_r
        peak = max(peak, equity)
        drawdown = max(drawdown, peak - equity)
        sessions[trade.session].append(trade.pnl_r)
        regimes[trade.regime].append(trade.pnl_r)
        years[str(trade.entry_time.year)].append(trade.pnl_r)
    yearly_expectancy = {key: sum(values) / len(values) for key, values in years.items() if values}
    positive_years = sum(value > 0 for value in yearly_expectancy.values())
    total = len(trades) + unresolved
    return {
        "trades": len(trades),
        "unresolved": unresolved,
        "resolved_rate": len(trades) / total if total else 0.0,
        "wins": int(wins),
        "win_rate": wins / len(trades) * 100.0 if trades else 0.0,
        "net_r": round(sum(pnls), 6),
        "expectancy_r": round(sum(pnls) / len(pnls), 6) if pnls else 0.0,
        "profit_factor": round(pf, 6),
        "max_drawdown_r": round(drawdown, 6),
        "year_stability": positive_years / len(yearly_expectancy) if yearly_expectancy else 0.0,
        "yearly_expectancy": {key: round(value, 6) for key, value in yearly_expectancy.items()},
        "session_expectancy": {key: round(sum(values) / len(values), 6) for key, values in sessions.items() if values},
        "regime_expectancy": {key: round(sum(values) / len(values), 6) for key, values in regimes.items() if values},
    }


def replay_sequence(
    items: list[Intent],
    day_data: dict[str, list[dict[str, Any]]],
    *,
    stop_atr: float,
    target_atr: float,
    hold_minutes: int,
    cooldown_minutes: int,
    cost_r: float,
) -> dict[str, Any]:
    """Replay signals in entry order with the generated EA's position rules."""
    trades: list[ReplayTrade] = []
    unresolved = 0
    skipped_while_busy = 0
    next_allowed: datetime | None = None
    for intent in sorted(items, key=lambda item: item.entry_time):
        if next_allowed and intent.entry_time < next_allowed:
            skipped_while_busy += 1
            continue
        trade = replay_intent(
            intent,
            day_data.get(intent.entry_time.date().isoformat(), []),
            stop_atr=stop_atr,
            target_atr=target_atr,
            hold_minutes=hold_minutes,
            cost_r=cost_r,
        )
        if trade is None:
            unresolved += 1
            continue
        trades.append(trade)
        next_allowed = max(
            trade.exit_time,
            trade.entry_time + timedelta(minutes=max(1, cooldown_minutes)),
        )
    result = metrics(trades, unresolved)
    result["eligible_signals"] = len(items)
    result["skipped_while_position_or_cooldown"] = skipped_while_busy
    result["position_model"] = "M1-resolved single position; cooldown measured from entry"
    return result


async def _fetch_days(source: SourceRepository, symbol: str, intents: list[Intent], hold_minutes: int) -> dict[str, list[dict[str, Any]]]:
    dates = sorted({intent.entry_time.date().isoformat() for intent in intents})
    result: dict[str, list[dict[str, Any]]] = {}
    semaphore = asyncio.Semaphore(3)

    async def fetch(date_text: str) -> None:
        async with semaphore:
            start = datetime.fromisoformat(date_text).replace(tzinfo=timezone.utc)
            end = start + timedelta(days=1, minutes=hold_minutes + 5)
            rows: list[dict[str, Any]] = []
            cursor: str | None = None
            while True:
                page = await source.fetch_candles_page(
                    symbol,
                    "1min",
                    after=cursor,
                    date_from=start.isoformat(),
                    date_to=end.isoformat(),
                    limit=1000,
                )
                if not page:
                    break
                rows.extend(page)
                if len(page) < 1000:
                    break
                cursor = str(page[-1].get("candle_time"))
            result[date_text] = rows

    for start in range(0, len(dates), 12):
        await asyncio.gather(*(fetch(value) for value in dates[start:start + 12]))
    return result


async def validate_with_m1(source: SourceRepository, candidate: dict[str, Any], rows: list[dict[str, Any]]) -> dict[str, Any]:
    rules = dict(candidate.get("rules") or {})
    risk = dict(rules.get("risk") or {})
    split = chronological_segments(rows)
    confirmation_intents = build_intents(split["confirmation"], rules, "confirmation")
    holdout_intents = build_intents(split["holdout"], rules, "holdout")
    intents = confirmation_intents + holdout_intents
    hold = max(1, int(number(risk.get("max_hold_minutes"), risk.get("horizon_minutes") or 60)))
    symbol = str((rules.get("market") or {}).get("symbol") or candidate.get("symbol") or "XAU/USD")
    day_data = await _fetch_days(source, symbol, intents, hold)
    stop = max(0.1, number(risk.get("stop_atr"), 1.0))
    target = max(0.1, number(risk.get("target_atr"), 2.0))
    base_cost = max(0.03, number(risk.get("cost_r"), 0.04))
    costs = {"standard": base_cost, "elevated": max(0.06, base_cost * 2), "severe": max(0.10, base_cost * 3)}

    cooldown = max(1, int(number(risk.get("cooldown_minutes"), hold)))

    def run(items: list[Intent], cost: float) -> dict[str, Any]:
        return replay_sequence(
            items,
            day_data,
            stop_atr=stop,
            target_atr=target,
            hold_minutes=hold,
            cooldown_minutes=cooldown,
            cost_r=cost,
        )

    standard_confirmation = run(confirmation_intents, costs["standard"])
    standard_holdout = run(holdout_intents, costs["standard"])
    elevated_holdout = run(holdout_intents, costs["elevated"])
    severe_holdout = run(holdout_intents, costs["severe"])
    gates = {
        "confirmation_sample": standard_confirmation["trades"] >= 35,
        "holdout_sample": standard_holdout["trades"] >= 25,
        "resolved_data": min(standard_confirmation["resolved_rate"], standard_holdout["resolved_rate"]) >= 0.98,
        "confirmation_edge": standard_confirmation["profit_factor"] >= 1.05 and standard_confirmation["expectancy_r"] > 0,
        "holdout_edge": standard_holdout["profit_factor"] >= 1.08 and standard_holdout["expectancy_r"] > 0,
        "elevated_cost_survival": elevated_holdout["expectancy_r"] > 0,
        "year_stability": min(standard_confirmation["year_stability"], standard_holdout["year_stability"]) >= 0.50,
    }
    passed = all(gates.values())
    return {
        "engine_version": M1_REPLAY_VERSION,
        "status": "passed" if passed else "failed",
        "passed": passed,
        "gates": gates,
        "failed_gates": [key for key, value in gates.items() if not value],
        "m1_days_scanned": len(day_data),
        "intents": len(intents),
        "cost_profiles": costs,
        "confirmation": standard_confirmation,
        "holdout": standard_holdout,
        "elevated_holdout": elevated_holdout,
        "severe_holdout": severe_holdout,
        "entry_protocol": f"Enter on the first M1 open after the completed {str((rules.get('market') or {}).get('timeframe') or 'M5')} source candle.",
        "position_protocol": "Replay resolves each exit on M1, permits only one position, and measures cooldown from entry exactly like the generated EA.",
        "ambiguity_protocol": "If one M1 candle reaches stop and target, count the stop first.",
    }
