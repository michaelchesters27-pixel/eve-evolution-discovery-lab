from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from app.services import live_trader_execution_forensics_v47 as fx
from app.services import live_trader_execution_integrity_v39 as integrity


def bar(stamp: str, low: float, high: float, close: float) -> dict:
    return {"candle_time": stamp, "open": close, "high": high, "low": low, "close": close, "volume": 1}


def continuous_bars(start: datetime, end: datetime) -> list[dict]:
    rows = []
    cursor = start
    while cursor <= end:
        rows.append(bar(cursor.isoformat(), 99.0, 101.0, 100.0))
        cursor += timedelta(minutes=1)
    return rows


def test_entry_maturity_is_diagnostic_and_rewards_aligned_context() -> None:
    context = {
        "bias": {"confidence": 80},
        "setup_family_descriptor": {
            "htf_alignment": "bullish",
            "intraday_alignment": "bullish",
            "zone_quality": "high",
            "location": "in_demand",
        },
        "liquidity": {"primary_event": {"implication": "bullish"}},
    }
    result = fx.entry_maturity_score(context, "BUY")
    assert result["available"] is True
    assert result["score"] >= 85
    assert "does not arm or veto" in result["reason"]


def test_loss_forensics_detects_target_reached_after_stop() -> None:
    campaign = {
        "id": "loss-1",
        "status": "lost",
        "side": "BUY",
        "order_type": "buy_stop",
        "entry": 100.0,
        "stop": 99.0,
        "target": 102.0,
        "risk_reward": 2.0,
        "created_at": "2026-08-24T08:00:00+00:00",
        "triggered_at": "2026-08-24T08:05:10+00:00",
        "completed_at": "2026-08-24T08:10:20+00:00",
    }
    bars = [
        bar("2026-08-24T08:06:00+00:00", 99.8, 100.4, 100.2),
        bar("2026-08-24T08:07:00+00:00", 99.6, 100.6, 100.1),
        bar("2026-08-24T08:11:00+00:00", 99.2, 101.4, 101.0),
        bar("2026-08-24T08:12:00+00:00", 100.5, 102.2, 102.0),
    ]
    metrics = fx._path_metrics(campaign, bars)
    assert metrics["mfe_r"] == 0.6
    assert metrics["mae_r"] == 1.0
    assert metrics["target_reached_after_completion"] is True
    diagnosis = fx._diagnosis(campaign, metrics, None)
    assert diagnosis["primary"] == "execution_timing_or_stop"
    assert diagnosis["stop"] == "timing_or_stop_geometry_suspect"
    assert diagnosis["target"] == "reachable_after_stop"


def test_partial_trigger_and_completion_candles_are_excluded_from_mfe_mae() -> None:
    campaign = {
        "status": "closed",
        "side": "BUY",
        "entry": 100.0,
        "stop": 99.0,
        "target": 102.0,
        "risk_reward": 2.0,
        "created_at": "2026-08-24T08:00:00+00:00",
        "triggered_at": "2026-08-24T08:05:10+00:00",
        "completed_at": "2026-08-24T08:08:20+00:00",
    }
    bars = [
        # These extrema are ambiguous because the trigger occurs inside this candle.
        bar("2026-08-24T08:05:00+00:00", 90.0, 110.0, 100.0),
        bar("2026-08-24T08:06:00+00:00", 99.8, 100.3, 100.0),
        bar("2026-08-24T08:07:00+00:00", 99.7, 100.4, 100.0),
        # Completion occurs inside this candle, so it is ambiguous too.
        bar("2026-08-24T08:08:00+00:00", 90.0, 110.0, 100.0),
    ]
    metrics = fx._path_metrics(campaign, bars)
    assert metrics["active_path_full_bars"] == 2
    assert metrics["mfe_r"] == 0.4
    assert metrics["mae_r"] == 0.3
    assert metrics["boundary_policy"] == "exclude_partial_trigger_and_completion_m1_candles"


def test_late_trigger_fast_loss_is_classified_as_aged_setup() -> None:
    campaign = {
        "status": "lost",
        "side": "SELL",
        "risk_reward": 2.2,
        "triggered_at": "2026-08-24T10:00:00+00:00",
    }
    metrics = {
        "mfe_r": 0.1,
        "post_completion_best_r": 0.2,
        "target_reached_after_completion": False,
        "time_to_trigger_minutes": 120.0,
        "active_minutes": 8.0,
    }
    diagnosis = fx._diagnosis(campaign, metrics, {"direction_correct": None})
    assert diagnosis["primary"] == "aged_setup_trigger"
    assert diagnosis["entry_timing"] == "aged_setup_triggered_late"


def test_historical_challenger_summary_reuses_existing_academy_evidence() -> None:
    rows = [
        {
            "best_challenger": "confirmation_stop",
            "challenger_results": {
                "confirmation_stop": {"realised_r": 2.0, "learning_success": True},
                "market": {"realised_r": -1.0, "learning_success": False},
            },
        },
        {
            "best_challenger": "confirmation_stop",
            "challenger_results": {
                "confirmation_stop": {"realised_r": 1.5, "learning_success": True},
                "market": {"realised_r": 0.1, "learning_success": True},
            },
        },
    ]
    summary = fx._historical_challenger_summary(rows)
    assert summary["dominant_best_challenger"] == "confirmation_stop"
    assert summary["alternatives"]["confirmation_stop"]["avg_r"] == 1.75
    assert summary["alternatives"]["confirmation_stop"]["success_rate"] == 1.0


def test_worker_requires_full_continuous_post_completion_path() -> None:
    worker = object.__new__(fx.ExecutionForensicsWorker)
    campaign = {
        "created_at": "2026-08-24T08:00:30+00:00",
        "completed_at": "2026-08-24T08:10:20+00:00",
    }
    start = datetime(2026, 8, 24, 7, 56, tzinfo=timezone.utc)
    end = datetime(2026, 8, 24, 9, 10, tzinfo=timezone.utc)
    complete = continuous_bars(start, end)
    assert worker._path_is_ready(campaign, complete) is True

    missing_middle = [row for row in complete if row["candle_time"] != datetime(2026, 8, 24, 8, 30, tzinfo=timezone.utc).isoformat()]
    assert worker._path_is_ready(campaign, missing_middle) is False
    assert worker._path_is_ready(campaign, complete[:-1]) is False
    assert worker._path_is_ready(campaign, complete[1:]) is False


def test_review_scan_uses_offset_so_unprocessable_old_rows_cannot_starve_newer_rows() -> None:
    class Client:
        def __init__(self) -> None:
            self.params = None

        async def get(self, _table, *, params):
            self.params = dict(params)
            return [{"campaign_id": "later", "review": {}, "completed_at": "2026-08-24T09:00:00+00:00"}]

    client = Client()
    worker = object.__new__(fx.ExecutionForensicsWorker)
    worker.repo = SimpleNamespace(client=client)
    worker.symbol = "XAU/USD"
    pending, raw_count = asyncio.run(worker._review_page(100))
    assert raw_count == 1
    assert pending[0]["campaign_id"] == "later"
    assert client.params["offset"] == "100"


def test_forensics_waits_until_execution_regrade_is_complete() -> None:
    worker = object.__new__(fx.ExecutionForensicsWorker)
    worker.owner = SimpleNamespace(_execution_regrade_ready_v39=False)
    assert asyncio.run(worker.enrich({"campaign_id": "must-not-read"})) is False


def test_historical_challengers_are_filtered_to_current_execution_schema() -> None:
    class Client:
        def __init__(self) -> None:
            self.calls = []

        async def get(self, table, *, params):
            self.calls.append((table, dict(params)))
            return []

    client = Client()
    worker = object.__new__(fx.ExecutionForensicsWorker)
    worker.repo = SimpleNamespace(client=client)
    worker.symbol = "XAU/USD"
    asyncio.run(worker._family_rows("family-1"))
    historical_params = client.calls[1][1]
    assert historical_params["market_state->execution_regrade->>version"] == f"eq.{integrity.REGRADER_VERSION}"
    assert historical_params["market_state->execution_regrade->>execution_schema"] == f"eq.{integrity.EXECUTION_SCHEMA}"


def test_forward_proven_confidence_requires_mature_evidence() -> None:
    building = fx._forward_family_evidence_summary([
        {"observed_at": "2026-08-24T08:00:00+00:00", "learning_success": True}
    ])
    assert building["confidence"] is None
    rows = []
    for day in (20, 21, 24):
        for hour in range(4):
            rows.append({"observed_at": f"2026-08-{day:02d}T{8+hour:02d}:00:00+00:00", "learning_success": True})
    mature = fx._forward_family_evidence_summary(rows)
    assert mature["mature"] is True
    assert mature["confidence"] is not None
