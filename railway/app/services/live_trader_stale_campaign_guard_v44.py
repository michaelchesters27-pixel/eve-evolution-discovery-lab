from __future__ import annotations

from typing import Any

from app.services import live_trader as core
from app.services import live_trader_trade_lock_v28 as v28

GUARD_VERSION = "eve-live-stale-campaign-guard-v1"
STALE_RESULT_PREFIX = "CANCELLED — STALE CRITICAL TIMEFRAME BEFORE ENTRY"

_original_trade_idea = core.LiveTrader._trade_idea
_original_runtime_status = core.LiveTrader.runtime_status


def _data_quality_block(bias: dict[str, Any] | None) -> tuple[bool, list[str]]:
    if not isinstance(bias, dict):
        return False, []
    quality = dict(bias.get("data_quality") or {})
    critical = [str(value) for value in (quality.get("critical_stale") or []) if value]
    blocked = bool(quality.get("trade_bias_blocked")) or bool(critical)
    return blocked, critical


def _quality_reason(critical: list[str]) -> str:
    labels = ", ".join(critical) if critical else "a critical higher timeframe"
    return (
        f"Pending idea cancelled before entry because EVE detected stale critical timeframe data ({labels}). "
        "EVE will wait for fresh closed-candle context before publishing another idea."
    )


def _cancel_pending_for_stale_bias(
    self: core.LiveTrader,
    campaign: dict[str, Any],
    price: float,
    critical: list[str],
) -> dict[str, Any]:
    now = core.utc_now()
    labels = ",".join(critical) if critical else "critical_htf"
    result = f"{STALE_RESULT_PREFIX} — {labels}"
    campaign = v28._complete(campaign, "invalidated", result, price, now)
    campaign["data_quality_invalidation"] = {
        "version": GUARD_VERSION,
        "reason": "stale_critical_timeframe",
        "critical_stale": list(critical),
        "cancelled_before_entry": True,
        "cancelled_at": now.isoformat(),
    }
    self._live_campaign = campaign
    self._live_campaign_dirty = True
    return campaign


def _cancelled_display(campaign: dict[str, Any], critical: list[str]) -> tuple[dict[str, Any], dict[str, Any]]:
    setup = {
        "status": "IDEA CANCELLED",
        "reason": _quality_reason(critical),
    }
    trade = v28._campaign_trade(campaign)
    trade.update(
        {
            "action": "CANCEL — STALE DATA",
            "order_type": "none",
            "reason": _quality_reason(critical),
            "campaign_locked": False,
        }
    )
    return setup, trade


def _active_warning(
    setup: dict[str, Any],
    trade: dict[str, Any],
    critical: list[str],
) -> tuple[dict[str, Any], dict[str, Any]]:
    labels = ", ".join(critical) if critical else "critical higher-timeframe data"
    warning = (
        f"Data warning: {labels} is stale, but this trade already triggered. "
        "EVE will not rewrite an active trade; the original stop and target remain locked."
    )
    setup = dict(setup or {})
    trade = dict(trade or {})
    setup["data_quality_warning"] = warning
    setup["reason"] = f"{setup.get('reason') or ''} {warning}".strip()
    trade["data_quality_warning"] = warning
    return setup, trade


def _trade_idea_v44(
    self: core.LiveTrader,
    price: float,
    atr: float,
    bias: dict[str, Any],
    zones: dict[str, list[dict[str, Any]]],
    liquidity: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, Any]]:
    blocked, critical = _data_quality_block(bias)
    campaign = getattr(self, "_live_campaign", None)
    status = str((campaign or {}).get("status") or "").lower() if isinstance(campaign, dict) else ""

    if blocked and isinstance(campaign, dict) and status == "pending":
        campaign = _cancel_pending_for_stale_bias(self, campaign, price, critical)
        return _cancelled_display(campaign, critical)

    if blocked and not isinstance(campaign, dict):
        reason = _quality_reason(critical).replace("Pending idea cancelled before entry because ", "No new trade will be published because ")
        return (
            {"status": "DATA WAIT", "reason": reason},
            {
                "action": "WAIT",
                "order_type": "none",
                "reason": reason,
                "manual_only": True,
                "automatic_order_placement": False,
                "data_quality_blocked": True,
                "critical_stale": list(critical),
            },
        )

    if isinstance(campaign, dict) and status == "invalidated":
        quality = dict(campaign.get("data_quality_invalidation") or {})
        if quality.get("reason") == "stale_critical_timeframe":
            saved_critical = [str(value) for value in (quality.get("critical_stale") or []) if value]
            return _cancelled_display(campaign, saved_critical)

    setup, trade = _original_trade_idea(self, price, atr, bias, zones, liquidity)
    setup = dict(setup or {})
    trade = dict(trade or {})

    # A triggered trade is real execution state. Stale context can block a new
    # decision, but must never move or silently cancel an already-active stop/TP.
    campaign_after = getattr(self, "_live_campaign", None)
    status_after = str((campaign_after or {}).get("status") or "").lower() if isinstance(campaign_after, dict) else ""
    if blocked and status_after == "active":
        return _active_warning(setup, trade, critical)

    return setup, trade


def _runtime_status_v44(self: core.LiveTrader) -> dict[str, Any]:
    state = dict(_original_runtime_status(self))
    state.update(
        {
            "stale_campaign_guard_version": GUARD_VERSION,
            "pending_campaign_cancelled_on_critical_stale": True,
            "active_campaign_preserved_on_critical_stale": True,
        }
    )
    return state


core.LiveTrader._trade_idea = _trade_idea_v44  # type: ignore[method-assign]
core.LiveTrader.runtime_status = _runtime_status_v44  # type: ignore[method-assign]
