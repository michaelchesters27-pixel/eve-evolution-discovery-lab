from __future__ import annotations

import asyncio
from datetime import datetime
from typing import Any

from app.services import live_trader as core
from app.services import live_trader_intelligence_indicator_v33 as intelligence

GUARD_VERSION = "eve-live-db-load-guard-v1"
LEARNING_SUMMARY_CACHE_SECONDS = 30
METRICS_CACHE_SECONDS = 60
METRICS_STALE_FALLBACK_SECONDS = 600

# Capture the fully wrapped learning summary after v41 and the original v33
# intelligence loader. This module is imported last from app.__init__.
_CURRENT_LEARNING_SUMMARY = core.LiveTrader.learning_summary
_ORIGINAL_FETCH_METRICS = intelligence._fetch_metrics

# Process-local only. Railway runs one Live Trader replica; these structures are
# deliberately small and prevent multiple browser tabs/background jobs from
# launching the same expensive Supabase intelligence aggregate concurrently.
_METRICS_CACHE: dict[tuple[int, str], tuple[datetime, dict[str, Any]]] = {}
_METRICS_IN_FLIGHT: dict[tuple[int, str], asyncio.Task[dict[str, Any]]] = {}


def _age_seconds(stamp: datetime | None, now: datetime) -> float:
    if not isinstance(stamp, datetime):
        return float("inf")
    return max(0.0, (now - stamp).total_seconds())


async def _singleflight_fetch_metrics(client: Any, symbol: str) -> dict[str, Any]:
    """Return intelligence metrics without overlapping identical database scans.

    The v33 intelligence RPC is intentionally evidence-heavy. Browser refreshes,
    Academy snapshots and multiple tabs can all request it at once. One shared
    in-flight task per client/symbol is authoritative; followers await that task
    instead of starting another Supabase statement. A short successful-result
    cache keeps presentation traffic away from the database between updates.
    """

    key = (id(client), str(symbol))
    now = core.utc_now()
    cached = _METRICS_CACHE.get(key)
    if cached and _age_seconds(cached[0], now) < METRICS_CACHE_SECONDS:
        return dict(cached[1])

    task = _METRICS_IN_FLIGHT.get(key)
    if task is None or task.done():
        async def load() -> dict[str, Any]:
            result = await _ORIGINAL_FETCH_METRICS(client, symbol)
            return dict(result)

        task = asyncio.create_task(load(), name=f"eve-intelligence-metrics-{str(symbol).replace('/', '-')}")
        _METRICS_IN_FLIGHT[key] = task

    try:
        result = dict(await asyncio.shield(task))
    except Exception:
        # A brief Supabase slowdown must not turn a healthy Live Trader display
        # into a thundering-herd retry loop. Recent verified metrics are safe for
        # presentation only; live trading decisions do not consume this index.
        cached = _METRICS_CACHE.get(key)
        if cached and _age_seconds(cached[0], core.utc_now()) < METRICS_STALE_FALLBACK_SECONDS:
            return dict(cached[1])
        raise
    else:
        _METRICS_CACHE[key] = (core.utc_now(), dict(result))
        return result
    finally:
        current = _METRICS_IN_FLIGHT.get(key)
        if current is task and task.done():
            _METRICS_IN_FLIGHT.pop(key, None)


async def _build_learning_summary(self: core.LiveTrader) -> dict[str, Any]:
    summary = dict(await _CURRENT_LEARNING_SUMMARY(self))
    summary["database_load_guard"] = {
        "version": GUARD_VERSION,
        "learning_summary_cache_seconds": LEARNING_SUMMARY_CACHE_SECONDS,
        "intelligence_metrics_cache_seconds": METRICS_CACHE_SECONDS,
        "singleflight": True,
    }
    return summary


async def _learning_summary_v42(self: core.LiveTrader) -> dict[str, Any]:
    """Cache/coalesce the operator learning summary without slowing live state.

    `/api/live-trader` remains independent and can refresh every five seconds.
    The heavier `/api/live-trader/learning` response is presentation data, so a
    30-second cache is sufficient while protecting Supabase and the execution
    revalidator from dashboard-induced contention.
    """

    now = core.utc_now()
    cached_at = getattr(self, "_learning_summary_cache_at_v42", None)
    cached = getattr(self, "_learning_summary_cache_v42", None)
    if isinstance(cached, dict) and _age_seconds(cached_at, now) < LEARNING_SUMMARY_CACHE_SECONDS:
        return dict(cached)

    task = getattr(self, "_learning_summary_task_v42", None)
    if not isinstance(task, asyncio.Task) or task.done():
        task = asyncio.create_task(_build_learning_summary(self), name="eve-live-learning-summary")
        self._learning_summary_task_v42 = task

    try:
        result = dict(await asyncio.shield(task))
    except Exception:
        # If the database has a transient wobble, a recently verified summary is
        # preferable to multiplying retries. This summary is display-only and
        # cannot override closed-safe execution controls.
        cached = getattr(self, "_learning_summary_cache_v42", None)
        cached_at = getattr(self, "_learning_summary_cache_at_v42", None)
        if isinstance(cached, dict) and _age_seconds(cached_at, core.utc_now()) < METRICS_STALE_FALLBACK_SECONDS:
            fallback = dict(cached)
            fallback["database_load_guard"] = {
                **dict(fallback.get("database_load_guard") or {}),
                "stale_fallback": True,
            }
            return fallback
        raise
    else:
        self._learning_summary_cache_at_v42 = core.utc_now()
        self._learning_summary_cache_v42 = dict(result)
        return result
    finally:
        current = getattr(self, "_learning_summary_task_v42", None)
        if current is task and task.done():
            self._learning_summary_task_v42 = None


# Patch the v33 module global used by both Live Trader intelligence summaries and
# the Historical Academy's 15-minute snapshot. This gives both callers the same
# single-flight/cache contract.
intelligence._fetch_metrics = _singleflight_fetch_metrics

# Patch only the presentation summary. The live snapshot/trade engine remains on
# its existing fast cadence and all execution/learning semantics stay unchanged.
core.LiveTrader.learning_summary = _learning_summary_v42  # type: ignore[method-assign]
