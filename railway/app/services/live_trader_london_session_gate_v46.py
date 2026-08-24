from __future__ import annotations

from datetime import datetime, time, timezone
from typing import Any
from zoneinfo import ZoneInfo

from app.services import live_trader as core
from app.services import live_trader_clear_bias_gate_v45 as clear_gate
from app.services import live_trader_execution_integrity_v39 as integrity
from app.services import live_trader_trade_lock_v28 as lock

SESSION_GATE_VERSION = "eve-live-london-session-gate-v1"
LONDON_TZ = ZoneInfo("Europe/London")
SESSION_START = time(8, 20)
SESSION_END = time(17, 0)
OPEN_CAMPAIGN_STATUSES = {"pending", "active"}
SESSION_CANCEL_RESULT = "CANCELLED — OUTSIDE LONDON TRADE WINDOW BEFORE ENTRY"

_original_trade_idea = core.LiveTrader._trade_idea
_original_runtime_status = core.LiveTrader.runtime_status


def _utc(value: datetime | None = None) -> datetime:
    value = value or core.utc_now()
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _session_status(now: datetime | None = None) -> dict[str, Any]:
    utc_now = _utc(now)
    local = utc_now.astimezone(LONDON_TZ)
    local_clock = local.timetz().replace(tzinfo=None)
    weekday_open = local.weekday() < 5
    within_clock = SESSION_START <= local_clock < SESSION_END
    is_open = weekday_open and within_clock
    return {
        "version": SESSION_GATE_VERSION,
        "timezone": "Europe/London",
        "local_time": local.isoformat(),
        "session_date": local.date().isoformat(),
        "weekday": local.strftime("%A"),
        "start": SESSION_START.strftime("%H:%M"),
        "end": SESSION_END.strftime("%H:%M"),
        "end_exclusive": True,
        "open": is_open,
        "reason": (
            "inside London trade-idea window"
            if is_open
            else "outside London trade-idea window"
        ),
    }


def _wait_response(session: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    reason = (
        "No new trade idea: EVE only publishes trades from 08:20 until 17:00 Europe/London time, Monday to Friday."
    )
    return (
        {"status": "SESSION WAIT", "reason": reason, "london_session_gate": session},
        {
            "action": "WAIT",
            "order_type": "none",
            "reason": reason,
            "manual_only": True,
            "automatic_order_placement": False,
            "session_blocked": True,
            "london_session_gate": session,
        },
    )


def _cancel_pending_for_session(
    self: core.LiveTrader,
    campaign: dict[str, Any],
    price: float,
    session: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, Any]]:
    now = core.utc_now()
    campaign = lock._complete(campaign, "invalidated", SESSION_CANCEL_RESULT, price, now)
    campaign["session_invalidation"] = {
        "version": SESSION_GATE_VERSION,
        "reason": "outside_london_trade_window",
        "cancelled_before_entry": True,
        "cancelled_at": now.isoformat(),
        "session": dict(session),
    }
    self._live_campaign = campaign
    self._live_campaign_dirty = True

    reason = (
        "Pending idea cancelled before entry because the London trade-idea window is closed. "
        "EVE will wait until 08:20 Europe/London time before publishing another trade."
    )
    trade = lock._campaign_trade(campaign)
    trade.update(
        {
            "action": "CANCEL — SESSION CLOSED",
            "order_type": "none",
            "reason": reason,
            "campaign_locked": False,
            "session_blocked": True,
            "london_session_gate": session,
        }
    )
    setup = {
        "status": "IDEA CANCELLED",
        "reason": reason,
        "london_session_gate": session,
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
    # Historical research and deterministic regression helpers use compact bias
    # dictionaries without the v43 structural-panel marker. Do not make those
    # pure helpers depend on wall-clock time. Production Live Trader always has
    # the structural marker and therefore always takes the real session gate.
    if not clear_gate._is_modern_structural_bias(dict(bias or {})):
        return _original_trade_idea(self, price, atr, bias, zones, liquidity)

    session = _session_status()
    campaign = getattr(self, "_live_campaign", None)
    status = str((campaign or {}).get("status") or "").lower() if isinstance(campaign, dict) else ""

    # A triggered trade is real risk and must keep its original stop/target even
    # after the publication window closes. The established campaign chain owns it.
    if status == "active":
        setup, trade = _original_trade_idea(self, price, atr, bias, zones, liquidity)
        setup = dict(setup or {})
        trade = dict(trade or {})
        setup["london_session_gate"] = session
        trade["london_session_gate"] = session
        return setup, trade

    # An untriggered order is not allowed to drift into an out-of-session entry.
    if status == "pending" and not session["open"]:
        return _cancel_pending_for_session(self, campaign, price, session)

    # Outside the London window, do not call any downstream idea generator. This
    # prevents clear-bias/liquidity layers from publishing a fresh campaign.
    if status not in OPEN_CAMPAIGN_STATUSES and not session["open"]:
        return _wait_response(session)

    setup, trade = _original_trade_idea(self, price, atr, bias, zones, liquidity)
    setup = dict(setup or {})
    trade = dict(trade or {})
    setup["london_session_gate"] = session
    trade["london_session_gate"] = session
    return setup, trade


def _runtime_status_v46(self: core.LiveTrader) -> dict[str, Any]:
    state = dict(_original_runtime_status(self))
    state.update(
        {
            "london_session_gate_version": SESSION_GATE_VERSION,
            "new_trade_window_timezone": "Europe/London",
            "new_trade_window_start": "08:20",
            "new_trade_window_end": "17:00",
            "new_trade_window_end_exclusive": True,
            "new_trade_window_weekdays_only": True,
            "pending_campaign_cancelled_outside_window": True,
            "active_campaign_preserved_outside_window": True,
        }
    )
    return state


core.LiveTrader._trade_idea = _trade_idea_v46  # type: ignore[method-assign]
core.LiveTrader.runtime_status = _runtime_status_v46  # type: ignore[method-assign]

# Earlier safety modules intentionally expose aliases to the newest audited
# runtime wrapper. Keep those identity contracts intact for regression coverage.
integrity._trade_idea_v39 = _trade_idea_v46
lock._trade_idea_v28 = _trade_idea_v46
