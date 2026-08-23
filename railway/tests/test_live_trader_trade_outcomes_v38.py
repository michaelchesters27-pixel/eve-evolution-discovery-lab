from __future__ import annotations

from datetime import datetime, timezone

from app.services import live_trader as core
from app.services import live_trader_historical_runtime_v30 as runtime
from app.services import live_trader_trade_lock_v28 as lock
from app.services import live_trader_trade_outcomes_v38 as outcomes


def utc(year: int, month: int, day: int, hour: int = 0, minute: int = 0) -> datetime:
    return datetime(year, month, day, hour, minute, tzinfo=timezone.utc)


def test_weekly_result_uses_sunday_to_saturday_uk_window() -> None:
    start, start_utc, end_utc = outcomes._week_window(utc(2026, 8, 23, 8))
    assert start.isoformat() == "2026-08-23"
    # August is BST, so UK Sunday midnight is 23:00 UTC Saturday.
    assert start_utc.isoformat() == "2026-08-22T23:00:00+00:00"
    assert end_utc.isoformat() == "2026-08-29T23:00:00+00:00"


def test_realised_r_is_honest_strategy_result() -> None:
    assert outcomes._campaign_realised_r({"status": "lost", "risk_reward": 7.25}) == -1.0
    assert outcomes._campaign_realised_r({"status": "won", "risk_reward": 2.2}) == 2.2
    assert outcomes._campaign_realised_r({"status": "invalidated", "risk_reward": 9.0}) == 0.0
    assert outcomes._campaign_realised_r({"status": "expired", "risk_reward": 9.0}) == 0.0
    assert outcomes._campaign_realised_r({"status": "won", "entry": 100, "stop": 98, "target": 106}) == 3.0


def test_losing_trade_review_is_negative_execution_evidence_not_double_counted() -> None:
    campaign = {
        "id": "loss-1",
        "status": "lost",
        "side": "SELL",
        "order_type": "sell_stop",
        "entry": 100,
        "stop": 101,
        "target": 97,
        "risk_reward": 3.0,
        "outcome_learning_v38": {
            "publication_context_quality": "publication_snapshot",
            "publication_context": {"setup_family": "family-1"},
        },
    }
    review = outcomes._review_payload(campaign, {"setup_family": "family-1"})
    assert review["signal"] == "negative"
    assert review["priority"] == "high"
    assert review["realised_r"] == -1.0
    assert review["evidence_role"] == "execution_postmortem_not_second_independent_sample"
    assert "One loss must not rewrite" in review["lesson"]


def test_legacy_campaign_is_not_given_fake_publication_context(monkeypatch) -> None:
    monkeypatch.setattr(outcomes.core, "utc_now", lambda: utc(2026, 8, 23, 8))
    assert outcomes._publication_is_current({"created_at": "2026-08-21T20:07:03+00:00"}) is False
    assert outcomes._publication_is_current({"created_at": "2026-08-23T07:59:30+00:00"}) is True


def test_latest_runtime_refresh_aliases_still_point_to_v38() -> None:
    assert core.LiveTrader.refresh_state is outcomes._refresh_v38
    assert core.LiveTrader.refresh_state is lock._refresh_state_v28
    assert core.LiveTrader.refresh_state is runtime._refresh_state_v30
