from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from types import SimpleNamespace

from app.services import live_trader as core
from app.services import live_trader_red_folder_all_day_v37 as all_day
from app.services import live_trader_red_folder_news_confirmation_v36 as confirmation
from app.services import live_trader_red_folder_news_v35 as news


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
    def __init__(self) -> None:
        self.params = None

    async def get(self, table: str, *, params: dict | None = None, **_kwargs):
        assert table == "live_trader_news_events"
        self.params = params
        return []


class FakeTrader:
    symbol = "XAU/USD"

    def __init__(self) -> None:
        self.repo = SimpleNamespace(client=FakeClient())


def test_base_calendar_loader_reads_usd_and_all_scope_events(monkeypatch) -> None:
    trader = FakeTrader()
    monkeypatch.setattr(all_day.core, "utc_now", lambda: utc(2026, 8, 23, 8, 0))

    result = asyncio.run(all_day._load_calendar_with_all(trader, force=True))

    assert trader.repo.client.params["currency"] == "in.(USD,ALL)"
    assert result["available"] is True
    assert result["all_day_version"] == all_day.ALL_DAY_VERSION


def test_v36_uses_v37_base_calendar_loader() -> None:
    assert confirmation._current_calendar_loader is all_day._load_calendar_with_all
    assert news._decorate_event is all_day._decorate_event_v37
    assert core.LiveTrader.answer is all_day._answer_v37
