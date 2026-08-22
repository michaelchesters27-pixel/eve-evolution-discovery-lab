from __future__ import annotations

import asyncio
from typing import Any

from app.services import live_trader as core
from app.services import live_trader_historical_learning_v29 as academy
from app.services.repository import SourceRepository

RUNTIME_VERSION = "eve-live-historical-runtime-v1"
_current_run_forever = core.LiveTrader.run_forever
_current_refresh_state = core.LiveTrader.refresh_state
_current_runtime_status = core.LiveTrader.runtime_status


async def _refresh_state_v30(self: core.LiveTrader, *, force_rows: bool = False) -> dict[str, Any]:
    state = await _current_refresh_state(self, force_rows=force_rows)
    feed = dict(state.get("feed") or {})
    if str(feed.get("status") or "").lower() == "market_closed":
        # The Twelve Data transport can remain healthy while the broker market is
        # closed. Keep transport health separate from tradability so the browser
        # does not misannounce a normal weekend closure as a stale/disconnected feed.
        feed["connected"] = bool(feed.get("provider_connected") or feed.get("socket_connected"))
        feed["tradable"] = False
        state["feed"] = feed
        self._latest_state = state
    return state


async def _run_forever_v30(self: core.LiveTrader) -> None:
    learner = getattr(self, "_historical_academy_v30", None)
    if learner is None:
        learner = academy.LiveTraderHistoricalLearner(
            self.settings,
            SourceRepository(self.settings),
            self.repo,
        )
        self._historical_academy_v30 = learner
    historical_task = asyncio.create_task(
        learner.run_forever(),
        name="eve-live-trader-historical-academy",
    )
    try:
        await _current_run_forever(self)
    finally:
        await learner.stop()
        historical_task.cancel()
        try:
            await historical_task
        except asyncio.CancelledError:
            pass


def _runtime_status_v30(self: core.LiveTrader) -> dict[str, Any]:
    status = dict(_current_runtime_status(self))
    learner = getattr(self, "_historical_academy_v30", None)
    status["historical_runtime_version"] = RUNTIME_VERSION
    status["historical_academy"] = learner.runtime_status() if learner is not None else {
        "version": academy.ACADEMY_VERSION,
        "enabled": True,
        "running": False,
        "status": "starting",
    }
    return status


core.LiveTrader.refresh_state = _refresh_state_v30  # type: ignore[method-assign]
core.LiveTrader.run_forever = _run_forever_v30  # type: ignore[method-assign]
core.LiveTrader.runtime_status = _runtime_status_v30  # type: ignore[method-assign]
