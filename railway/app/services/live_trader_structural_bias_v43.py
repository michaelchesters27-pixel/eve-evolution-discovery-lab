from __future__ import annotations

import math
from datetime import datetime, timedelta, timezone
from typing import Any

from app.services import live_trader as core
from app.services import live_trader_intelligence_v24 as v24
from app.services import live_trader_learning_v2 as v2

BIAS_VERSION = "eve-live-bias-v2.5-structural-panel"

TIMEFRAME_MINUTES = {
    "M5": 5,
    "M15": 15,
    "M30": 30,
    "H1": 60,
    "H4": 240,
    "D1": 1440,
}
CRITICAL_TIMEFRAMES = ("D1", "H4", "H1", "M30", "M15")
MAX_STRUCTURE_BARS = 8
MIN_STRUCTURE_BARS = 3

_original_bias = v2.LiveTrader._bias
_original_runtime_status = v2.LiveTrader.runtime_status


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


def _num(value: Any, default: float = 0.0) -> float:
    return core.number(value, default)


def _sign(value: float, tolerance: float = 1e-9) -> int:
    if value > tolerance:
        return 1
    if value < -tolerance:
        return -1
    return 0


def _latest_decision_time(latest: dict[str, Any]) -> datetime | None:
    context = dict(latest.get("mtf_context") or {})
    decision = _parse_time(context.get("decision_time"))
    if decision is not None:
        return decision
    start = _parse_time(latest.get("candle_time"))
    return start + timedelta(minutes=5) if start is not None else None


def _history_for_timeframe(self: v2.LiveTrader, latest: dict[str, Any], timeframe: str) -> list[dict[str, Any]]:
    by_time: dict[str, dict[str, Any]] = {}
    source_rows = list(getattr(self, "_rows", None) or [])
    if not source_rows:
        source_rows = [latest]
    elif source_rows[-1] is not latest:
        source_rows.append(latest)

    for row in source_rows:
        context = dict(row.get("mtf_context") or {})
        item = dict(context.get(timeframe) or {})
        stamp = str(item.get("candle_time") or "")
        if not stamp:
            continue
        by_time[stamp] = item

    ordered = sorted(
        by_time.values(),
        key=lambda item: _parse_time(item.get("completed_at")) or _parse_time(item.get("candle_time")) or datetime.min.replace(tzinfo=timezone.utc),
    )
    return ordered[-MAX_STRUCTURE_BARS:]


def _m5_times(self: v2.LiveTrader, latest: dict[str, Any]) -> set[datetime]:
    result: set[datetime] = set()
    source_rows = list(getattr(self, "_rows", None) or [])
    if not source_rows:
        source_rows = [latest]
    elif source_rows[-1] is not latest:
        source_rows.append(latest)
    for row in source_rows:
        stamp = _parse_time(row.get("candle_time"))
        if stamp is not None:
            result.add(stamp)
    return result


def _provably_stale(
    self: v2.LiveTrader,
    latest: dict[str, Any],
    timeframe: str,
    item: dict[str, Any],
) -> bool:
    """Return True only when M5 evidence proves a newer HTF candle should exist.

    Wall-clock age alone is unsafe around weekends/maintenance. Instead, if every
    completed M5 bar needed to construct the *next* timeframe candle is present,
    but the stored timeframe context has not advanced, the context is stale.
    """
    minutes = TIMEFRAME_MINUTES.get(timeframe)
    if not minutes:
        return False
    completed_at = _parse_time(item.get("completed_at"))
    decision_time = _latest_decision_time(latest)
    if completed_at is None or decision_time is None:
        return False

    next_completed_at = completed_at + timedelta(minutes=minutes)
    if decision_time < next_completed_at:
        return False

    expected = [completed_at + timedelta(minutes=5 * index) for index in range(minutes // 5)]
    available = _m5_times(self, latest)
    return bool(expected) and all(stamp in available for stamp in expected)


def _structure_score(bars: list[dict[str, Any]]) -> float:
    if len(bars) < MIN_STRUCTURE_BARS:
        return 0.0

    recent = bars[-MAX_STRUCTURE_BARS:]
    pair_scores: list[float] = []
    for left, right in zip(recent, recent[1:]):
        high_vote = _sign(_num(right.get("high")) - _num(left.get("high")))
        low_vote = _sign(_num(right.get("low")) - _num(left.get("low")))
        pair_scores.append((high_vote + low_vote) / 2.0)
    structure = sum(pair_scores) / len(pair_scores) if pair_scores else 0.0

    ranges = [max(_num(bar.get("high")) - _num(bar.get("low")), 0.0) for bar in recent]
    average_range = sum(ranges) / len(ranges) if ranges else 0.0
    first_close = _num(recent[0].get("close"))
    last_close = _num(recent[-1].get("close"))
    if average_range > 0:
        close_trend = math.tanh(((last_close - first_close) / average_range) / 1.5)
    else:
        close_trend = 0.0

    latest_conviction = v24._candle_conviction(recent[-1])
    return core.clamp(structure * 0.55 + close_trend * 0.30 + latest_conviction * 0.15, -1.0, 1.0)


def _structure_direction(score: float) -> str:
    if score >= 0.16:
        return "bullish"
    if score <= -0.16:
        return "bearish"
    return "neutral"


def _bias_v43(self: v2.LiveTrader, latest: dict[str, Any]) -> tuple[dict[str, Any], float]:
    # Preserve the validated v2.4 weighted decision score. v43 upgrades the panel
    # semantics and adds a fail-closed stale-data veto without silently changing
    # the historical learning namespace or reinterpreting the six-year ledger.
    bias, score = _original_bias(self, latest)
    bias = dict(bias)
    legacy_timeframes = dict(bias.get("timeframes") or {})
    context = dict(latest.get("mtf_context") or {})
    timeframes: dict[str, Any] = {}
    stale_timeframes: list[str] = []

    for timeframe in ("D1", "H4", "H1", "M30", "M15", "M5"):
        item = dict(context.get(timeframe) or {})
        legacy = dict(legacy_timeframes.get(timeframe) or {})
        history = _history_for_timeframe(self, latest, timeframe)
        stale = bool(item) and _provably_stale(self, latest, timeframe, item)

        if not item:
            direction = "unknown"
            structure_score = 0.0
            method = "missing"
        elif stale:
            direction = "unknown"
            structure_score = 0.0
            method = "stale"
            stale_timeframes.append(timeframe)
        elif len(history) < MIN_STRUCTURE_BARS:
            direction = "unknown"
            structure_score = 0.0
            method = "insufficient_history"
        else:
            structure_score = _structure_score(history)
            direction = _structure_direction(structure_score)
            method = "multi_candle_structure"

        timeframes[timeframe] = {
            **legacy,
            "direction": direction,
            "legacy_direction": legacy.get("direction"),
            "structure_score": round(structure_score, 3),
            "bars_used": len(history),
            "method": method,
            "stale": stale,
            "completed_at": item.get("completed_at"),
        }

    # M1 remains execution/microstructure diagnostics only and never gains a vote.
    m1 = dict(context.get("M1") or {})
    m1_legacy = dict(legacy_timeframes.get("M1") or {})
    timeframes["M1"] = {
        **m1_legacy,
        "direction": core.direction_label(_num(m1.get("direction"))) if m1.get("available", True) else "unknown",
        "weight": 0,
        "method": "microstructure_diagnostic",
        "stale": False,
    }

    bias["timeframes"] = timeframes
    bias["panel_bias_version"] = BIAS_VERSION
    bias["data_quality"] = {
        "stale_timeframes": stale_timeframes,
        "critical_stale": [timeframe for timeframe in stale_timeframes if timeframe in CRITICAL_TIMEFRAMES],
        "decision_score_source": "eve-live-bias-v2",
        "panel_direction_source": "multi_candle_closed_structure",
    }

    # A proven stale critical timeframe is a data-quality failure, not a trading
    # opinion. Fail closed rather than recycling an old H4/H1/etc. vote.
    if bias["data_quality"]["critical_stale"]:
        bias["overall"] = "neutral"
        bias["raw_score"] = 0.0
        bias["confidence"] = min(int(_num(bias.get("confidence"), 40)), 50)
        bias["data_quality"]["trade_bias_blocked"] = True
        score = 0.0
    else:
        bias["data_quality"]["trade_bias_blocked"] = False

    return bias, score


def _runtime_status_v43(self: v2.LiveTrader) -> dict[str, Any]:
    state = dict(_original_runtime_status(self))
    state.update(
        {
            "panel_bias_version": BIAS_VERSION,
            "timeframe_panel_uses_multi_candle_structure": True,
            "timeframe_stale_data_fails_closed": True,
            "bias_uses_m1": False,
        }
    )
    return state


v2.LiveTrader._bias = _bias_v43  # type: ignore[method-assign]
v2.LiveTrader.runtime_status = _runtime_status_v43  # type: ignore[method-assign]
