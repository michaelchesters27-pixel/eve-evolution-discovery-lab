from __future__ import annotations

from types import SimpleNamespace

from app.services.live_trader import LiveTrader
from app.services.live_trader_zone_ranking_v62 import _dedupe_zones_v62
from app.services.live_trader_mtf_zones_v63 import _chart_zones_v95


def trader() -> LiveTrader:
    settings = SimpleNamespace(
        live_trader_symbol="XAU/USD",
        live_trader_enabled=True,
        twelve_data_api_key="test-key",
        twelve_data_ws_url="wss://example.invalid",
        live_trader_learning_horizon_minutes=60,
    )
    return LiveTrader(settings, SimpleNamespace())


def test_chart_zone_survives_trade_proximity_filter_until_true_invalidation() -> None:
    engine = trader()
    still_valid_demand = {
        "id": "same-zone",
        "kind": "demand",
        "low": 101.0,
        "high": 103.0,
        "mid": 102.0,
        "quality": 72,
        "quality_label": "HIGH",
        "status": "ACTIVE",
        "retests": 1,
        "fresh": False,
        "departure_atr": 2.0,
        "distance_atr": 1.0,
        "origin_time": "2026-09-30T15:25:00+00:00",
        "origin_session": "new_york",
    }

    # Existing trade-facing behaviour is deliberately unchanged: with price at
    # 100 and ATR 2, a demand zone whose top is 103 is more than 0.5 ATR above
    # price and is omitted from the trade-facing zone list.
    published = _dedupe_zones_v62(
        engine,
        [still_valid_demand],
        price=100.0,
        atr=2.0,
        kind="demand",
    )
    assert published == []

    # But the same already-validated zone is retained for chart mapping.
    assert engine._chart_zone_raw_v95["demand"][0]["id"] == "same-zone"

    chart = _chart_zones_v95(
        engine,
        price=100.0,
        atr=2.0,
        h1={"demand": [], "supply": []},
        m15={"demand": [], "supply": []},
        rows=[],
    )
    assert chart["demand"][0]["id"] == "same-zone"
    assert chart["demand"][0]["low"] == 101.0
    assert chart["demand"][0]["high"] == 103.0
    assert chart["demand"][0]["chart_state"] == "UNDER PRESSURE"


def test_chart_zone_keeps_same_id_when_price_moves_back_inside() -> None:
    engine = trader()
    zone = {
        "id": "same-zone",
        "kind": "demand",
        "low": 101.0,
        "high": 103.0,
        "mid": 102.0,
        "quality": 72,
        "quality_label": "HIGH",
        "status": "ACTIVE",
        "retests": 1,
        "fresh": False,
        "departure_atr": 2.0,
        "distance_atr": 1.0,
        "origin_time": "2026-09-30T15:25:00+00:00",
        "origin_session": "new_york",
    }
    _dedupe_zones_v62(engine, [zone], price=100.0, atr=2.0, kind="demand")

    below = _chart_zones_v95(
        engine,
        price=100.0,
        atr=2.0,
        h1={"demand": [], "supply": []},
        m15={"demand": [], "supply": []},
        rows=[],
    )["demand"][0]
    inside = _chart_zones_v95(
        engine,
        price=102.0,
        atr=2.0,
        h1={"demand": [], "supply": []},
        m15={"demand": [], "supply": []},
        rows=[],
    )["demand"][0]

    assert below["id"] == inside["id"] == "same-zone"
    assert below["chart_state"] == "UNDER PRESSURE"
    assert inside["chart_state"] == "IN ZONE"



def _rows(origin_close: float, later_closes: list[float]) -> list[dict]:
    rows = [
        {
            "candle_time": f"2026-09-30T15:{minute:02d}:00+00:00",
            "close": origin_close,
        }
        for minute in range(0, 45, 5)
    ]
    rows[5]["candle_time"] = "2026-09-30T15:25:00+00:00"
    for offset, close in enumerate(later_closes, start=0):
        rows.append(
            {
                "candle_time": f"2026-09-30T16:{offset * 5:02d}:00+00:00",
                "close": close,
            }
        )
    return rows


def _mapped_zone(kind: str) -> dict:
    return {
        "id": f"{kind}-zone",
        "kind": kind,
        "low": 101.0,
        "high": 103.0,
        "mid": 102.0,
        "quality": 72,
        "quality_label": "HIGH",
        "status": "ACTIVE",
        "retests": 1,
        "fresh": False,
        "departure_atr": 2.0,
        "distance_atr": 1.0,
        "origin_time": "2026-09-30T15:25:00+00:00",
        "origin_session": "new_york",
    }


def test_chart_demand_zone_removed_on_completed_m5_close_below_low() -> None:
    engine = trader()
    _dedupe_zones_v62(engine, [_mapped_zone("demand")], price=100.0, atr=2.0, kind="demand")

    chart = _chart_zones_v95(
        engine,
        price=100.0,
        atr=2.0,
        h1={"demand": [], "supply": []},
        m15={"demand": [], "supply": []},
        rows=_rows(102.0, [101.4, 100.9]),
    )
    assert chart["demand"] == []


def test_chart_demand_zone_survives_wick_or_live_price_below_when_completed_close_holds() -> None:
    engine = trader()
    _dedupe_zones_v62(engine, [_mapped_zone("demand")], price=100.0, atr=2.0, kind="demand")

    chart = _chart_zones_v95(
        engine,
        price=100.0,
        atr=2.0,
        h1={"demand": [], "supply": []},
        m15={"demand": [], "supply": []},
        rows=_rows(102.0, [101.2, 101.0]),
    )
    assert chart["demand"][0]["id"] == "demand-zone"
    assert chart["demand"][0]["chart_state"] == "UNDER PRESSURE"
    assert chart["demand"][0]["chart_invalidation_rule"] == "completed_m5_close_below_zone_low"


def test_chart_supply_zone_removed_on_completed_m5_close_above_high() -> None:
    engine = trader()
    _dedupe_zones_v62(engine, [_mapped_zone("supply")], price=104.0, atr=2.0, kind="supply")

    chart = _chart_zones_v95(
        engine,
        price=104.0,
        atr=2.0,
        h1={"demand": [], "supply": []},
        m15={"demand": [], "supply": []},
        rows=_rows(102.0, [102.7, 103.1]),
    )
    assert chart["supply"] == []
