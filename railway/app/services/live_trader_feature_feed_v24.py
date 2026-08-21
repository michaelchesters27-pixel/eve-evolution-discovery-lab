from __future__ import annotations

from datetime import timedelta
from typing import Any

from app.services import live_trader as core

LIVE_FEATURE_SELECT = (
    "candle_time,open,high,low,close,atr_14,session,regime,direction,"
    "return_12_pct,return_48_pct,trend_12_atr,trend_48_atr,compression_ratio,"
    "mtf_context,outcome_complete"
)


async def _load_rows_v24(self: core.LiveTrader, force: bool = False) -> list[dict[str, Any]]:
    now = core.utc_now()
    if (
        not force
        and self._rows
        and self._rows_loaded_at is not None
        and now - self._rows_loaded_at < timedelta(seconds=45)
    ):
        return self._rows
    rows = await self.repo.client.get(
        "m5_research_snapshots",
        params={
            "select": LIVE_FEATURE_SELECT,
            "symbol": f"eq.{self.symbol}",
            "order": "candle_time.desc",
            "limit": "720",
        },
    )
    rows.reverse()
    self._rows = rows
    self._rows_loaded_at = now
    return rows


core.LiveTrader._load_rows = _load_rows_v24  # type: ignore[method-assign]
