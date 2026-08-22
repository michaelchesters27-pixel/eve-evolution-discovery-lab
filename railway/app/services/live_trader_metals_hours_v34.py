from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from app.services import live_trader_historical_learning_v29 as academy

METALS_HOURS_VERSION = "ic-markets-xau-rollover-guard-v2"
METALS_HOURS_POLICY = (
    "XAU/USD uses a conservative IC Markets metals-hours guard. EVE freezes live campaign management, "
    "forward-learning observations and historical decision anchors from 16:59 through 18:00 America/New_York "
    "each trading day, covering the broker/server rollover and published metals maintenance break. Friday remains "
    "closed after 16:59 ET and Sunday is treated as closed until 18:00 ET. This intentionally skips the brief "
    "post-rollover quote window before the metals maintenance break rather than treating it as normal liquidity."
)

ROLLOVER_START = (16, 59, 0)
ROLLOVER_END = (18, 0, 0)


def _clock(local: datetime) -> tuple[int, int, int]:
    return local.hour, local.minute, local.second


def broker_market_open_v34(at: datetime) -> bool:
    local = at.astimezone(academy.NY)
    weekday = local.weekday()  # Monday=0 ... Sunday=6
    clock = _clock(local)

    if weekday == 5:  # Saturday
        return False
    if weekday == 6:  # Sunday: do not use the short pre-maintenance quote window.
        return clock >= ROLLOVER_END
    if weekday == 4 and clock >= ROLLOVER_START:  # Friday close.
        return False
    if ROLLOVER_START <= clock < ROLLOVER_END:  # Mon-Thu daily metals maintenance/rollover.
        return False
    return True


def broker_market_open_through_v34(observed: datetime, horizon_minutes: int) -> bool:
    """Require the entire causal horizon to stay within tradable XAU/USD minutes."""
    horizon = observed + timedelta(minutes=max(1, int(horizon_minutes)))
    cursor = observed
    while cursor <= horizon:
        if not broker_market_open_v34(cursor):
            return False
        cursor += timedelta(minutes=1)
    return True


def market_hours_payload_v34(at: datetime) -> dict[str, Any]:
    local = at.astimezone(academy.NY)
    return {
        "version": METALS_HOURS_VERSION,
        "tradable": broker_market_open_v34(at),
        "broker_reference": "IC Markets",
        "instrument": "XAU/USD",
        "timezone": "America/New_York",
        "local_time": local.isoformat(),
        "weekly_open_conservative": "Sunday 18:00 ET",
        "weekly_close_conservative": "Friday 16:59 ET",
        "daily_rollover_freeze": "16:59-18:00 ET",
        "policy": METALS_HOURS_POLICY,
    }


# Patch the shared market-hours functions rather than duplicating the Live Trader
# runtime. Existing trade-lock, learning, Historical Academy and intelligence code
# all resolve these module globals at call time, so one guard protects every path.
academy.MARKET_HOURS_VERSION = METALS_HOURS_VERSION
academy.BROKER_HOURS_POLICY = METALS_HOURS_POLICY
academy.broker_market_open = broker_market_open_v34
academy.broker_market_open_through = broker_market_open_through_v34
academy._market_hours_payload = market_hours_payload_v34
