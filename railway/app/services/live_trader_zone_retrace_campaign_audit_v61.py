from __future__ import annotations

from typing import Any

from app.services import live_trader as core
from app.services import live_trader_trade_lock_v28 as lock
from app.services import live_trader_zone_retrace_specialist_v58 as v58

AUDIT_VERSION = "eve-live-zone-retrace-campaign-audit-v61"
_current_new_campaign = lock._new_campaign
_current_runtime_status = core.LiveTrader.runtime_status

_SPECIALIST_FIELDS = (
    "strategy_key",
    "specialist_version",
    "execution_class",
    "entry_policy",
    "source_zone",
)


def _new_campaign_v61(self: core.LiveTrader, trade: dict[str, Any], price: float) -> dict[str, Any]:
    campaign = dict(_current_new_campaign(self, trade, price) or {})
    published = dict(campaign.get("published_trade") or {})

    if str(trade.get("strategy_key") or "") == v58.STRATEGY_KEY:
        for key in _SPECIALIST_FIELDS:
            if trade.get(key) is not None:
                campaign[key] = trade.get(key)
                published[key] = trade.get(key)
        campaign["specialist_audit_version"] = AUDIT_VERSION
        campaign["specialist_trade"] = True
        published["specialist_audit_version"] = AUDIT_VERSION
        published["specialist_trade"] = True

    campaign["published_trade"] = published
    return campaign


def _runtime_status_v61(self: core.LiveTrader) -> dict[str, Any]:
    state = dict(_current_runtime_status(self))
    state.update(
        {
            "zone_retrace_campaign_audit_version": AUDIT_VERSION,
            "zone_retrace_campaign_metadata_preserved": True,
            "zone_retrace_campaign_strategy_key": v58.STRATEGY_KEY,
            "zone_retrace_campaign_execution_class": "zone_retrace_confirmation",
        }
    )
    return state


# v28 creates campaigns through the module-global function, so this wraps the real
# live creation point while preserving v49's source-zone binding and target cap.
lock._new_campaign = _new_campaign_v61
core.LiveTrader.runtime_status = _runtime_status_v61  # type: ignore[method-assign]
