from __future__ import annotations

from typing import Any

from app.services import live_trader as core

ZONE_RANKING_VERSION = "eve-live-zone-ranking-v62"
PRECONFLUENCE_POOL_SIZE = 8


def _num(value: Any, default: float = 0.0) -> float:
    return core.number(value, default)


def _rank_score(zone: dict[str, Any]) -> float:
    quality = _num(zone.get("quality"))
    retests = max(0.0, _num(zone.get("retests")))
    departure = min(max(_num(zone.get("departure_atr")), 0.0), 4.0)
    distance = min(max(_num(zone.get("distance_atr")), 0.0), 10.0)
    fresh_bonus = 5.0 if bool(zone.get("fresh")) else 0.0
    return quality + fresh_bonus + departure * 2.0 - retests * 2.5 - distance * 1.25


def _dedupe_zones_v62(
    self: core.LiveTrader,
    zones: list[dict[str, Any]],
    price: float,
    atr: float,
    *,
    kind: str,
) -> list[dict[str, Any]]:
    eligible: list[dict[str, Any]] = []
    for raw in zones:
        zone = dict(raw)
        if kind == "demand" and _num(zone.get("high")) > price + atr * 0.5:
            continue
        if kind == "supply" and _num(zone.get("low")) < price - atr * 0.5:
            continue
        zone["rank_score"] = round(_rank_score(zone), 2)
        zone["ranking_version"] = ZONE_RANKING_VERSION
        eligible.append(zone)

    eligible.sort(key=lambda z: (-_num(z.get("rank_score")), -_num(z.get("quality")), _num(z.get("distance_atr"))))
    kept: list[dict[str, Any]] = []
    for zone in eligible:
        midpoint = _num(zone.get("mid"))
        if any(abs(midpoint - _num(other.get("mid"))) <= atr * 0.65 for other in kept):
            continue
        kept.append(zone)
        # v63 must see a wider candidate pool before H1/M15 confluence is added;
        # otherwise a lower standalone M5 rank can never be rescued by strong HTF backing.
        if len(kept) >= PRECONFLUENCE_POOL_SIZE:
            break

    for index, zone in enumerate(kept, start=1):
        zone["preconfluence_rank"] = index
        zone["rank"] = index
        zone["preferred"] = index == 1
    return kept


core.LiveTrader._dedupe_zones = _dedupe_zones_v62  # type: ignore[method-assign]
