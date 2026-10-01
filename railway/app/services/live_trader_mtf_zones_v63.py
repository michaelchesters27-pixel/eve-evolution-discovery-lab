from __future__ import annotations

from typing import Any

from app.services import live_trader as core

MTF_ZONE_VERSION = "eve-live-mtf-zones-v63"
MIN_NATIVE_QUALITY = 58
MAX_NATIVE_RETESTS = 2
FINAL_ZONE_COUNT = 4
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
        # HTF confluence is only allowed to strengthen a genuinely clean native
        # zone. Weak/overused HTF areas remain historical context, not a ranking boost.
        eligible = [
            item for item in items
            if _num(item.get("quality")) >= MIN_NATIVE_QUALITY
            and int(item.get("retests") or 0) <= MAX_NATIVE_RETESTS
        ]
        eligible.sort(key=lambda z: (-_num(z.get("quality")), int(z.get("retests") or 0), _num(z.get("distance_atr"))))
        return eligible[:5]

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


def _stable_chart_zone_pool(
    self: core.LiveTrader,
    rows: list[dict[str, Any]],
    price: float,
    bias: dict[str, Any],
) -> dict[str, list[dict[str, Any]]]:
    """Build chart zones from immutable origin-bar ATR, never current ATR.

    Trade-facing zones keep their existing policy.  The public chart map needs
    stable identity/geometry so an old mapped zone cannot disappear and return
    merely because current volatility changes.
    """
    source = list(rows[-360:])
    if len(source) < 20:
        return {"demand": [], "supply": []}

    latest_atr = _num(source[-1].get("atr_14"))
    if latest_atr <= 0:
        return {"demand": [], "supply": []}

    htf = dict((bias or {}).get("timeframes") or {})
    demand: list[dict[str, Any]] = []
    supply: list[dict[str, Any]] = []
    window = 2

    for index in range(window, len(source) - 8):
        row = source[index]
        origin_atr = _num(row.get("atr_14"))
        if origin_atr <= 0:
            continue
        low = _num(row.get("low"))
        high = _num(row.get("high"))
        open_ = _num(row.get("open"))
        close = _num(row.get("close"))
        if min(low, high, open_, close) <= 0 or high < low:
            continue

        nearby = source[index - window:index + window + 1]
        future = source[index + 1:index + 9]
        prior = source[max(0, index - 12):index]
        later = source[index + 9:]

        is_low = low <= min(_num(item.get("low")) for item in nearby)
        is_high = high >= max(_num(item.get("high")) for item in nearby)

        if is_low and future:
            future_high = max(_num(item.get("high")) for item in future)
            departure = (future_high - low) / origin_atr
            if departure >= 1.15:
                zone_low = low
                zone_high = min(max(open_, close), low + origin_atr * 0.55)
                if zone_high >= zone_low:
                    retests = sum(
                        1 for item in later
                        if _num(item.get("low")) <= zone_high and _num(item.get("high")) >= zone_low
                    )
                    broke_structure = bool(prior) and future_high > max(_num(item.get("high")) for item in prior)
                    alignment = sum(
                        1 for tf in ("D1", "H4", "H1")
                        if str((htf.get(tf) or {}).get("direction") or "") == "bullish"
                    )
                    quality = core.clamp(
                        38 + min(departure, 3.5) * 11 + (18 if broke_structure else 0)
                        + alignment * 4 - min(retests, 4) * 7,
                        1,
                        99,
                    )
                    zone = self._zone(
                        "demand", row, zone_low, zone_high, quality, retests,
                        departure, price, latest_atr,
                    )
                    zone.update({
                        "geometry_version": "eve-chart-zone-origin-atr-v1",
                        "origin_atr_14": round(origin_atr, 6),
                        "formation_end_time": future[-1].get("candle_time"),
                        "departure_extreme": round(future_high, 6),
                        "broke_prior_structure": bool(broke_structure),
                        "htf_alignment_count_at_refresh": int(alignment),
                        "retest_metric": "overlapping_m5_bars",
                    })
                    demand.append(zone)

        if is_high and future:
            future_low = min(_num(item.get("low")) for item in future)
            departure = (high - future_low) / origin_atr
            if departure >= 1.15:
                zone_high = high
                zone_low = max(min(open_, close), high - origin_atr * 0.55)
                if zone_high >= zone_low:
                    retests = sum(
                        1 for item in later
                        if _num(item.get("low")) <= zone_high and _num(item.get("high")) >= zone_low
                    )
                    broke_structure = bool(prior) and future_low < min(_num(item.get("low")) for item in prior)
                    alignment = sum(
                        1 for tf in ("D1", "H4", "H1")
                        if str((htf.get(tf) or {}).get("direction") or "") == "bearish"
                    )
                    quality = core.clamp(
                        38 + min(departure, 3.5) * 11 + (18 if broke_structure else 0)
                        + alignment * 4 - min(retests, 4) * 7,
                        1,
                        99,
                    )
                    zone = self._zone(
                        "supply", row, zone_low, zone_high, quality, retests,
                        departure, price, latest_atr,
                    )
                    zone.update({
                        "geometry_version": "eve-chart-zone-origin-atr-v1",
                        "origin_atr_14": round(origin_atr, 6),
                        "formation_end_time": future[-1].get("candle_time"),
                        "departure_extreme": round(future_low, 6),
                        "broke_prior_structure": bool(broke_structure),
                        "htf_alignment_count_at_refresh": int(alignment),
                        "retest_metric": "overlapping_m5_bars",
                    })
                    supply.append(zone)

    return {"demand": demand, "supply": supply}


def _chart_zone_broken_by_completed_m5_close(
    zone: dict[str, Any],
    kind: str,
    rows: list[dict[str, Any]],
) -> tuple[bool | None, str | None, float | None]:
    # Core zone creation deliberately reserves the eight M5 bars after the
    # pivot for proving departure. Its own "later" invalidation window begins
    # at origin + 9 bars. Chart mapping uses that identical causal start point,
    # but invalidates at the actual zone edge rather than the trade engine's
    # extra 0.20 ATR tolerance.
    source = list(rows[-360:])
    origin = str(zone.get("origin_time") or "")
    origin_index = next(
        (index for index, row in enumerate(source) if str(row.get("candle_time") or "") == origin),
        None,
    )
    if origin_index is None:
        # Unverifiable history is not equivalent to an intact zone.
        return None, None, None

    low = _num(zone.get("low"))
    high = _num(zone.get("high"))
    for row in source[origin_index + 9:]:
        close = _num(row.get("close"))
        if kind == "demand" and close < low:
            return True, str(row.get("candle_time") or ""), close
        if kind == "supply" and close > high:
            return True, str(row.get("candle_time") or ""), close
    return False, None, None


def _chart_zones_v95(
    self: core.LiveTrader,
    price: float,
    atr: float,
    h1: dict[str, list[dict[str, Any]]],
    m15: dict[str, list[dict[str, Any]]],
    rows: list[dict[str, Any]],
) -> dict[str, list[dict[str, Any]]]:
    raw_pool = getattr(self, "_chart_zone_raw_v95", None)
    if not isinstance(raw_pool, dict):
        self._chart_zones_status_v99 = {
            "available": False,
            "error": "stable_chart_zone_pool_unavailable",
        }
        return {"demand": [], "supply": []}

    result: dict[str, list[dict[str, Any]]] = {"demand": [], "supply": []}
    for kind in ("demand", "supply"):
        annotated: list[dict[str, Any]] = []
        for raw_zone in list(raw_pool.get(kind) or []):
            broken, broken_at, broken_close = _chart_zone_broken_by_completed_m5_close(raw_zone, kind, rows)
            if broken is not False:
                # True = broken. None = history cannot prove survival.
                continue
            zone = _confluence(dict(raw_zone), h1[kind], m15[kind], atr)
            zone["chart_invalidation_rule"] = (
                "completed_m5_close_below_zone_low"
                if kind == "demand"
                else "completed_m5_close_above_zone_high"
            )
            zone["chart_last_break_check_at"] = str((rows[-1] if rows else {}).get("candle_time") or "")
            zone["chart_broken_at"] = broken_at
            zone["chart_broken_close"] = broken_close
            annotated.append(zone)

        for zone in annotated:
            low = _num(zone.get("low"))
            high = _num(zone.get("high"))
            distance = 0.0 if low <= price <= high else min(abs(price - low), abs(price - high))
            zone["distance_atr"] = round(distance / max(atr, 0.01), 2)
            if low <= price <= high:
                zone["chart_state"] = "IN ZONE"
            elif kind == "demand" and price < low:
                zone["chart_state"] = "UNDER PRESSURE"
            elif kind == "supply" and price > high:
                zone["chart_state"] = "UNDER PRESSURE"
            else:
                zone["chart_state"] = "ACTIVE"

        # Chart mapping deliberately keeps every native M5 zone that has
        # NOT had a completed M5 close through its actual zone edge. Do not
        # top-N, proximity-filter or dynamically dedupe this list: those can
        # make a zone already drawn by the trader disappear/reappear without a
        # real structural break.
        annotated.sort(
            key=lambda z: (
                _num(z.get("distance_atr")),
                -int(z.get("mtf_confluence_count") or 0),
                -_num(z.get("quality")),
                int(z.get("retests") or 0),
            )
        )
        for index, zone in enumerate(annotated, start=1):
            zone["chart_rank"] = index
        result[kind] = annotated

    self._chart_zones_status_v99 = {
        "available": True,
        "error": None,
        "source": "stable_origin_atr_pool",
        "geometry_version": "eve-chart-zone-origin-atr-v1",
        "invalidation_version": "completed_m5_close_actual_edge_v1",
    }
    return result


def _zone_candidates_v63(self: core.LiveTrader, rows: list[dict[str, Any]], price: float, bias: dict[str, Any]) -> dict[str, list[dict[str, Any]]]:
    base = _BASE_ZONE_CANDIDATES(self, rows, price, bias)
    source = list(rows[-360:])
    atr = _num((source[-1] if source else {}).get("atr_14"))
    if len(source) < 20:
        self._chart_zone_raw_v95 = {"demand": [], "supply": []}
        self._chart_zones_v95 = {"demand": [], "supply": []}
        self._chart_zones_status_v99 = {"available": False, "error": "insufficient_completed_m5_history"}
        return base
    if atr <= 0:
        self._chart_zone_raw_v95 = {"demand": [], "supply": []}
        self._chart_zones_v95 = {"demand": [], "supply": []}
        self._chart_zones_status_v99 = {"available": False, "error": "latest_atr_unavailable"}
        return base

    stable_chart_pool = _stable_chart_zone_pool(self, source, price, bias)
    self._chart_zone_raw_v95 = stable_chart_pool
    h1 = _native_zones(rows[-720:], "H1", price)
    m15 = _native_zones(rows[-720:], "M15", price)

    result: dict[str, list[dict[str, Any]]] = {"demand": [], "supply": []}
    for kind in ("demand", "supply"):
        annotated = [_confluence(zone, h1[kind], m15[kind], atr) for zone in list(base.get(kind) or [])]
        annotated.sort(key=lambda z: (-_num(z.get("rank_score")), -int(z.get("mtf_confluence_count") or 0), -_num(z.get("quality")), _num(z.get("distance_atr"))))
        final = annotated[:FINAL_ZONE_COUNT]
        for index, zone in enumerate(final, start=1):
            zone["rank"] = index
            zone["preferred"] = index == 1
        result[kind] = final

    self._chart_zones_v95 = _chart_zones_v95(self, price, atr, h1, m15, rows)

    self._mtf_zone_map_v63 = {
        "version": MTF_ZONE_VERSION,
        "H1": h1,
        "M15": m15,
        "policy": "H1 zone -> M15 refinement -> M5 execution. A wider M5 pool is ranked first, HTF confluence is then applied, and only the final four execution zones are published. Weak/repeated HTF zones do not grant confluence boosts.",
    }
    return result


core.LiveTrader._zone_candidates = _zone_candidates_v63  # type: ignore[method-assign]
