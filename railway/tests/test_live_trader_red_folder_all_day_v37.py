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
        assert function == "get_live_trader_news_window_v98"
        self.rpc_call = (function, dict(payload or {}))
        return {
            "version": all_day.BLACKOUT_WINDOW_VERSION,
            "complete": True,
            "source": "server_side_sql_aggregation",
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

    assert trader.repo.client.rpc_call[0] == "get_live_trader_news_window_v98"
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
            "event_count": 0,
            "events": [],
        }

    trader.repo.client.rpc = incomplete_rpc
    monkeypatch.setattr(all_day.core, "utc_now", lambda: utc(2026, 9, 22, 10, 0))

    result = asyncio.run(all_day._load_calendar_with_all(trader, force=True))

    assert result["available"] is False
    assert result["new_trade_blocked"] is True
    assert result["forward_learning_blocked"] is True
