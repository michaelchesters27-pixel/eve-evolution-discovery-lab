from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from types import SimpleNamespace

from app.services import live_trader_historical_m1_coverage_v32 as coverage


class SourceClient:
    async def get(self, table: str, *, params: dict):
        assert table == "market_candles"
        assert params["interval"] == "eq.1min"
        return [{"candle_time": "2020-04-06T13:16:00+00:00"}]


class Dummy:
    symbol = "XAU/USD"
    source = SimpleNamespace(client=SourceClient())


def test_discovers_first_source_m1_timestamp() -> None:
    item = Dummy()
    start = asyncio.run(coverage._m1_coverage_start(item))
    assert start == datetime(2020, 4, 6, 13, 16, tzinfo=timezone.utc)


def test_pre_m1_cursor_jumps_to_coverage_boundary(monkeypatch) -> None:
    item = Dummy()
    captured = {}

    async def fake_fetch(_self, cursor):
        captured["cursor"] = cursor
        return [], []

    monkeypatch.setattr(coverage, "_original_fetch_window", fake_fetch)
    asyncio.run(coverage._fetch_window_v32(item, "2020-03-19T01:55:00+00:00"))

    assert captured["cursor"] == "2020-04-06T13:11:00+00:00"
    assert item._historical_coverage_jump_v32 is True


def test_cursor_after_m1_coverage_is_not_rewound(monkeypatch) -> None:
    item = Dummy()
    captured = {}

    async def fake_fetch(_self, cursor):
        captured["cursor"] = cursor
        return [], []

    monkeypatch.setattr(coverage, "_original_fetch_window", fake_fetch)
    cursor = "2020-04-07T14:00:00+00:00"
    asyncio.run(coverage._fetch_window_v32(item, cursor))

    assert captured["cursor"] == cursor
