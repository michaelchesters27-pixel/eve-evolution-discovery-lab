from __future__ import annotations

"""Compatibility surface for the P0 research-memory guard.

Small synthetic/test datasets intentionally expose the historical ``obs_*``
fields because those fields are useful for causal-semantics regression tests and
operator debugging. The production six-year fabric must not pay that per-row
heap cost.

This wrapper therefore keeps the old expanded representation only for small
lists. Large research lists use the compact `_eve_obs` representation installed
by ``memory_guard_v1``.
"""

from typing import Any, Iterable

from app.services import backtest_v3 as research
from app.services import memory_guard_v1 as guard

MEMORY_DEBUG_COMPAT_LIMIT = 4096
MEMORY_COMPAT_VERSION = "eve-research-memory-debug-compat-v1"


def bounded_enrich_market_observations(rows: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    if isinstance(rows, list) and len(rows) <= MEMORY_DEBUG_COMPAT_LIMIT:
        return guard._ORIGINAL_ENRICH(rows)
    return guard.compact_enrich_market_observations(rows)


research.enrich_market_observations = bounded_enrich_market_observations
