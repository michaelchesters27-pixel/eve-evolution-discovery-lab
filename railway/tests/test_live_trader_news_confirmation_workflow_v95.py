from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from app.services import live_trader_news_confirmation_workflow_v95 as v95


def utc(year: int, month: int, day: int, hour: int = 0, minute: int = 0) -> datetime:
    return datetime(year, month, day, hour, minute, tzinfo=timezone.utc)


def base_status() -> dict:
    return {
        "status": "clear",
        "available": True,
        "new_trade_blocked": False,
        "forward_learning_blocked": False,
        "events": [],
    }


def inventory_row(count: int = 2) -> dict:
    items = [
        {
            "event_id": f"evt-{index}",
            "currency": "USD",
            "event_name": f"Event {index}",
            "scheduled_at": f"2026-09-{22 + index:02d}T12:30:00+00:00",
            "event_class": "high",
            "pre_minutes": 30,
            "post_minutes": 15,
            "source": "Forex Factory manual",
        }
        for index in range(count)
    ]
    return {
        "week_start": "2026-09-20",
        "_current_event_count": count,
        "_current_event_digest": v95._inventory_digest(items),
        "_current_event_ids": [item["event_id"] for item in items],
        "_current_inventory": items,
    }


def test_missing_week_is_explicitly_closed_safe() -> None:
    row = inventory_row(2)
    result = v95._apply_confirmation_v95(base_status(), row, utc(2026, 9, 22, 10))
    assert result["week_confirmed"] is False
    assert result["week_confirmation_state"] == "missing"
    assert result["status"] == "week_unconfirmed"
    assert result["new_trade_blocked"] is True
    assert result["forward_learning_blocked"] is True
    assert result["confirmation_action_required"] is True
    assert result["current_week_event_count"] == 2


def test_matching_explicit_inventory_confirmation_is_valid() -> None:
    row = inventory_row(2)
    row.update(
        {
            "confirmed_at": "2026-09-22T10:00:00+00:00",
            "calendar_checked_at": "2026-09-22T10:00:00+00:00",
            "confirmation_version": v95.VERSION,
            "confirmation_method": v95.CONFIRMATION_METHOD,
            "confirmed_event_count": 2,
            "confirmed_event_digest": row["_current_event_digest"],
            "source_reference": "Forex Factory checked manually",
        }
    )
    result = v95._apply_confirmation_v95(base_status(), row, utc(2026, 9, 22, 10))
    assert result["week_confirmed"] is True
    assert result["week_confirmation_state"] == "confirmed_current_inventory"
    assert result["new_trade_blocked"] is False
    assert result["confirmation_action_required"] is False


def test_event_change_after_confirmation_invalidates_week() -> None:
    row = inventory_row(3)
    row.update(
        {
            "confirmed_at": "2026-09-22T10:00:00+00:00",
            "calendar_checked_at": "2026-09-22T10:00:00+00:00",
            "confirmation_version": v95.VERSION,
            "confirmation_method": v95.CONFIRMATION_METHOD,
            "confirmed_event_count": 2,
            "confirmed_event_digest": "old-digest",
            "source_reference": "Forex Factory checked manually",
        }
    )
    result = v95._apply_confirmation_v95(base_status(), row, utc(2026, 9, 22, 10))
    assert result["week_confirmed"] is False
    assert result["week_confirmation_state"] == "calendar_changed_since_confirmation"
    assert result["status"] == "week_confirmation_stale"
    assert result["block_reason"] == "weekly_calendar_changed_since_confirmation"
    assert result["new_trade_blocked"] is True


def test_legacy_confirmation_requires_recheck() -> None:
    row = inventory_row(0)
    row.update({"confirmed_at": "2026-09-22T10:00:00+00:00"})
    result = v95._apply_confirmation_v95(base_status(), row, utc(2026, 9, 22, 10))
    assert result["week_confirmed"] is False
    assert result["week_confirmation_state"] == "legacy_confirmation_requires_recheck"
    assert result["block_reason"] == "weekly_confirmation_protocol_upgrade_required"


class FakeClient:
    def __init__(self, events: list[dict]) -> None:
        self.events = events
        self.upserts: list[tuple[str, dict, str]] = []

    async def get(self, table: str, *, params: dict | None = None, **_kwargs):
        if table == "live_trader_news_events":
            return list(self.events)
        if table == "live_trader_news_weeks":
            return []
        raise AssertionError(table)

    async def upsert(self, table: str, payload: dict, *, on_conflict: str, return_rows: bool = False):
        self.upserts.append((table, dict(payload), on_conflict))
        return []


class FakeTrader:
    symbol = "XAU/USD"

    def __init__(self, events: list[dict]) -> None:
        self.repo = SimpleNamespace(client=FakeClient(events))
        self._news_week_cache_at_v95 = None
        self._news_week_cache_at_v36 = None
        self._news_calendar_cache_at_v35 = None
        self._news_calendar_cache_at_v37 = None


def test_confirmation_requires_explicit_attestation() -> None:
    trader = FakeTrader([])
    with pytest.raises(ValueError, match="explicit attestation"):
        asyncio.run(v95._confirm_current_week_v95(trader, expected_event_count=0, source_reference="Forex Factory"))


def test_confirmation_rejects_event_count_mismatch(monkeypatch) -> None:
    event = {
        "event_id": "evt-1",
        "currency": "USD",
        "event_name": "CPI",
        "scheduled_at": "2026-09-23T12:30:00+00:00",
        "event_class": "major",
        "pre_minutes": 45,
        "post_minutes": 30,
        "source": "Forex Factory manual",
        "enabled": True,
    }
    trader = FakeTrader([event])
    monkeypatch.setattr(v95.core, "utc_now", lambda: utc(2026, 9, 22, 10))
    with pytest.raises(ValueError, match="attested to 0 events"):
        asyncio.run(
            v95._confirm_current_week_v95(
                trader,
                calendar_checked=True,
                expected_event_count=0,
                source_reference="Forex Factory checked manually",
            )
        )


def test_bare_legacy_confirmation_command_cannot_auto_confirm() -> None:
    trader = FakeTrader([])

    async def fake_load(_self, *, force: bool = False):
        return {
            **base_status(),
            "week_start": "2026-09-20",
            "week_confirmed": False,
            "current_week_event_count": 0,
        }

    original = v95.news._load_calendar
    v95.news._load_calendar = fake_load
    try:
        result = asyncio.run(v95._answer_v95(trader, "__EVE_NEWS_CONFIRM_WEEK__"))
    finally:
        v95.news._load_calendar = original
    assert result["ok"] is False
    assert "explicit" in result["answer"].lower()
