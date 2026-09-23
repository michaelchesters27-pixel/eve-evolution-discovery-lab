from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from types import SimpleNamespace

from app.services import live_trader as core
from app.services import live_trader_red_folder_all_day_v37 as all_day
from app.services import live_trader_red_folder_news_confirmation_v36 as confirmation
from app.services import live_trader_red_folder_news_v35 as news
from app.services import live_trader_news_confirmation_workflow_v95 as workflow


def utc(year: int, month: int, day: int, hour: int, minute: int = 0) -> datetime:
    return datetime(year, month, day, hour, minute, tzinfo=timezone.utc)


def test_all_day_event_uses_full_uk_calendar_day_without_fake_release_time() -> None:
    row = all_day.build_all_day_event("XAU/USD", "2026-08-28", "Jackson Hole Symposium")
    event = all_day._decorate_event_v37(row)

    assert row["currency"] == "ALL"
    assert row["event_class"] == "all_day"
    assert event is not None
    assert event["all_day"] is True
    assert event["all_day_date"] == "2026-08-28"
    # 28 Aug 2026 is BST: UK midnight is 23:00 UTC on the prior date.
    assert event["blackout_start"] == "2026-08-27T23:00:00+00:00"
    assert event["blackout_end"] == "2026-08-28T23:00:00+00:00"


def test_all_day_event_blackout_is_active_for_entire_uk_day() -> None:
    row = all_day.build_all_day_event("XAU/USD", "2026-08-28", "Jackson Hole Symposium")

    before = news.news_status_from_rows([row], utc(2026, 8, 27, 22, 59))
    morning = news.news_status_from_rows([row], utc(2026, 8, 28, 7, 0))
    evening = news.news_status_from_rows([row], utc(2026, 8, 28, 22, 59))
    after = news.news_status_from_rows([row], utc(2026, 8, 28, 23, 0))

    assert before["status"] == "armed"
    assert morning["status"] == "blackout"
    assert evening["status"] == "blackout"
    assert after["status"] == "clear"


class FakeClient:
    def __init__(self, events: list[dict] | None = None) -> None:
        self.rpc_call = None
        self.events = list(events or [])

    async def rpc(self, function: str, payload: dict | None = None):
        assert function == all_day.BLACKOUT_WINDOW_RPC
        self.rpc_call = (function, dict(payload or {}))
        return {
            "version": all_day.BLACKOUT_WINDOW_VERSION,
            "complete": True,
            "source": all_day.BLACKOUT_WINDOW_SOURCE,
            "selection": all_day.BLACKOUT_WINDOW_SELECTION,
            "event_count": len(self.events),
            "events": list(self.events),
        }


class FakeTrader:
    symbol = "XAU/USD"

    def __init__(self, events: list[dict] | None = None) -> None:
        self.repo = SimpleNamespace(client=FakeClient(events))


def test_base_calendar_loader_uses_complete_server_side_window(monkeypatch) -> None:
    trader = FakeTrader()
    monkeypatch.setattr(all_day.core, "utc_now", lambda: utc(2026, 8, 23, 8, 0))

    result = asyncio.run(all_day._load_calendar_with_all(trader, force=True))

    assert trader.repo.client.rpc_call[0] == all_day.BLACKOUT_WINDOW_RPC
    assert result["available"] is True
    assert result["blackout_inventory_complete"] is True
    assert result["blackout_inventory_count"] == 0
    assert result["all_day_version"] == all_day.ALL_DAY_VERSION


def test_v36_uses_v37_base_calendar_loader() -> None:
    assert confirmation._current_calendar_loader is all_day._load_calendar_with_all
    assert news._decorate_event is all_day._decorate_event_v37
    assert core.LiveTrader.answer is workflow._answer_v95



def test_complete_blackout_loader_blocks_active_event_after_former_100_row_boundary(monkeypatch) -> None:
    now = utc(2026, 9, 22, 10, 0)
    expired = [
        {
            "event_id": f"expired-{index:03d}",
            "currency": "USD",
            "event_name": f"Expired event {index}",
            "scheduled_at": "2026-09-22T08:00:00+00:00",
            "event_class": "high",
            "pre_minutes": 1,
            "post_minutes": 1,
            "source": news.NEWS_SOURCE,
        }
        for index in range(100)
    ]
    active = {
        "event_id": "active-101",
        "currency": "USD",
        "event_name": "Active event after old cap",
        "scheduled_at": "2026-09-22T10:05:00+00:00",
        "event_class": "high",
        "pre_minutes": 30,
        "post_minutes": 15,
        "source": news.NEWS_SOURCE,
    }
    trader = FakeTrader(expired + [active])
    monkeypatch.setattr(all_day.core, "utc_now", lambda: now)

    result = asyncio.run(all_day._load_calendar_with_all(trader, force=True))

    assert result["event_count"] == 101
    assert result["blackout_inventory_count"] == 101
    assert result["active"] is True
    assert result["new_trade_blocked"] is True
    assert result["active_event_ids"] == ["active-101"]


def test_incomplete_blackout_inventory_fails_closed(monkeypatch) -> None:
    trader = FakeTrader()

    async def incomplete_rpc(_function: str, _payload: dict | None = None):
        return {
            "version": all_day.BLACKOUT_WINDOW_VERSION,
            "complete": False,
            "source": all_day.BLACKOUT_WINDOW_SOURCE,
            "selection": all_day.BLACKOUT_WINDOW_SELECTION,
            "event_count": 0,
            "events": [],
        }

    trader.repo.client.rpc = incomplete_rpc
    monkeypatch.setattr(all_day.core, "utc_now", lambda: utc(2026, 9, 22, 10, 0))

    result = asyncio.run(all_day._load_calendar_with_all(trader, force=True))

    assert result["available"] is False
    assert result["new_trade_blocked"] is True
    assert result["forward_learning_blocked"] is True



def test_malformed_timestamp_fails_closed_instead_of_being_silently_dropped(monkeypatch) -> None:
    valid = {
        "event_id": "valid-001",
        "currency": "USD",
        "event_name": "Valid event",
        "scheduled_at": "2026-09-23T15:30:00+00:00",
        "event_class": "high",
        "pre_minutes": 30,
        "post_minutes": 15,
        "source": news.NEWS_SOURCE,
    }
    malformed = {
        "event_id": "malformed-101",
        "currency": "USD",
        "event_name": "Malformed active event",
        "scheduled_at": "not-a-time",
        "event_class": "high",
        "pre_minutes": 30,
        "post_minutes": 15,
        "source": news.NEWS_SOURCE,
    }
    trader = FakeTrader([valid, malformed])
    monkeypatch.setattr(all_day.core, "utc_now", lambda: utc(2026, 9, 23, 15, 0))

    result = asyncio.run(all_day._load_calendar_with_all(trader, force=True))

    assert result["available"] is False
    assert result["new_trade_blocked"] is True
    assert result["forward_learning_blocked"] is True
    assert "invalid scheduled_at timestamp" in str(result["error"])


def test_missing_required_event_field_fails_closed(monkeypatch) -> None:
    malformed = {
        "event_id": "missing-name",
        "currency": "USD",
        "event_name": "",
        "scheduled_at": "2026-09-23T15:05:00+00:00",
        "event_class": "high",
        "pre_minutes": 30,
        "post_minutes": 15,
        "source": news.NEWS_SOURCE,
    }
    trader = FakeTrader([malformed])
    monkeypatch.setattr(all_day.core, "utc_now", lambda: utc(2026, 9, 23, 15, 0))

    result = asyncio.run(all_day._load_calendar_with_all(trader, force=True))

    assert result["available"] is False
    assert result["new_trade_blocked"] is True
    assert result["forward_learning_blocked"] is True


def test_all_day_event_returned_in_afternoon_stays_blocked(monkeypatch) -> None:
    event = all_day.build_all_day_event("XAU/USD", "2026-09-23", "All Day Safety Test")
    # On 23 Sep 2026 (BST), the storage anchor is 11:00 UTC. The old loader's
    # two-hour timestamp lookback at 15:00 UTC began at 13:00 and lost this row.
    assert event["scheduled_at"] == "2026-09-23T11:00:00+00:00"
    trader = FakeTrader([event])
    monkeypatch.setattr(all_day.core, "utc_now", lambda: utc(2026, 9, 23, 15, 0))

    result = asyncio.run(all_day._load_calendar_with_all(trader, force=True))

    assert result["available"] is True
    assert result["blackout_inventory_complete"] is True
    assert result["active"] is True
    assert result["new_trade_blocked"] is True
    assert result["forward_learning_blocked"] is True
    assert result["active_event_ids"] == [event["event_id"]]



def test_all_day_class_variants_are_canonicalised_before_evaluation(monkeypatch) -> None:
    now = utc(2026, 9, 23, 15, 0)
    base = all_day.build_all_day_event("XAU/USD", "2026-09-23", "Canonicalisation safety test")

    for raw_class in ("ALL_DAY", "all_day "):
        event = dict(base)
        event["event_id"] = f"variant-{raw_class.strip().lower()}"
        event["event_class"] = raw_class
        trader = FakeTrader([event])
        monkeypatch.setattr(all_day.core, "utc_now", lambda: now)

        result = asyncio.run(all_day._load_calendar_with_all(trader, force=True))

        assert result["available"] is True
        assert result["active"] is True
        assert result["new_trade_blocked"] is True
        assert result["forward_learning_blocked"] is True
        assert result["event_count"] == 1
        assert result["events"][0]["event_class"] == "all_day"
        assert result["events"][0]["all_day"] is True


def test_unsupported_event_class_fails_closed(monkeypatch) -> None:
    malformed = {
        "event_id": "unsupported-class",
        "currency": "USD",
        "event_name": "Unsupported class",
        "scheduled_at": "2026-09-23T15:05:00+00:00",
        "event_class": "nonsense",
        "pre_minutes": 30,
        "post_minutes": 15,
        "source": news.NEWS_SOURCE,
    }
    trader = FakeTrader([malformed])
    monkeypatch.setattr(all_day.core, "utc_now", lambda: utc(2026, 9, 23, 15, 0))

    result = asyncio.run(all_day._load_calendar_with_all(trader, force=True))

    assert result["available"] is False
    assert result["new_trade_blocked"] is True
    assert result["forward_learning_blocked"] is True
    assert "unsupported event_class" in str(result["error"])


def test_validator_returns_canonical_event_class_and_required_fields() -> None:
    raw = {
        "event_id": " canonical-id ",
        "currency": " all ",
        "event_name": "  All Day   Event  ",
        "scheduled_at": "2026-09-23T11:00:00+00:00",
        "event_class": " ALL_DAY ",
        "pre_minutes": 0.0,
        "post_minutes": 0.0,
        "source": " Forex Factory manual ",
    }

    clean = all_day._validate_blackout_row_v99(raw)

    assert clean["event_id"] == "canonical-id"
    assert clean["currency"] == "ALL"
    assert clean["event_name"] == "All Day Event"
    assert clean["event_class"] == "all_day"
    assert clean["scheduled_at"] == "2026-09-23T11:00:00+00:00"
    assert clean["pre_minutes"] == 0
    assert clean["post_minutes"] == 0
    assert clean["source"] == "Forex Factory manual"
