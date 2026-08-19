from __future__ import annotations

import math
import statistics
from typing import Any, Iterable
from zoneinfo import ZoneInfo

from app.services.multitimeframe import FABRIC_VERSION, as_utc, number, safe_pct, sign

FEATURE_VERSION = "eve-discovery-m5-features-v1"
LOOKBACK_BARS = 288
MAX_FUTURE_BARS = 48
HORIZON_BARS = {5: 1, 15: 3, 30: 6, 60: 12, 240: 48}
LONDON_TZ = ZoneInfo("Europe/London")
NEW_YORK_TZ = ZoneInfo("America/New_York")


def mean(values: Iterable[float]) -> float:
    items = list(values)
    return statistics.fmean(items) if items else 0.0


def standard_deviation(values: Iterable[float]) -> float:
    items = list(values)
    return statistics.pstdev(items) if len(items) >= 2 else 0.0


def true_range(current: dict[str, Any], previous_close: float | None) -> float:
    high = number(current.get("high"))
    low = number(current.get("low"))
    if previous_close is None:
        return max(0.0, high - low)
    return max(high - low, abs(high - previous_close), abs(low - previous_close))


def linear_slope(values: list[float]) -> float:
    count = len(values)
    if count < 2:
        return 0.0
    x_mean = (count - 1) / 2.0
    y_mean = mean(values)
    numerator = sum((index - x_mean) * (value - y_mean) for index, value in enumerate(values))
    denominator = sum((index - x_mean) ** 2 for index in range(count))
    return numerator / denominator if denominator else 0.0


def candle_streak(history_and_current: list[dict[str, Any]], maximum: int = 12) -> int:
    streak = 0
    current_direction = 0
    for candle in reversed(history_and_current[-maximum:]):
        candle_direction = sign(number(candle.get("close")) - number(candle.get("open")))
        if candle_direction == 0:
            break
        if current_direction == 0:
            current_direction = candle_direction
        if candle_direction != current_direction:
            break
        streak += candle_direction
    return streak


def session_name(timestamp) -> str:
    london = timestamp.astimezone(LONDON_TZ)
    new_york = timestamp.astimezone(NEW_YORK_TZ)
    if 8 <= new_york.hour < 17:
        return "new_york"
    if 8 <= london.hour < 13:
        return "london"
    if 0 <= timestamp.hour < 7:
        return "asia"
    return "off_session"


def regime_name(atr: float, average_range_12: float, compression_ratio: float, trend_12_atr: float) -> str:
    if compression_ratio < 0.72:
        return "compression"
    if abs(trend_12_atr) >= 0.18:
        return "trend_up" if trend_12_atr > 0 else "trend_down"
    if average_range_12 > 0 and atr >= average_range_12 * 1.25:
        return "high_volatility"
    return "range"


def _outcome_for_horizon(
    current: dict[str, Any],
    future: list[dict[str, Any]],
    horizon_bars: int,
    atr: float,
) -> dict[str, Any] | None:
    if len(future) < horizon_bars:
        return None
    segment = future[:horizon_bars]
    close = number(current.get("close"))
    threshold = max(atr * 0.25, close * 0.00005, 1e-9)
    maximum_high = max(number(item.get("high")) for item in segment)
    minimum_low = min(number(item.get("low")) for item in segment)
    max_up = maximum_high - close
    max_down = close - minimum_low
    close_change = number(segment[-1].get("close")) - close

    first_side = "none"
    for candle in segment:
        hit_up = number(candle.get("high")) - close >= threshold
        hit_down = close - number(candle.get("low")) >= threshold
        if hit_up and hit_down:
            first_side = "ambiguous"
            break
        if hit_up:
            first_side = "up"
            break
        if hit_down:
            first_side = "down"
            break

    if close_change > threshold:
        outcome_direction = "up"
    elif close_change < -threshold:
        outcome_direction = "down"
    else:
        outcome_direction = "flat"

    current_direction = sign(number(current.get("close")) - number(current.get("open")))
    future_direction = sign(close_change, threshold)
    continuation = current_direction != 0 and future_direction == current_direction
    return {
        "close_return_pct": round(safe_pct(number(segment[-1].get("close")), close), 8),
        "max_up_price": round(max_up, 8),
        "max_down_price": round(max_down, 8),
        "max_up_atr": round(max_up / atr, 6) if atr > 0 else None,
        "max_down_atr": round(max_down / atr, 6) if atr > 0 else None,
        "direction": outcome_direction,
        "first_side": first_side,
        "continuation": continuation,
    }


def _context_return(fabric: dict[str, Any], label: str) -> float | None:
    item = fabric.get(label)
    if not isinstance(item, dict):
        return None
    value = item.get("return_pct")
    return None if value is None else number(value)


def build_m5_snapshot(
    symbol: str,
    previous: list[dict[str, Any]],
    current: dict[str, Any],
    future: list[dict[str, Any]],
    fabric: dict[str, Any],
) -> dict[str, Any]:
    """Rebuild the production feature definitions at every completed M5 candle.

    Forward candles are used only to create outcome labels. Every feature and
    multi-timeframe context value must already be present in `previous/current`
    or the causal fabric supplied for the M5 decision timestamp.
    """
    if len(previous) < LOOKBACK_BARS:
        raise ValueError(f"At least {LOOKBACK_BARS} prior M5 candles are required")
    timestamp = as_utc(current.get("candle_time"))
    if timestamp is None:
        raise ValueError("Current M5 candle has no candle_time")

    all_bars = previous + [current]
    open_price = number(current.get("open"))
    high = number(current.get("high"))
    low = number(current.get("low"))
    close = number(current.get("close"))
    current_range = max(0.0, high - low)
    body = close - open_price
    upper_wick = high - max(open_price, close)
    lower_wick = min(open_price, close) - low
    close_location = (close - low) / current_range if current_range > 0 else 0.5

    recent_14 = all_bars[-14:]
    true_ranges: list[float] = []
    for index, candle in enumerate(recent_14):
        previous_close = number(recent_14[index - 1].get("close")) if index > 0 else number(previous[-14].get("close"))
        true_ranges.append(true_range(candle, previous_close))
    atr_14 = mean(true_ranges)

    ranges_3 = [number(item.get("high")) - number(item.get("low")) for item in all_bars[-3:]]
    ranges_12 = [number(item.get("high")) - number(item.get("low")) for item in all_bars[-12:]]
    average_range_12 = mean(ranges_12)
    compression_ratio = mean(ranges_3) / average_range_12 if average_range_12 > 0 else 1.0

    closes_13 = [number(item.get("close")) for item in all_bars[-13:]]
    log_returns = [
        math.log(closes_13[index] / closes_13[index - 1])
        for index in range(1, len(closes_13))
        if closes_13[index - 1] > 0 and closes_13[index] > 0
    ]
    volatility_12 = standard_deviation(log_returns) * 100.0
    closes_12 = [number(item.get("close")) for item in all_bars[-12:]]
    closes_48 = [number(item.get("close")) for item in all_bars[-48:]]
    trend_12_atr = linear_slope(closes_12) / atr_14 if atr_14 > 0 else 0.0
    trend_48_atr = linear_slope(closes_48) / atr_14 if atr_14 > 0 else 0.0

    return_1 = safe_pct(close, number(previous[-1].get("close")))
    return_3 = safe_pct(close, number(previous[-3].get("close")))
    return_12 = safe_pct(close, number(previous[-12].get("close")))
    return_48 = safe_pct(close, number(previous[-48].get("close")))
    return_288 = safe_pct(close, number(previous[-288].get("close")))

    context_m15 = _context_return(fabric, "M15")
    context_m30 = _context_return(fabric, "M30")
    context_h1 = _context_return(fabric, "H1")
    context_h4 = _context_return(fabric, "H4")
    context_d1 = _context_return(fabric, "D1")
    # Preserve the production alignment definition (M15/H1/H4/D1) for old
    # strategies. M30 and M1 live in mtf_context for the richer scientist.
    production_context = [value for value in (context_m15, context_h1, context_h4, context_d1) if value is not None]
    alignment_source = production_context if production_context else [return_3, return_12, return_48, return_288]
    alignment = sum(sign(value) for value in alignment_source)
    regime = regime_name(atr_14, average_range_12, compression_ratio, trend_12_atr)

    outcomes: dict[str, Any] = {}
    horizons: list[int] = []
    for horizon_minutes, horizon_bars in HORIZON_BARS.items():
        result = _outcome_for_horizon(current, future, horizon_bars, atr_14)
        if result is not None:
            outcomes[str(horizon_minutes)] = result
            horizons.append(horizon_minutes)

    return {
        "symbol": symbol,
        "snapshot_interval": "5min",
        "source_interval": "5min",
        "candle_time": timestamp.isoformat(),
        "open": open_price,
        "high": high,
        "low": low,
        "close": close,
        "volume": None if current.get("volume") is None else number(current.get("volume")),
        "weekday": timestamp.isoweekday(),
        "month": timestamp.month,
        "quarter": ((timestamp.month - 1) // 3) + 1,
        "hour_utc": timestamp.hour,
        "week_of_month": ((timestamp.day - 1) // 7) + 1,
        "session": session_name(timestamp),
        "direction": sign(body),
        "range_price": current_range,
        "body_price": body,
        "upper_wick": max(0.0, upper_wick),
        "lower_wick": max(0.0, lower_wick),
        "close_location": close_location,
        "atr_14": atr_14,
        "average_range_12": average_range_12,
        "volatility_12": volatility_12,
        "compression_ratio": compression_ratio,
        "return_1_pct": return_1,
        "return_3_pct": return_3,
        "return_12_pct": return_12,
        "return_48_pct": return_48,
        "return_288_pct": return_288,
        "context_m15_return_pct": context_m15,
        "context_m30_return_pct": context_m30,
        "context_h1_return_pct": context_h1,
        "context_h4_return_pct": context_h4,
        "context_d1_return_pct": context_d1,
        "trend_12_atr": trend_12_atr,
        "trend_48_atr": trend_48_atr,
        "streak": candle_streak(all_bars),
        "regime": regime,
        "alignment_score": alignment,
        "outcomes": outcomes,
        "outcome_horizons": horizons,
        "outcome_complete": len(horizons) == len(HORIZON_BARS),
        "feature_version": FEATURE_VERSION,
        "mtf_context": fabric,
        "fabric_version": FABRIC_VERSION,
    }
