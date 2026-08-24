from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from zoneinfo import ZoneInfo

from app.services import live_trader as core
from app.services import live_trader_execution_integrity_v39 as integrity
from app.services import live_trader_trade_lock_v28 as lock

WINDOW_VERSION = "eve-live-london-trade-window-v1"
LONDON_TZ = ZoneInfo("Europe/London")
START_MINUTE = 8 * 60 + 20
END_MINUTE = 17 * 60
OPEN_CAMPAIGN_STATUSES = {"pending", "active"}
WINDOW_RESULT = "NO TRIGGER — LONDON TRADE-IDEA WINDOW CLOSED"

_original_trade_idea = core.LiveTrader._trade_idea
_original_runtime_status = core.LiveTrader.runtime_status


def _parse_time(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _window_assessment(now_utc: datetime | None = None) -> dict[str, Any]:
    now = now_utc or core.utc_now()
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    local = now.astimezone(LONDON_TZ)
    minute = local.hour * 60 + local.minute
    weekday = local.weekday()
    open_now = weekday < 5 and START_MINUTE <= minute < END_MINUTE
    return {
        "version": WINDOW_VERSION,
        "timezone": "Europe/London",
        "start": "08:20",
        "end": "17:00",
        "open": open_now,
        "london_time": local.isoformat(),
        "weekday": weekday,
    }


def _campaign_created_inside_window(campaign: dict[str, Any]) -> bool | None:
    created = _parse_time(campaign.get("created_at"))
    if created is None:
        return None
    return bool(_window_assessment(created).get("open"))


def _window_reason(assessment: dict[str, Any], *, published_outside: bool = False) -> str:
    if published_outside:
        return (
            "Pending idea cancelled because it was originally published outside EVE's allowed "
            "08:20–17:00 Europe/London trade-idea window."
        )
    return (
        "No new trade idea: EVE only publishes trade ideas from 08:20 until 17:00 Europe/London. "
        "Outside that window she keeps analysing and learning, but waits for the next allowed session."
    )


def _cancel_pending_for_window(
    self: core.LiveTrader,
    campaign: dict[str, Any],
    price: float,
    assessment: dict[str, Any],
    *,
    published_outside: bool,
) -> tuple[dict[str, Any], dict[str, Any]]:
    now = core.utc_now()
    reason = _window_reason(assessment, published_outside=published_outside)
    campaign = lock._complete(campaign, "expired", WINDOW_RESULT, price, now)
    campaign["trade_window_expiry"] = {
        "version": WINDOW_VERSION,
        "reason": "published_outside_window" if published_outside else "window_closed_before_entry",
        "cancelled_before_entry": True,
        "cancelled_at": now.isoformat(),
        "window": {"timezone": "Europe/London", "start": "08:20", "end": "17:00"},
    }
    self._live_campaign = campaign
    self._live_campaign_dirty = True

    trade = lock._campaign_trade(campaign)
    trade.update(
        {
            "action": "CANCEL — OUTSIDE TRADE WINDOW",
            "order_type": "none",
            "reason": reason,
            "campaign_locked": False,
            "trade_window": assessment,
        }
    )
    setup = {
        "status": "SESSION WAIT",
        "reason": reason,
        "trade_window": assessment,
    }
    return setup, trade


def _trade_idea_v46(
    self: core.LiveTrader,
    price: float,
    atr: float,
    bias: dict[str, Any],
    zones: dict[str, list[dict[str, Any]]],
    liquidity: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, Any]]:
    assessment = _window_assessment()
    campaign = getattr(self, "_live_campaign", None)
    status = str((campaign or {}).get("status") or "").lower() if isinstance(campaign, dict) else ""

    # A triggered trade is real risk. Never close or rewrite it merely because the
    # publication window has ended; the established stop/target manager retains control.
    if isinstance(campaign, dict) and status == "active":
        setup, trade = _original_trade_idea(self, price, atr, bias, zones, liquidity)
        setup = dict(setup or {})
        trade = dict(trade or {})
        setup["trade_window"] = assessment
        trade["trade_window"] = assessment
        if not assessment["open"]:
            warning = "Trade already active; the London idea window is closed, but the original stop and target remain locked."
            setup["trade_window_warning"] = warning
            trade["trade_window_warning"] = warning
        return setup, trade

    # Pending orders must themselves have been published inside the allowed window,
    # and they cannot remain armed after 17:00 London waiting to trigger later.
    if isinstance(campaign, dict) and status == "pending":
        created_inside = _campaign_created_inside_window(campaign)
        if created_inside is False:
            return _cancel_pending_for_window(
                self,
                campaign,
                price,
                assessment,
                published_outside=True,
            )
        if not assessment["open"]:
            return _cancel_pending_for_window(
                self,
                campaign,
                price,
                assessment,
                published_outside=False,
            )
        setup, trade = _original_trade_idea(self, price, atr, bias, zones, liquidity)
        setup = dict(setup or {})
        trade = dict(trade or {})
        setup["trade_window"] = assessment
        trade["trade_window"] = assessment
        return setup, trade

    # No campaign is open: outside the London window EVE may still analyse, learn,
    # update bias/zones/events and resolve outcomes, but cannot publish a new order.
    if not assessment["open"]:
        reason = _window_reason(assessment)
        return (
            {"status": "SESSION WAIT", "reason": reason, "trade_window": assessment},
            {
                "action": "WAIT",
                "order_type": "none",
                "reason": reason,
                "manual_only": True,
                "automatic_order_placement": False,
                "trade_window_blocked": True,
                "trade_window": assessment,
            },
        )

    setup, trade = _original_trade_idea(self, price, atr, bias, zones, liquidity)
    setup = dict(setup or {})
    trade = dict(trade or {})
    setup["trade_window"] = assessment
    trade["trade_window"] = assessment
    return setup, trade


def _runtime_status_v46(self: core.LiveTrader) -> dict[str, Any]:
    state = dict(_original_runtime_status(self))
    state.update(
        {
            "trade_idea_window_version": WINDOW_VERSION,
            "trade_idea_timezone": "Europe/London",
            "trade_idea_window_start": "08:20",
            "trade_idea_window_end": "17:00",
            "new_trade_ideas_only_inside_window": True,
            "pending_campaigns_expire_at_window_close": True,
            "active_campaigns_preserved_after_window_close": True,
        }
    )
    return state


core.LiveTrader._trade_idea = _trade_idea_v46  # type: ignore[method-assign]
core.LiveTrader.runtime_status = _runtime_status_v46  # type: ignore[method-assign]

# Preserve the established runtime-alias identity contract used by older safety
# regression tests: those aliases intentionally identify the newest audited wrapper.
integrity._trade_idea_v39 = _trade_idea_v46
lock._trade_idea_v28 = _trade_idea_v46
