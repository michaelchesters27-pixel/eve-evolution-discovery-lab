from __future__ import annotations

from typing import Any

CONTEXT_CONTRACT_VERSION = "eve-live-context-contract-v1"
LIVE_CONTEXT_VERSION = "eve-live-context-freshness-v101"
SOURCE_NAME = "source_market_candles_read_only_completed_m5_overlay"
MAX_CONTEXT_LAG_MINUTES = 10.0
SOURCE_POLL_SECONDS = 30.0
MAX_OVERLAY_M5_ROWS = 1000


def definition() -> dict[str, Any]:
    return {
        "contract_version": CONTEXT_CONTRACT_VERSION,
        "runtime_version": LIVE_CONTEXT_VERSION,
        "source": SOURCE_NAME,
        "completed_m5_only": True,
        "persistent_research_fabric_required_for_live_freshness": False,
        "ephemeral_overlay_only": True,
        "max_context_lag_minutes": MAX_CONTEXT_LAG_MINUTES,
        "source_poll_seconds": SOURCE_POLL_SECONDS,
        "max_overlay_m5_rows": MAX_OVERLAY_M5_ROWS,
        "fail_closed_on_stale_live_context": True,
        "trading_rules_relaxed": False,
        "research_history_reduced": False,
    }
