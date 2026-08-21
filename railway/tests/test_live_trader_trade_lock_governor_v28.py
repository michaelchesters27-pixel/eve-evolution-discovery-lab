from __future__ import annotations

import asyncio
from datetime import datetime, timezone

from app.services import live_trader_trade_lock_v28 as lock


class Dummy:
    pass


def open_campaign() -> dict:
    return {
        "id": "locked-1",
        "status": "pending",
        "side": "BUY",
        "order_type": "buy_stop",
        "entry": 100.0,
        "stop": 95.0,
        "target": 110.0,
        "risk_reward": 2.0,
        "confidence": 70,
        "reason": "published",
        "invalidation": "Cancel below 96.00 before triggering.",
        "invalidation_price": 96.0,
        "created_at": "2026-08-21T12:00:00+00:00",
        "expires_at": "2026-08-21T15:00:00+00:00",
        "published_trade": {
            "action": "BUY STOP",
            "side": "BUY",
            "order_type": "buy_stop",
            "entry": 100.0,
            "stop": 95.0,
            "target": 110.0,
        },
    }


def test_stale_feed_cannot_trigger_or_stop_locked_campaign(monkeypatch) -> None:
    engine = Dummy()
    engine._live_campaign = open_campaign()
    monkeypatch.setattr(lock.core, "utc_now", lambda: datetime(2026, 8, 21, 12, 10, tzinfo=timezone.utc))
    result = lock._advance_campaign(engine, engine._live_campaign, 111.0, allow_price_events=False)
    assert result["status"] == "pending"


def test_published_campaign_is_immune_to_later_learning_veto(monkeypatch) -> None:
    engine = Dummy()
    engine._live_campaign = open_campaign()
    engine._live_campaign_new_v28 = False
    state = {
        "learning_governor": {"decision": "veto"},
        "trade": {"action": "WAIT", "order_type": "none"},
        "setup": {"status": "WATCHING"},
    }
    engine._learning_governor_pending_state = state

    async def fake_calibration(_self, _signature):
        return {"active": True, "samples": 20, "posterior_accuracy": 0.4}

    monkeypatch.setattr(lock, "_original_calibration", fake_calibration)
    asyncio.run(lock._calibration_v28(engine, "family"))

    assert state["learning_governor"]["decision"] == "locked_campaign_continues"
    assert state["trade"]["action"] == "BUY STOP"
    assert state["trade"]["entry"] == 100.0
    assert state["setup"]["status"] == "IDEA LOCKED"


def test_new_candidate_remains_vetoable_before_publication(monkeypatch) -> None:
    engine = Dummy()
    engine._live_campaign = open_campaign()
    engine._live_campaign_new_v28 = True
    state = {
        "learning_governor": {"decision": "veto"},
        "trade": {"action": "WAIT", "order_type": "none"},
        "setup": {"status": "WATCHING"},
    }
    engine._learning_governor_pending_state = state

    async def fake_calibration(_self, _signature):
        return {"active": True, "samples": 20, "posterior_accuracy": 0.4}

    monkeypatch.setattr(lock, "_original_calibration", fake_calibration)
    asyncio.run(lock._calibration_v28(engine, "family"))

    assert state["learning_governor"]["decision"] == "veto"
    assert state["trade"]["action"] == "WAIT"
