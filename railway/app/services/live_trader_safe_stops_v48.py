from __future__ import annotations

from typing import Any

from app.services import live_trader as core

SAFE_STOPS_VERSION = "eve-live-safe-stops-v1"
ATR_BUFFER = 0.22
CLUSTER_ATR = 0.75
FALLBACK_ATR = 1.50

_current_refresh_state = core.LiveTrader.refresh_state
_current_runtime_status = core.LiveTrader.runtime_status


def _candidate(value: Any, label: str, price: float, side: str) -> dict[str, Any] | None:
    level = core.number(value)
    if level <= 0:
        return None
    if side == "below" and level >= price:
        return None
    if side == "above" and level <= price:
        return None
    return {"level": level, "label": label}


def _structural_reference(
    *,
    price: float,
    atr: float,
    candidates: list[dict[str, Any]],
    side: str,
) -> dict[str, Any]:
    atr = max(core.number(atr), 0.01)
    buffer = max(atr * ATR_BUFFER, 0.01)
    cluster_width = atr * CLUSTER_ATR

    clean = [item for item in candidates if core.number(item.get("level")) > 0]
    if not clean:
        level = price - atr * FALLBACK_ATR if side == "below" else price + atr * FALLBACK_ATR
        return {
            "level": round(level, 3),
            "anchor": None,
            "anchor_type": "atr_fallback",
            "sources": ["ATR fallback"],
            "distance_atr": round(abs(price - level) / atr, 2),
            "buffer_atr": ATR_BUFFER,
            "fallback": True,
        }

    if side == "below":
        nearest = max(core.number(item.get("level")) for item in clean)
        cluster = [item for item in clean if nearest - core.number(item.get("level")) <= cluster_width]
        anchor = min(core.number(item.get("level")) for item in cluster)
        level = anchor - buffer
    else:
        nearest = min(core.number(item.get("level")) for item in clean)
        cluster = [item for item in clean if core.number(item.get("level")) - nearest <= cluster_width]
        anchor = max(core.number(item.get("level")) for item in cluster)
        level = anchor + buffer

    source_labels = sorted({str(item.get("label") or "Structure") for item in cluster})
    return {
        "level": round(level, 3),
        "anchor": round(anchor, 3),
        "anchor_type": "structural_cluster",
        "sources": source_labels,
        "distance_atr": round(abs(price - level) / atr, 2),
        "buffer_atr": ATR_BUFFER,
        "fallback": False,
    }


def safe_stop_references(state: dict[str, Any] | None) -> dict[str, Any]:
    payload = dict(state or {})
    price = core.number(payload.get("price"))
    market = dict(payload.get("market") or {})
    atr = max(core.number(market.get("atr")), 0.01)
    zones = dict(payload.get("zones") or {})
    liquidity = dict(payload.get("liquidity") or {})

    if price <= 0:
        return {
            "version": SAFE_STOPS_VERSION,
            "available": False,
            "informational_only": True,
            "buy": {"level": None},
            "sell": {"level": None},
        }

    below: list[dict[str, Any]] = []
    above: list[dict[str, Any]] = []

    for zone in list(zones.get("demand") or [])[:4]:
        item = _candidate((zone or {}).get("low"), "Demand zone", price, "below")
        if item:
            below.append(item)
    for zone in list(zones.get("supply") or [])[:4]:
        item = _candidate((zone or {}).get("high"), "Supply zone", price, "above")
        if item:
            above.append(item)

    for key, label in (
        ("recent_low", "Recent low"),
        ("previous_day_low", "Previous day low"),
        ("london_low", "London low"),
        ("new_york_low", "New York low"),
    ):
        item = _candidate(liquidity.get(key), label, price, "below")
        if item:
            below.append(item)

    for key, label in (
        ("recent_high", "Recent high"),
        ("previous_day_high", "Previous day high"),
        ("london_high", "London high"),
        ("new_york_high", "New York high"),
    ):
        item = _candidate(liquidity.get(key), label, price, "above")
        if item:
            above.append(item)

    return {
        "version": SAFE_STOPS_VERSION,
        "available": True,
        "informational_only": True,
        "buy": _structural_reference(price=price, atr=atr, candidates=below, side="below"),
        "sell": _structural_reference(price=price, atr=atr, candidates=above, side="above"),
        "policy": (
            "Informational structural stop references only. BUY SAFE SL sits beyond the nearest downside "
            "structure/liquidity cluster; SELL SAFE SL sits beyond the nearest upside cluster. These references "
            "do not alter EVE's published trade, campaign stop, trade gate, confidence, or execution rules."
        ),
    }


async def _refresh_state_v48(self: core.LiveTrader, *, force_rows: bool = False) -> dict[str, Any]:
    state = dict(await _current_refresh_state(self, force_rows=force_rows))
    state["safe_stops"] = safe_stop_references(state)
    self._latest_state = state
    return state


def _runtime_status_v48(self: core.LiveTrader) -> dict[str, Any]:
    status = dict(_current_runtime_status(self))
    status.update(
        {
            "safe_stops_version": SAFE_STOPS_VERSION,
            "safe_stops_informational_only": True,
            "safe_stops_atr_buffer": ATR_BUFFER,
            "safe_stops_cluster_atr": CLUSTER_ATR,
        }
    )
    return status


core.LiveTrader.refresh_state = _refresh_state_v48  # type: ignore[method-assign]
core.LiveTrader.runtime_status = _runtime_status_v48  # type: ignore[method-assign]
