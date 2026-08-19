from __future__ import annotations

import math
from bisect import bisect_right
from datetime import datetime, timedelta, timezone
from typing import Any, Iterable

FABRIC_VERSION = "eve-multitimeframe-fabric-v1"
INTERVAL_MINUTES = {
    "1min": 1,
    "5min": 5,
    "15min": 15,
    "30min": 30,
    "1h": 60,
    "4h": 240,
    "1day": 1440,
}
CANONICAL_TIMEFRAMES = {
    "M1": "1min",
    "M5": "5min",
    "M15": "15min",
    "M30": "30min",
    "H1": "1h",
    "H4": "4h",
    "D1": "1day",
}


def as_utc(value: str | datetime | None) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        parsed = value
    else:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def number(value: Any, default: float = 0.0) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return default
    return result if math.isfinite(result) else default


def sign(value: Any, tolerance: float = 1e-12) -> int:
    amount = number(value)
    if amount > tolerance:
        return 1
    if amount < -tolerance:
        return -1
    return 0


def safe_pct(current: float, previous: float) -> float:
    return ((current / previous) - 1.0) * 100.0 if previous else 0.0


def candle_start(row: dict[str, Any]) -> datetime | None:
    return as_utc(row.get("candle_time"))


def candle_completed_at(row: dict[str, Any], interval: str) -> datetime | None:
    start = candle_start(row)
    minutes = INTERVAL_MINUTES.get(interval)
    if start is None or minutes is None:
        return None
    return start + timedelta(minutes=minutes)


def _normalise_candle(row: dict[str, Any]) -> dict[str, Any]:
    start = candle_start(row)
    if start is None:
        raise ValueError("Candle has no candle_time")
    return {
        "candle_time": start.isoformat(),
        "open": number(row.get("open")),
        "high": number(row.get("high")),
        "low": number(row.get("low")),
        "close": number(row.get("close")),
        "volume": None if row.get("volume") is None else number(row.get("volume")),
    }


def candle_features(row: dict[str, Any], interval: str) -> dict[str, Any]:
    candle = _normalise_candle(row)
    start = as_utc(candle["candle_time"])
    assert start is not None
    completed = start + timedelta(minutes=INTERVAL_MINUTES[interval])
    range_price = max(0.0, candle["high"] - candle["low"])
    body = candle["close"] - candle["open"]
    close_location = (candle["close"] - candle["low"]) / range_price if range_price > 0 else 0.5
    return {
        "interval": interval,
        "candle_time": candle["candle_time"],
        "completed_at": completed.isoformat(),
        "open": candle["open"],
        "high": candle["high"],
        "low": candle["low"],
        "close": candle["close"],
        "range_price": range_price,
        "body_price": body,
        "body_abs": abs(body),
        "direction": sign(body),
        "return_pct": safe_pct(candle["close"], candle["open"]),
        "close_location": close_location,
        "upper_wick": max(0.0, candle["high"] - max(candle["open"], candle["close"])),
        "lower_wick": max(0.0, min(candle["open"], candle["close"]) - candle["low"]),
    }


def aggregate_m30(m5_rows: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    """Construct exact UTC M30 candles from six consecutive M5 candles."""
    ordered = sorted((_normalise_candle(row) for row in m5_rows), key=lambda row: row["candle_time"])
    buckets: dict[datetime, list[dict[str, Any]]] = {}
    for row in ordered:
        start = as_utc(row["candle_time"])
        assert start is not None
        bucket = start.replace(minute=0 if start.minute < 30 else 30, second=0, microsecond=0)
        buckets.setdefault(bucket, []).append(row)

    result: list[dict[str, Any]] = []
    for bucket, rows in sorted(buckets.items()):
        rows = sorted(rows, key=lambda row: row["candle_time"])
        expected = [bucket + timedelta(minutes=5 * index) for index in range(6)]
        actual = [as_utc(row["candle_time"]) for row in rows]
        if len(rows) != 6 or actual != expected:
            continue
        result.append(
            {
                "candle_time": bucket.isoformat(),
                "open": rows[0]["open"],
                "high": max(row["high"] for row in rows),
                "low": min(row["low"] for row in rows),
                "close": rows[-1]["close"],
                "volume": sum(number(row.get("volume")) for row in rows) if any(row.get("volume") is not None for row in rows) else None,
            }
        )
    return result


class CompletedCandleIndex:
    """Lookup the latest candle that was fully known at a decision timestamp."""

    def __init__(self, rows: Iterable[dict[str, Any]], interval: str) -> None:
        if interval not in INTERVAL_MINUTES:
            raise ValueError(f"Unsupported interval: {interval}")
        self.interval = interval
        ordered = sorted((_normalise_candle(row) for row in rows), key=lambda row: row["candle_time"])
        self.rows = ordered
        self.completed_times = [
            as_utc(row["candle_time"]) + timedelta(minutes=INTERVAL_MINUTES[interval])  # type: ignore[operator]
            for row in ordered
        ]

    def at(self, decision_time: datetime) -> dict[str, Any] | None:
        decision_time = decision_time.astimezone(timezone.utc)
        index = bisect_right(self.completed_times, decision_time) - 1
        return self.rows[index] if index >= 0 else None


def m1_microstructure(signal_m5: dict[str, Any], m1_rows: Iterable[dict[str, Any]]) -> dict[str, Any]:
    """Describe the five completed M1 bars inside one completed M5 signal candle."""
    start = candle_start(signal_m5)
    if start is None:
        return {"available": False, "reason": "missing_signal_time"}
    end = start + timedelta(minutes=5)
    bars = []
    for row in m1_rows:
        stamp = candle_start(row)
        if stamp is not None and start <= stamp < end:
            bars.append(_normalise_candle(row))
    bars.sort(key=lambda row: row["candle_time"])
    expected = [start + timedelta(minutes=index) for index in range(5)]
    actual = [as_utc(row["candle_time"]) for row in bars]
    if len(bars) != 5 or actual != expected:
        return {"available": False, "bars": len(bars), "reason": "incomplete_m1_path"}

    directions = [sign(row["close"] - row["open"]) for row in bars]
    direction_changes = sum(
        1 for left, right in zip(directions, directions[1:]) if left != 0 and right != 0 and left != right
    )
    path = sum(abs(bars[index]["close"] - bars[index - 1]["close"]) for index in range(1, len(bars)))
    path += abs(bars[0]["close"] - bars[0]["open"])
    net = abs(bars[-1]["close"] - bars[0]["open"])
    signed_sum = sum(directions)
    return {
        "available": True,
        "bars": 5,
        "direction": sign(bars[-1]["close"] - bars[0]["open"]),
        "bullish_minutes": sum(1 for value in directions if value > 0),
        "bearish_minutes": sum(1 for value in directions if value < 0),
        "neutral_minutes": sum(1 for value in directions if value == 0),
        "direction_changes": direction_changes,
        "direction_score": signed_sum,
        "path_efficiency": net / path if path > 0 else 0.0,
        "first_minute_direction": directions[0],
        "last_minute_direction": directions[-1],
        "first_minute_return_pct": safe_pct(bars[0]["close"], bars[0]["open"]),
        "last_minute_return_pct": safe_pct(bars[-1]["close"], bars[-1]["open"]),
        "high": max(row["high"] for row in bars),
        "low": min(row["low"] for row in bars),
    }


def build_fabric_context(
    signal_m5: dict[str, Any],
    *,
    m1_rows: Iterable[dict[str, Any]] = (),
    m15_index: CompletedCandleIndex | None = None,
    m30_index: CompletedCandleIndex | None = None,
    h1_index: CompletedCandleIndex | None = None,
    h4_index: CompletedCandleIndex | None = None,
    d1_index: CompletedCandleIndex | None = None,
) -> dict[str, Any]:
    """Build the auditable market state available immediately after an M5 close."""
    signal_start = candle_start(signal_m5)
    if signal_start is None:
        raise ValueError("Signal M5 candle has no candle_time")
    decision_time = signal_start + timedelta(minutes=5)

    def completed(index: CompletedCandleIndex | None) -> dict[str, Any] | None:
        if index is None:
            return None
        row = index.at(decision_time)
        return candle_features(row, index.interval) if row else None

    m5 = candle_features(signal_m5, "5min")
    payload = {
        "fabric_version": FABRIC_VERSION,
        "signal_time": signal_start.isoformat(),
        "decision_time": decision_time.isoformat(),
        "M1": m1_microstructure(signal_m5, m1_rows),
        "M5": m5,
        "M15": completed(m15_index),
        "M30": completed(m30_index),
        "H1": completed(h1_index),
        "H4": completed(h4_index),
        "D1": completed(d1_index),
    }

    direction_values = [
        number((payload.get(label) or {}).get("direction"))
        for label in ("M5", "M15", "M30", "H1", "H4", "D1")
        if payload.get(label)
    ]
    payload["direction_alignment_score"] = int(sum(sign(value) for value in direction_values))
    payload["higher_timeframe_alignment_score"] = int(
        sum(sign(number((payload.get(label) or {}).get("direction"))) for label in ("M15", "M30", "H1", "H4", "D1") if payload.get(label))
    )
    payload["context_complete"] = all(payload.get(label) is not None for label in ("M5", "M15", "M30", "H1", "H4", "D1"))
    return payload
