from __future__ import annotations

from typing import Any

from app.services import live_trader as core

MTF_ZONE_VERSION = "eve-live-mtf-zones-v63"
_BASE_ZONE_CANDIDATES = core.LiveTrader._zone_candidates


def _num(value: Any, default: float = 0.0) -> float:
    return core.number(value, default)


def _unique_tf_bars(rows: list[dict[str, Any]], timeframe: str) -> list[dict[str, Any]]:
    by_time: dict[str, dict[str, Any]] = {}
    for row in rows:
        item = dict((row.get("mtf_context") or {}).get(timeframe) or {})
        stamp = str(item.get("candle_time") or "")
        if not stamp or item.get("completed_at") is None:
            continue
        if not all(_num(item.get(key)) > 0 for key in ("open", "high", "low", "close")):
            continue
        by_time[stamp] = item
    return [by_time[key] for key in sorted(by_time)]


def _average_range(bars: list[dict[str, Any]]) -> float:
    recent = bars[-14:]
    ranges = [max(_num(bar.get("high")) - _num(bar.get("low")), 0.0) for bar in recent]
    useful = [value for value in ranges if value > 0]
    return sum(useful) / len(useful) if useful else 0.01


def _native_zones(rows: list[dict[str, Any]], timeframe: str, price: float) -> dict[str, list[dict[str, Any]]]:
    bars = _unique_tf_bars(rows, timeframe)
    if len(bars) < 10:
        return {"demand": [], "supply": []}

    atr = max(_average_range(bars), 0.01)
    window = 2
    demand: list[dict[str, Any]] = []
    supply: list[dict[str, Any]] = []

    for index in range(window, len(bars) - 3):
        row = bars[index]
        nearby = bars[index - window:index + window + 1]
        future = bars[index + 1:index + 4]
        later = bars[index + 4:]
        low = _num(row.get("low"))
        high = _num(row.get("high"))
        open_ = _num(row.get("open"))
        close = _num(row.get("close"))

        if low <= min(_num(item.get("low")) for item in nearby):
            future_high = max(_num(item.get("high")) for item in future)
            departure = (future_high - low) / atr
            if departure >= 0.9:
                zone_low = low
                zone_high = min(max(open_, close), low + atr * 0.45)
                invalid = any(_num(item.get("close")) < zone_low - atr * 0.12 for item in later)
                if not invalid and zone_high >= zone_low:
                    retests = sum(1 for item in later if _num(item.get("low")) <= zone_high and _num(item.get("high")) >= zone_low)
                    quality = min(99.0, 52.0 + min(departure, 3.0) * 12.0 + (10.0 if retests == 0 else 0.0) - min(retests, 3) * 7.0)
                    demand.append(_zone_payload("demand", timeframe, row, zone_low, zone_high, quality, retests, departure, price, atr))

        if high >= max(_num(item.get("high")) for item in nearby):
            future_low = min(_num(item.get("low")) for item in future)
            departure = (high - future_low) / atr
            if departure >= 0.9:
                zone_high = high
                zone_low = max(min(open_, close), high - atr * 0.45)
                invalid = any(_num(item.get("close")) > zone_high + atr * 0.12 for item in later)
                if not invalid and zone_high >= zone_low:
                    retests = sum(1 for item in later if _num(item.get("low")) <= zone_high and _num(item.get("high")) >= zone_low)
                    quality = min(99.0, 52.0 + min(departure, 3.0) * 12.0 + (10.0 if retests == 0 else 0.0) - min(retests, 3) * 7.0)
                    supply.append(_zone_payload("supply", timeframe, row, zone_low, zone_high, quality, retests, departure, price, atr))

    def rank(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
        items.sort(key=lambda z: (-_num(z.get("quality")), int(z.get("retests") or 0), _num(z.get("distance_atr"))))
        return items[:5]

    return {"demand": rank(demand), "supply": rank(supply)}


def _zone_payload(kind: str, timeframe: str, row: dict[str, Any], low: float, high: float, quality: float, retests: int, departure: float, price: float, atr: float) -> dict[str, Any]:
    distance = 0.0 if low <= price <= high else min(abs(price - low), abs(price - high))
    return {
        "kind": kind,
        "timeframe": timeframe,
        "low": round(low, 3),
        "high": round(high, 3),
        "mid": round((low + high) / 2.0, 3),
        "quality": int(round(quality)),
        "fresh": retests == 0,
        "retests": int(retests),
        "departure_atr": round(departure, 2),
        "distance_atr": round(distance / max(atr, 0.01), 2),
        "origin_time": row.get("candle_time"),
        "completed_at": row.get("completed_at"),
    }


def _overlaps(a: dict[str, Any], b: dict[str, Any], tolerance: float = 0.0) -> bool:
    return _num(a.get("low")) <= _num(b.get("high")) + tolerance and _num(a.get("high")) >= _num(b.get("low")) - tolerance


def _confluence(zone: dict[str, Any], h1: list[dict[str, Any]], m15: list[dict[str, Any]], atr: float) -> dict[str, Any]:
    h1_hits = [item for item in h1 if _overlaps(zone, item, atr * 0.20)]
    m15_hits = [item for item in m15 if _overlaps(zone, item, atr * 0.12)]
    h1_best = h1_hits[0] if h1_hits else None
    m15_best = m15_hits[0] if m15_hits else None

    boost = 0.0
    if h1_best:
        boost += 12.0 + max(0.0, (_num(h1_best.get("quality")) - 60.0) * 0.08)
    if m15_best:
        boost += 7.0 + max(0.0, (_num(m15_best.get("quality")) - 60.0) * 0.05)
    if h1_best and m15_best:
        boost += 5.0

    result = dict(zone)
    result["mtf_zone_version"] = MTF_ZONE_VERSION
    result["h1_confluence"] = bool(h1_best)
    result["m15_confluence"] = bool(m15_best)
    result["mtf_confluence_count"] = int(bool(h1_best)) + int(bool(m15_best))
    result["h1_zone"] = h1_best
    result["m15_zone"] = m15_best
    result["mtf_rank_boost"] = round(boost, 2)
    result["rank_score"] = round(_num(result.get("rank_score"), _num(result.get("quality"))) + boost, 2)
    if h1_best and m15_best:
        result["zone_role"] = "H1_ZONE_M15_REFINEMENT_M5_EXECUTION"
    elif h1_best:
        result["zone_role"] = "H1_BACKED_M5_EXECUTION"
    elif m15_best:
        result["zone_role"] = "M15_BACKED_M5_EXECUTION"
    else:
        result["zone_role"] = "M5_ONLY"
    return result


def _zone_candidates_v63(self: core.LiveTrader, rows: list[dict[str, Any]], price: float, bias: dict[str, Any]) -> dict[str, list[dict[str, Any]]]:
    base = _BASE_ZONE_CANDIDATES(self, rows, price, bias)
    atr = max(_num((rows[-1] if rows else {}).get("atr_14")), 0.01)
    h1 = _native_zones(rows[-720:], "H1", price)
    m15 = _native_zones(rows[-720:], "M15", price)

    result: dict[str, list[dict[str, Any]]] = {"demand": [], "supply": []}
    for kind in ("demand", "supply"):
        annotated = [_confluence(zone, h1[kind], m15[kind], atr) for zone in list(base.get(kind) or [])]
        annotated.sort(key=lambda z: (-_num(z.get("rank_score")), -int(z.get("mtf_confluence_count") or 0), -_num(z.get("quality")), _num(z.get("distance_atr"))))
        for index, zone in enumerate(annotated, start=1):
            zone["rank"] = index
            zone["preferred"] = index == 1
        result[kind] = annotated

    self._mtf_zone_map_v63 = {
        "version": MTF_ZONE_VERSION,
        "H1": h1,
        "M15": m15,
        "policy": "H1 zone -> M15 refinement -> M5 execution; M5-only zones remain visible but receive no higher-timeframe confluence boost.",
    }
    return result


core.LiveTrader._zone_candidates = _zone_candidates_v63  # type: ignore[method-assign]
