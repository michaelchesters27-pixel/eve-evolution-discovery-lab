from __future__ import annotations

from app.services import live_trader_execution_forensics_v47 as fx


def bar(stamp: str, low: float, high: float, close: float) -> dict:
    return {"candle_time": stamp, "open": close, "high": high, "low": low, "close": close, "volume": 1}


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


def test_worker_waits_for_full_post_completion_window() -> None:
    worker = object.__new__(fx.ExecutionForensicsWorker)
    campaign = {"completed_at": "2026-08-24T08:10:20+00:00"}
    incomplete = [bar("2026-08-24T09:09:00+00:00", 99, 101, 100)]
    complete = [bar("2026-08-24T09:10:00+00:00", 99, 101, 100)]
    assert worker._path_is_ready(campaign, incomplete) is False
    assert worker._path_is_ready(campaign, complete) is True


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
