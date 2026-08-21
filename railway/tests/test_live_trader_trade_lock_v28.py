from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone

from app.services import live_trader as core
from app.services import live_trader_trade_lock_v28 as lock


class Dummy:
    symbol = "XAU/USD"
    _live_campaign_dirty = False
    _live_campaign = None


def campaign(*, status: str = "pending", side: str = "BUY", order_type: str = "buy_stop") -> dict:
    now = datetime(2026, 8, 21, 12, 0, tzinfo=timezone.utc)
    return {
        "version": lock.CAMPAIGN_VERSION,
        "id": "campaign-1",
        "symbol": "XAU/USD",
        "status": status,
        "side": side,
        "order_type": order_type,
        "entry": 100.0,
        "stop": 95.0 if side == "BUY" else 105.0,
        "target": 110.0 if side == "BUY" else 90.0,
        "risk_reward": 2.0,
        "confidence": 70,
        "reason": "test",
        "invalidation": "Cancel if invalidated.",
        "invalidation_price": 96.0 if side == "BUY" else 104.0,
        "created_at": now.isoformat(),
        "expires_at": (now + timedelta(hours=3)).isoformat(),
        "triggered_at": now.isoformat() if status == "active" else None,
        "completed_at": None,
        "result": None,
        "last_price": 99.0,
        "last_checked_at": now.isoformat(),
        "published_trade": {
            "action": "BUY STOP" if side == "BUY" else "SELL STOP",
            "side": side,
            "order_type": order_type,
            "entry": 100.0,
            "stop": 95.0 if side == "BUY" else 105.0,
            "target": 110.0 if side == "BUY" else 90.0,
        },
    }


def test_published_invalidation_price_is_used_instead_of_stop() -> None:
    trade = {
        "stop": 94.0,
        "invalidation": "Cancel the idea if price trades below 96.25 before triggering.",
    }
    assert lock._invalidation_price(trade) == 96.25


def test_pending_buy_stop_stays_locked_until_trigger(monkeypatch) -> None:
    engine = Dummy()
    fixed = datetime(2026, 8, 21, 12, 10, tzinfo=timezone.utc)
    monkeypatch.setattr(lock.core, "utc_now", lambda: fixed)
    item = campaign()

    result = lock._advance_campaign(engine, item, 99.0)

    assert result is item
    assert result["status"] == "pending"
    trade = lock._campaign_trade(result)
    assert trade["action"] == "BUY STOP"
    assert trade["entry"] == 100.0
    assert trade["stop"] == 95.0
    assert trade["target"] == 110.0
    assert trade["campaign_locked"] is True


def test_pending_buy_stop_triggers_then_follows_original_geometry(monkeypatch) -> None:
    engine = Dummy()
    monkeypatch.setattr(lock.core, "utc_now", lambda: datetime(2026, 8, 21, 12, 10, tzinfo=timezone.utc))
    item = campaign()

    result = lock._advance_campaign(engine, item, 100.2)

    assert result["status"] == "active"
    assert result["triggered_at"] is not None
    trade = lock._campaign_trade(result)
    assert trade["action"] == "BUY ACTIVE"
    assert (trade["entry"], trade["stop"], trade["target"]) == (100.0, 95.0, 110.0)


def test_active_trade_finishes_only_at_published_target_or_stop(monkeypatch) -> None:
    engine = Dummy()
    item = campaign(status="active")

    monkeypatch.setattr(lock.core, "utc_now", lambda: datetime(2026, 8, 21, 12, 20, tzinfo=timezone.utc))
    still_active = lock._advance_campaign(engine, item, 106.0)
    assert still_active["status"] == "active"

    monkeypatch.setattr(lock.core, "utc_now", lambda: datetime(2026, 8, 21, 12, 21, tzinfo=timezone.utc))
    won = lock._advance_campaign(engine, item, 110.1)
    assert won["status"] == "won"
    assert won["result"] == "WIN — TARGET HIT"


def test_active_trade_can_finish_as_loss(monkeypatch) -> None:
    engine = Dummy()
    item = campaign(status="active")
    monkeypatch.setattr(lock.core, "utc_now", lambda: datetime(2026, 8, 21, 12, 20, tzinfo=timezone.utc))

    lost = lock._advance_campaign(engine, item, 94.9)

    assert lost["status"] == "lost"
    assert lost["result"] == "LOSS — STOP HIT"


def test_pending_stop_order_invalidates_before_entry(monkeypatch) -> None:
    engine = Dummy()
    item = campaign()
    monkeypatch.setattr(lock.core, "utc_now", lambda: datetime(2026, 8, 21, 12, 20, tzinfo=timezone.utc))

    invalid = lock._advance_campaign(engine, item, 95.9)

    assert invalid["status"] == "invalidated"
    assert invalid["result"] == "CANCELLED — INVALID BEFORE ENTRY"


def test_limit_order_gap_through_entry_and_stop_is_a_triggered_loss_not_preentry_cancel(monkeypatch) -> None:
    engine = Dummy()
    item = campaign(order_type="buy_limit")
    item["published_trade"]["order_type"] = "buy_limit"
    item["published_trade"]["action"] = "BUY LIMIT"
    monkeypatch.setattr(lock.core, "utc_now", lambda: datetime(2026, 8, 21, 12, 20, tzinfo=timezone.utc))

    result = lock._advance_campaign(engine, item, 94.5)

    assert result["triggered_at"] is not None
    assert result["status"] == "lost"


def test_pending_campaign_expires_without_trigger(monkeypatch) -> None:
    engine = Dummy()
    item = campaign()
    monkeypatch.setattr(lock.core, "utc_now", lambda: datetime(2026, 8, 21, 15, 1, tzinfo=timezone.utc))

    result = lock._advance_campaign(engine, item, 99.0)

    assert result["status"] == "expired"
    assert result["result"] == "NO TRIGGER — SETUP EXPIRED"


def test_terminal_campaign_is_held_for_voice_then_releases(monkeypatch) -> None:
    engine = Dummy()
    item = campaign(status="won")
    item["completed_at"] = datetime(2026, 8, 21, 12, 30, tzinfo=timezone.utc).isoformat()
    item["result"] = "WIN — TARGET HIT"

    monkeypatch.setattr(lock.core, "utc_now", lambda: datetime(2026, 8, 21, 12, 30, 30, tzinfo=timezone.utc))
    assert lock._advance_campaign(engine, item, 110.0) is item

    monkeypatch.setattr(lock.core, "utc_now", lambda: datetime(2026, 8, 21, 12, 31, 1, tzinfo=timezone.utc))
    assert lock._advance_campaign(engine, item, 110.0) is None


def test_runtime_is_patched_to_one_trade_state_machine() -> None:
    assert core.LiveTrader._trade_idea is lock._trade_idea_v28
    assert core.LiveTrader.refresh_state is lock._refresh_state_v28
    assert core.LiveTrader._maybe_persist_state is lock._maybe_persist_state_v28
