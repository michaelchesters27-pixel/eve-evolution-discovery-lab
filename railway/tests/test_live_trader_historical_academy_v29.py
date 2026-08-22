from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from app.services import live_trader as core
from app.services import live_trader_historical_learning_v29 as academy
from app.services import live_trader_historical_runtime_v30 as runtime


def utc(year: int, month: int, day: int, hour: int, minute: int = 0) -> datetime:
    return datetime(year, month, day, hour, minute, tzinfo=timezone.utc)


def test_ic_markets_weekend_boundary_respects_new_york_dst() -> None:
    # August is EDT: 17:00 ET == 21:00 UTC.
    assert academy.broker_market_open(utc(2026, 8, 21, 20, 59)) is True
    assert academy.broker_market_open(utc(2026, 8, 21, 21, 0)) is False
    assert academy.broker_market_open(utc(2026, 8, 22, 12, 0)) is False
    assert academy.broker_market_open(utc(2026, 8, 23, 20, 59)) is False
    assert academy.broker_market_open(utc(2026, 8, 23, 21, 0)) is True


def test_forward_learning_requires_full_horizon_before_weekend_close() -> None:
    # Friday 16:30 ET with a 60-minute horizon crosses the 17:00 ET close.
    assert academy.broker_market_open_through(utc(2026, 8, 21, 20, 30), 60) is False
    # Friday 15:30 ET resolves before the close.
    assert academy.broker_market_open_through(utc(2026, 8, 21, 19, 30), 60) is True


def test_hourly_historical_anchor_is_deliberately_independent() -> None:
    assert academy.LiveTraderHistoricalLearner._hourly_anchor(utc(2024, 1, 2, 10, 0)) is True
    assert academy.LiveTraderHistoricalLearner._hourly_anchor(utc(2024, 1, 2, 10, 5)) is False


class FakeClient:
    def __init__(self, rows: list[dict]) -> None:
        self.rows = rows

    async def get(self, table: str, **_kwargs):
        if table == "live_trader_historical_learning":
            return list(self.rows)
        return []


class FakeRepo:
    def __init__(self, rows: list[dict]) -> None:
        self.client = FakeClient(rows)


class FakeTrader:
    def __init__(self, rows: list[dict]) -> None:
        self.repo = FakeRepo(rows)
        self._learning_descriptor_v22 = {
            "session": "london",
            "regime_group": "trend",
            "momentum_relation": "aligned",
            "zone_quality": "high",
        }


def historical_rows(wins: int = 18, total: int = 24) -> list[dict]:
    rows = []
    start = utc(2025, 1, 6, 10, 0)
    for index in range(total):
        stamp = start + timedelta(days=index // 2)
        rows.append(
            {
                "learning_success": index < wins,
                "independence_key": f"independent-{index}",
                "observed_at": stamp.isoformat(),
                "evidence_weight": academy.HISTORICAL_BASE_WEIGHT,
                "path_complete": True,
                "market_state": {
                    "setup_family_descriptor": {
                        "session": "london",
                        "regime_group": "trend",
                        "momentum_relation": "aligned",
                        "zone_quality": "high",
                    }
                },
            }
        )
    return rows


def test_history_can_seed_confidence_but_cannot_activate_live_governor(monkeypatch) -> None:
    trader = FakeTrader(historical_rows())

    async def live_calibration(_self, _signature):
        return {
            "samples": 0,
            "effective_samples": 0,
            "accuracy": None,
            "posterior_accuracy": 0.5,
            "active": False,
            "confidence_adjustment": 0.0,
        }

    monkeypatch.setattr(academy, "_current_calibration", live_calibration)
    result = asyncio.run(academy._calibration_v29(trader, "family"))

    assert result["active"] is False
    assert result["historical_samples"] == 24
    assert result["historical_days"] == 12
    assert result["historical_seed_active"] is True
    assert 0 < result["confidence_adjustment"] <= academy.HISTORICAL_CONFIDENCE_CAP
    assert result["confidence_adjustment_source"] == "historical_seed"


def test_historical_evidence_is_capped_even_with_many_replays(monkeypatch) -> None:
    trader = FakeTrader(historical_rows(wins=150, total=200))

    async def live_calibration(_self, _signature):
        return {
            "samples": 0,
            "effective_samples": 0,
            "accuracy": None,
            "posterior_accuracy": 0.5,
            "active": False,
            "confidence_adjustment": 0.0,
        }

    monkeypatch.setattr(academy, "_current_calibration", live_calibration)
    result = asyncio.run(academy._calibration_v29(trader, "family"))

    assert result["historical_effective_samples"] == academy.HISTORICAL_EFFECTIVE_CAP
    assert abs(result["confidence_adjustment"]) <= academy.HISTORICAL_CONFIDENCE_CAP


def test_same_m1_path_scores_execution_challengers_conservatively() -> None:
    bars = [
        {"low": 99.0, "high": 101.0},
        {"low": 98.0, "high": 103.0},
    ]
    challengers = {
        "market": {
            "side": "BUY",
            "order_type": "market",
            "entry": 100.0,
            "stop": 98.0,
            "target": 103.0,
            "risk_reward": 1.5,
        }
    }
    scored, best = academy.LiveTraderHistoricalLearner._score_challengers(challengers, bars, 102.0)

    # Second bar touches both stop and target; conservative replay assumes stop first.
    assert scored["market"]["trade_outcome"] == "stop"
    assert scored["market"]["learning_success"] is False
    assert best == "market"


def test_runtime_patches_live_trader_with_historical_worker() -> None:
    assert core.LiveTrader.run_forever is runtime._run_forever_v30
    assert core.LiveTrader.refresh_state is runtime._refresh_state_v30
    assert core.LiveTrader._calibration is academy._calibration_v29
