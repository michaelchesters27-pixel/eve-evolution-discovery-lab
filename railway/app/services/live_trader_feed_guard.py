from __future__ import annotations

from app.services.live_trader import LiveTrader

# Twelve Data's XAU/USD feed on the configured plan is minute-stamped in production.
# A 30-second freshness window falsely marked a healthy socket stale for roughly
# half of every minute. Keep a full minute plus network/runtime tolerance.
FEED_FRESHNESS_SECONDS = 90.0

_original_runtime_status = LiveTrader.runtime_status


def _feed_is_fresh_guard(self: LiveTrader, max_age_seconds: float = FEED_FRESHNESS_SECONDS) -> bool:
    age = self._tick_age_seconds()
    return bool(self.connected and age is not None and age <= max_age_seconds)


def _runtime_status_guard(self: LiveTrader) -> dict:
    state = dict(_original_runtime_status(self))
    state["feed_freshness_seconds"] = FEED_FRESHNESS_SECONDS
    state["feed_freshness_policy"] = "minute-stamped Twelve Data feed + 30s tolerance"
    return state


LiveTrader._feed_is_fresh = _feed_is_fresh_guard  # type: ignore[method-assign]
LiveTrader.runtime_status = _runtime_status_guard  # type: ignore[method-assign]
