from __future__ import annotations

import hashlib
from datetime import date, datetime, timedelta
from typing import Any

from app.services import live_trader as core
from app.services import live_trader_audit_hardening_v26 as hardening
from app.services import live_trader_historical_learning_v29 as academy
from app.services import live_trader_historical_runtime_v30 as runtime
from app.services import live_trader_red_folder_news_v35 as news
from app.services import live_trader_trade_lock_v28 as lock

CONFIRMATION_VERSION = "eve-live-red-folder-week-confirmation-v1"
CONFIRMATION_CACHE_SECONDS = 20

_current_calendar_loader = news._load_calendar
_current_window_intersects = news._window_intersects_known_news
_current_trade_idea = core.LiveTrader._trade_idea
_current_refresh = core.LiveTrader.refresh_state
_current_answer = core.LiveTrader.answer
_current_runtime_status = core.LiveTrader.runtime_status


def _week_start(at: datetime) -> date:
    local_day = at.astimezone(news.UK).date()
    # Python Monday=0; Forex Factory weekly workflow is Sunday-Saturday.
    days_since_sunday = (local_day.weekday() + 1) % 7
    return local_day - timedelta(days=days_since_sunday)


def _week_key(symbol: str, week_start: date) -> str:
    raw = f"{symbol}|{week_start.isoformat()}|{news.NEWS_SOURCE}"
    return hashlib.sha1(raw.encode()).hexdigest()[:24]


def _apply_confirmation(status: dict[str, Any], row: dict[str, Any] | None, at: datetime) -> dict[str, Any]:
    result = dict(status)
    start = _week_start(at)
    confirmed = isinstance(row, dict) and str(row.get("week_start") or "") == start.isoformat()
    result.update(
        {
            "confirmation_version": CONFIRMATION_VERSION,
            "week_start": start.isoformat(),
            "week_end": (start + timedelta(days=6)).isoformat(),
            "week_confirmed": confirmed,
            "week_confirmed_at": row.get("confirmed_at") if confirmed else None,
        }
    )
    if result.get("available") and not confirmed:
        result["status"] = "week_unconfirmed"
        result["new_trade_blocked"] = True
        result["forward_learning_blocked"] = True
        result["block_reason"] = "weekly_calendar_not_confirmed"
    return result


async def _week_confirmation(self: core.LiveTrader, at: datetime, *, force: bool = False) -> dict[str, Any] | None:
    start = _week_start(at)
    cached_at = getattr(self, "_news_week_cache_at_v36", None)
    cached_start = getattr(self, "_news_week_start_v36", None)
    cached_row = getattr(self, "_news_week_row_v36", None)
    if (
        not force
        and isinstance(cached_at, datetime)
        and cached_start == start.isoformat()
        and (at - cached_at).total_seconds() < CONFIRMATION_CACHE_SECONDS
    ):
        return dict(cached_row) if isinstance(cached_row, dict) else None
    rows = await self.repo.client.get(
        "live_trader_news_weeks",
        params={
            "select": "week_key,week_start,confirmed_at,source,source_timezone",
            "symbol": f"eq.{self.symbol}",
            "week_start": f"eq.{start.isoformat()}",
            "limit": "1",
        },
    )
    row = dict(rows[0]) if rows else None
    self._news_week_cache_at_v36 = at
    self._news_week_start_v36 = start.isoformat()
    self._news_week_row_v36 = dict(row) if row else None
    return row


async def _load_calendar_v36(self: core.LiveTrader, *, force: bool = False) -> dict[str, Any]:
    now = core.utc_now()
    try:
        base = await _current_calendar_loader(self, force=force)
        if not bool(base.get("available")):
            return base
        row = await _week_confirmation(self, now, force=force)
        return _apply_confirmation(base, row, now)
    except Exception as exc:
        core.logger.warning("Live Trader could not confirm weekly red-folder calendar: %s", exc)
        status = news._unavailable_status(exc)
        status["confirmation_version"] = CONFIRMATION_VERSION
        status["block_reason"] = "weekly_confirmation_unavailable"
        return status


def _window_intersects_v36(self: core.LiveTrader, observed: datetime, horizon_minutes: int) -> bool:
    status = getattr(self, "_news_status_v35", None)
    if isinstance(status, dict) and status.get("week_confirmed") is False:
        return True
    return _current_window_intersects(self, observed, horizon_minutes)


def _week_unconfirmed(status: Any) -> bool:
    return isinstance(status, dict) and bool(status.get("available")) and status.get("week_confirmed") is False


def _trade_idea_v36(
    self: core.LiveTrader,
    price: float,
    atr: float,
    bias: dict[str, Any],
    zones: dict[str, list[dict[str, Any]]],
    liquidity: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, Any]]:
    if not getattr(self, "_live_campaign_loaded_v28", False) or not academy.broker_market_open(core.utc_now()):
        return _current_trade_idea(self, price, atr, bias, zones, liquidity)

    status = getattr(self, "_news_status_v35", None)
    if not _week_unconfirmed(status):
        return _current_trade_idea(self, price, atr, bias, zones, liquidity)

    campaign = getattr(self, "_live_campaign", None)
    reason = (
        "This week's Forex Factory USD RED calendar has not been confirmed. EVE is closed-safe until the weekly check is completed."
    )
    if isinstance(campaign, dict) and str(campaign.get("status") or "").lower() == "pending":
        news._pause_pending_campaign(self, campaign, status)
        trade = lock._campaign_trade(campaign)
        trade["news_suspended"] = True
        trade["news_risk"] = "weekly_calendar_not_confirmed"
        return {"status": "NEWS WEEK NOT CONFIRMED — PENDING IDEA SUSPENDED", "reason": reason}, trade

    if not isinstance(campaign, dict):
        return (
            {"status": "NEWS WEEK NOT CONFIRMED — NO NEW TRADE", "reason": reason},
            {
                "action": "WAIT",
                "order_type": "none",
                "reason": reason,
                "manual_only": True,
                "automatic_order_placement": False,
                "news_week_unconfirmed": True,
            },
        )

    setup, trade = _current_trade_idea(self, price, atr, bias, zones, liquidity)
    setup = dict(setup or {})
    trade = dict(trade or {})
    if str(campaign.get("status") or "").lower() == "active":
        trade["news_risk"] = "weekly_calendar_not_confirmed"
        setup["news_warning"] = (
            "Weekly Forex Factory calendar is not confirmed. The triggered campaign remains locked to its published stop and target."
        )
    return setup, trade


async def _refresh_v36(self: core.LiveTrader, *, force_rows: bool = False) -> dict[str, Any]:
    state = await _current_refresh(self, force_rows=force_rows)
    status = state.get("news_risk") or getattr(self, "_news_status_v35", None)
    hours = dict(state.get("market_hours") or {})
    if bool(hours.get("tradable")) and _week_unconfirmed(status):
        campaign = state.get("trade_campaign")
        campaign_status = str((campaign or {}).get("status") or "").lower() if isinstance(campaign, dict) else ""
        if campaign_status == "active":
            state["opinion"] = (
                "Micky, this week's Forex Factory USD RED calendar is not confirmed. Your triggered campaign stays locked, but no replacement trade will be issued until the weekly check is confirmed."
            )
        elif campaign_status == "pending":
            state["opinion"] = (
                "Micky, this week's Forex Factory USD RED calendar is not confirmed. The pending campaign is suspended closed-safe until you confirm the weekly check."
            )
        else:
            state["opinion"] = (
                "Micky, this week's Forex Factory USD RED calendar is not confirmed. I will not publish a new gold trade until the weekly check is confirmed."
            )
    self._latest_state = state
    return state


async def _confirm_current_week(self: core.LiveTrader) -> dict[str, Any]:
    now = core.utc_now()
    start = _week_start(now)
    row = {
        "week_key": _week_key(self.symbol, start),
        "symbol": self.symbol,
        "week_start": start.isoformat(),
        "source": news.NEWS_SOURCE,
        "source_timezone": news.NEWS_TIMEZONE,
        "confirmed_at": now.isoformat(),
        "updated_at": now.isoformat(),
    }
    await self.repo.client.upsert(
        "live_trader_news_weeks",
        row,
        on_conflict="week_key",
        return_rows=False,
    )
    self._news_week_cache_at_v36 = None
    status = await _load_calendar_v36(self, force=True)
    self._news_status_v35 = status
    return {"ok": True, "week": status.get("week_start"), "news_risk": status}


async def _answer_v36(self: core.LiveTrader, question: str) -> dict[str, Any]:
    text = str(question or "").strip()
    if text == "__EVE_NEWS_CONFIRM_WEEK__":
        try:
            result = await _confirm_current_week(self)
        except Exception as exc:
            return {"answer": f"Could not confirm the weekly red-folder check: {str(exc)[:200]}"}
        return {
            "answer": "This week's Forex Factory USD RED calendar is confirmed. EVE's news guard is armed for the week.",
            **result,
        }
    return await _current_answer(self, question)


def _runtime_status_v36(self: core.LiveTrader) -> dict[str, Any]:
    status = dict(_current_runtime_status(self))
    news_status = getattr(self, "_news_status_v35", None)
    status.update(
        {
            "red_folder_confirmation_version": CONFIRMATION_VERSION,
            "red_folder_week_confirmed": (news_status or {}).get("week_confirmed") if isinstance(news_status, dict) else None,
            "red_folder_week_start": (news_status or {}).get("week_start") if isinstance(news_status, dict) else None,
        }
    )
    return status


# v35 resolves these helper names dynamically, so rebinding them makes weekly confirmation
# part of the existing pre-trade and pre-learning safety path rather than a cosmetic UI check.
news._load_calendar = _load_calendar_v36
news._window_intersects_known_news = _window_intersects_v36

core.LiveTrader._trade_idea = _trade_idea_v36  # type: ignore[method-assign]
core.LiveTrader.refresh_state = _refresh_v36  # type: ignore[method-assign]
core.LiveTrader.answer = _answer_v36  # type: ignore[method-assign]
core.LiveTrader.runtime_status = _runtime_status_v36  # type: ignore[method-assign]
core.LiveTrader.confirm_news_week = _confirm_current_week  # type: ignore[attr-defined]

# Preserve legacy identity contracts through the newest runtime wrapper.
lock._trade_idea_v28 = _trade_idea_v36
lock._refresh_state_v28 = _refresh_v36
runtime._refresh_state_v30 = _refresh_v36
hardening._record_v26 = core.LiveTrader._maybe_record_opinion
