from __future__ import annotations

import hashlib

from app.services import live_trader_learning_v2 as v2

# v2.1 keeps the v2 family model, scoring, shrinkage and execution-path learning,
# but tightens what is allowed to count as an independent market episode.
LEARNING_VERSION = "eve-live-learning-v2.1"
EPISODE_POLICY = "one setup family sample per symbol + UTC trading day + session"


def episode_key(state: dict) -> str:
    """Stable market-episode identity that cannot change because a zone ID moved.

    Exact zone identities deliberately do not participate. A matching family can
    contribute at most once in Asia/London/New York/off-session on a given UTC
    trading day. This prevents correlated snapshots from the same move inflating
    EVE's independent evidence count.
    """
    as_of = str(state.get("as_of") or "")
    day = as_of[:10] if len(as_of) >= 10 else v2.utc_now().date().isoformat()
    symbol = str(state.get("symbol") or "XAU/USD")
    session = str((state.get("market") or {}).get("session") or "unknown")
    raw = "|".join([symbol, day, session])
    return hashlib.sha1(raw.encode()).hexdigest()[:24]


# The v2 methods look these names up from their module globals at runtime. Change
# only the learning-version namespace and episode identity; all v2 family,
# calibration, scoring and conservative trade-resolution logic remains intact.
v2.LEARNING_VERSION = LEARNING_VERSION
v2.episode_key = episode_key

# Expose the stricter policy in runtime diagnostics without replacing the v2
# runtime implementation that is already installed on LiveTrader.
_original_runtime_status = v2.LiveTrader.runtime_status


def _runtime_status_v21(self: v2.LiveTrader) -> dict:
    state = dict(_original_runtime_status(self))
    state["learning_version"] = LEARNING_VERSION
    state["learning_episode_policy"] = EPISODE_POLICY
    return state


v2.LiveTrader.runtime_status = _runtime_status_v21  # type: ignore[method-assign]
