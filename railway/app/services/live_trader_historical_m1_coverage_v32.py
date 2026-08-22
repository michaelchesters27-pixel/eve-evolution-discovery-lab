from __future__ import annotations

from datetime import timedelta
from typing import Any

from app.services import live_trader as core
from app.services import live_trader_historical_learning_v29 as academy

COVERAGE_VERSION = "eve-live-historical-m1-coverage-v1"
_original_fetch_window = academy.LiveTraderHistoricalLearner._fetch_window
_original_runtime_status = academy.LiveTraderHistoricalLearner.runtime_status


async def _m1_coverage_start(self: academy.LiveTraderHistoricalLearner):
    cached = getattr(self, "_historical_m1_coverage_start_v32", None)
    if cached is not None:
        return cached
    rows = await self.source.client.get(
        "market_candles",
        params={
            "select": "candle_time",
            "symbol": f"eq.{self.symbol}",
            "interval": "eq.1min",
            "order": "candle_time.asc",
            "limit": "1",
        },
    )
    start = academy._parse_time((rows[0] or {}).get("candle_time")) if rows else None
    self._historical_m1_coverage_start_v32 = start
    return start


async def _fetch_window_v32(
    self: academy.LiveTraderHistoricalLearner,
    cursor: str | None,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    coverage_start = await _m1_coverage_start(self)
    parsed_cursor = academy._parse_time(cursor)
    if coverage_start is not None and (parsed_cursor is None or parsed_cursor < coverage_start):
        # Start just before the first M1 source bar. The worker still requires an
        # hourly decision anchor and a complete future path, so the first episode
        # that can actually teach EVE will naturally be the first clean hour after
        # M1 coverage begins.
        cursor = (coverage_start - timedelta(minutes=5)).isoformat()
        self._historical_coverage_jump_v32 = True
    return await _original_fetch_window(self, cursor)


def _runtime_status_v32(self: academy.LiveTraderHistoricalLearner) -> dict[str, Any]:
    status = dict(_original_runtime_status(self))
    start = getattr(self, "_historical_m1_coverage_start_v32", None)
    status.update(
        {
            "m1_coverage_version": COVERAGE_VERSION,
            "m1_coverage_start": start.isoformat() if start is not None else None,
            "coverage_jump_applied": bool(getattr(self, "_historical_coverage_jump_v32", False)),
        }
    )
    return status


academy.LiveTraderHistoricalLearner._m1_coverage_start = _m1_coverage_start  # type: ignore[attr-defined]
academy.LiveTraderHistoricalLearner._fetch_window = _fetch_window_v32  # type: ignore[method-assign]
academy.LiveTraderHistoricalLearner.runtime_status = _runtime_status_v32  # type: ignore[method-assign]
