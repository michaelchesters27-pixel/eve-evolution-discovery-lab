import asyncio
from types import SimpleNamespace

from app.services import live_trader_db_load_guard_v42 as guard


def test_intelligence_metrics_requests_are_singleflight() -> None:
    async def scenario() -> None:
        guard._METRICS_CACHE.clear()
        guard._METRICS_IN_FLIGHT.clear()
        original = guard._ORIGINAL_FETCH_METRICS
        calls = 0

        async def fake_fetch(client, symbol):
            nonlocal calls
            calls += 1
            await asyncio.sleep(0.02)
            return {"historical_scored": 123, "symbol": symbol}

        guard._ORIGINAL_FETCH_METRICS = fake_fetch
        try:
            client = object()
            results = await asyncio.gather(
                guard._singleflight_fetch_metrics(client, "XAU/USD"),
                guard._singleflight_fetch_metrics(client, "XAU/USD"),
                guard._singleflight_fetch_metrics(client, "XAU/USD"),
            )
            assert calls == 1
            assert all(item["historical_scored"] == 123 for item in results)
        finally:
            guard._ORIGINAL_FETCH_METRICS = original
            guard._METRICS_CACHE.clear()
            guard._METRICS_IN_FLIGHT.clear()

    asyncio.run(scenario())


def test_intelligence_metrics_cache_prevents_repeat_rpc() -> None:
    async def scenario() -> None:
        guard._METRICS_CACHE.clear()
        guard._METRICS_IN_FLIGHT.clear()
        original = guard._ORIGINAL_FETCH_METRICS
        calls = 0

        async def fake_fetch(client, symbol):
            nonlocal calls
            calls += 1
            return {"forward_scored": 22}

        guard._ORIGINAL_FETCH_METRICS = fake_fetch
        try:
            client = object()
            first = await guard._singleflight_fetch_metrics(client, "XAU/USD")
            second = await guard._singleflight_fetch_metrics(client, "XAU/USD")
            assert first == second
            assert calls == 1
        finally:
            guard._ORIGINAL_FETCH_METRICS = original
            guard._METRICS_CACHE.clear()
            guard._METRICS_IN_FLIGHT.clear()

    asyncio.run(scenario())


def test_learning_summary_is_cached_and_coalesced() -> None:
    async def scenario() -> None:
        original = guard._CURRENT_LEARNING_SUMMARY
        calls = 0

        async def fake_summary(self):
            nonlocal calls
            calls += 1
            await asyncio.sleep(0.02)
            return {"historical_learning": {"episodes_recorded": 34655}}

        guard._CURRENT_LEARNING_SUMMARY = fake_summary
        try:
            trader = SimpleNamespace()
            first, second = await asyncio.gather(
                guard._learning_summary_v42(trader),
                guard._learning_summary_v42(trader),
            )
            third = await guard._learning_summary_v42(trader)
            assert calls == 1
            assert first["database_load_guard"]["singleflight"] is True
            assert second == first
            assert third == first
        finally:
            guard._CURRENT_LEARNING_SUMMARY = original

    asyncio.run(scenario())
