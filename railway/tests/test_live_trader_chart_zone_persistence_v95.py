from __future__ import annotations

from types import SimpleNamespace

from app.services.live_trader import LiveTrader
from app.services.live_trader_mtf_zones_v63 import (
    _chart_zone_broken_by_completed_m5_close,
    _chart_zones_v95,
    _stable_chart_zone_pool,
)


def trader() -> LiveTrader:
    settings = SimpleNamespace(
        live_trader_symbol="XAU/USD",
        live_trader_enabled=True,
        twelve_data_api_key="test-key",
        twelve_data_ws_url="wss://example.invalid",
        live_trader_learning_horizon_minutes=60,
    )
    return LiveTrader(settings, SimpleNamespace())


def _rows(origin_close: float, later_closes: list[float]) -> list[dict]:
    formation_times = [
        "2026-09-30T15:25:00+00:00",
        "2026-09-30T15:30:00+00:00",
        "2026-09-30T15:35:00+00:00",
        "2026-09-30T15:40:00+00:00",
        "2026-09-30T15:45:00+00:00",
        "2026-09-30T15:50:00+00:00",
        "2026-09-30T15:55:00+00:00",
        "2026-09-30T16:00:00+00:00",
        "2026-09-30T16:05:00+00:00",
    ]
    rows = [
        {
            "candle_time": stamp,
            "open": 101.5,
            "high": 102.0,
            "low": 101.0,
            "close": origin_close,
            "atr_14": 2.0,
            "session": "new_york",
        }
        for stamp in formation_times
    ]
    later_times = [
        "2026-09-30T16:10:00+00:00",
        "2026-09-30T16:15:00+00:00",
        "2026-09-30T16:20:00+00:00",
        "2026-09-30T16:25:00+00:00",
    ]
    for stamp, close in zip(later_times, later_closes):
        rows.append(
            {
                "candle_time": stamp,
                "open": close,
                "high": max(close + 0.5, 101.5),
                "low": min(close - 0.5, 100.5),
                "close": close,
                "atr_14": 2.0,
                "session": "new_york",
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


def test_missing_origin_or_rows_is_unverifiable_not_intact() -> None:
    zone = _mapped_zone("demand")
    assert _chart_zone_broken_by_completed_m5_close(zone, "demand", []) == (None, None, None)
    rows = _rows(102.0, [101.5, 101.4])
    zone["origin_time"] = "2026-09-29T00:00:00+00:00"
    assert _chart_zone_broken_by_completed_m5_close(zone, "demand", rows) == (None, None, None)


def test_chart_demand_zone_removed_on_completed_m5_close_below_low() -> None:
    engine = trader()
    engine._chart_zone_raw_v95 = {"demand": [_mapped_zone("demand")], "supply": []}
    chart = _chart_zones_v95(
        engine,
        price=100.0,
        atr=2.0,
        h1={"demand": [], "supply": []},
        m15={"demand": [], "supply": []},
        rows=_rows(102.0, [101.4, 100.9]),
    )
    assert chart["demand"] == []


def test_chart_demand_zone_survives_live_price_below_when_completed_close_holds() -> None:
    engine = trader()
    engine._chart_zone_raw_v95 = {"demand": [_mapped_zone("demand")], "supply": []}
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
    engine._chart_zone_raw_v95 = {"demand": [], "supply": [_mapped_zone("supply")]}
    chart = _chart_zones_v95(
        engine,
        price=104.0,
        atr=2.0,
        h1={"demand": [], "supply": []},
        m15={"demand": [], "supply": []},
        rows=_rows(102.0, [102.7, 103.1]),
    )
    assert chart["supply"] == []


def _stable_pool_rows(latest_atr: float) -> list[dict]:
    rows: list[dict] = []
    for i in range(22):
        minute = i * 5
        hour = minute // 60
        mm = minute % 60
        rows.append(
            {
                "candle_time": f"2026-09-30T{hour:02d}:{mm:02d}:00+00:00",
                "open": 101.0,
                "high": 101.2,
                "low": 100.8,
                "close": 101.0,
                "atr_14": 1.0,
                "session": "london",
            }
        )

    origin = rows[2]
    origin.update({"open": 100.5, "high": 101.0, "low": 100.0, "close": 100.6, "atr_14": 1.0})
    rows[3]["high"] = 101.5
    for i in range(11, len(rows)):
        rows[i].update({"low": 100.7, "high": 101.4, "close": 101.1})
    rows[-1]["atr_14"] = latest_atr
    return rows


def test_chart_zone_geometry_and_presence_do_not_depend_on_latest_atr() -> None:
    engine = trader()
    bias = {"timeframes": {}}
    quiet = _stable_chart_zone_pool(engine, _stable_pool_rows(1.0), 105.0, bias)
    volatile = _stable_chart_zone_pool(engine, _stable_pool_rows(20.0), 105.0, bias)

    q = next(zone for zone in quiet["demand"] if zone["origin_time"] == "2026-09-30T00:10:00+00:00")
    v = next(zone for zone in volatile["demand"] if zone["origin_time"] == "2026-09-30T00:10:00+00:00")

    assert q["id"] == v["id"]
    assert q["low"] == v["low"] == 100.0
    assert q["high"] == v["high"]
    assert q["origin_atr_14"] == v["origin_atr_14"] == 1.0
    assert q["geometry_version"] == "eve-chart-zone-origin-atr-v1"
    assert q["quality_version"] == "eve-chart-zone-quality-v1"
    assert q["quality_inputs"]["departure_atr"] == v["quality_inputs"]["departure_atr"]
    assert q["quality_inputs"]["touch_bars"] == v["quality_inputs"]["touch_bars"]
