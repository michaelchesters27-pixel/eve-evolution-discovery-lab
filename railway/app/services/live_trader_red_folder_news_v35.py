from __future__ import annotations

import hashlib
from datetime import datetime, timedelta, timezone
from typing import Any
from zoneinfo import ZoneInfo

from app.services import live_trader as core
from app.services import live_trader_audit_hardening_v26 as hardening
from app.services import live_trader_historical_learning_v29 as academy
from app.services import live_trader_historical_runtime_v30 as runtime
from app.services import live_trader_trade_lock_v28 as lock

NEWS_VERSION = "eve-live-red-folder-news-v1"
NEWS_SOURCE = "Forex Factory manual"
NEWS_TIMEZONE = "Europe/London"
NEWS_POLICY = (
    "Only manually entered USD high-impact (red-folder) economic events are used. Standard red events block new "
    "XAU/USD entries from 30 minutes before until 15 minutes after release. CPI, PCE, NFP, FOMC/rate decisions "
    "and Fed-chair/Powell events use a wider 45-minute-before to 30-minute-after window. Pending campaigns are "
    "suspended without changing their geometry or consuming their validity clock; active triggered campaigns keep "
    "their locked entry/stop/target and are flagged as elevated news risk. Forward-learning samples whose horizon "
    "overlaps a known blackout are not recorded as normal-market evidence."
)
CALENDAR_CACHE_SECONDS = 20
CALENDAR_LOOKBACK_HOURS = 2
CALENDAR_LOOKAHEAD_DAYS = 14
UK = ZoneInfo(NEWS_TIMEZONE)

MAJOR_EVENT_MARKERS = (
    "cpi",
    "consumer price index",
    "core pce",
    "pce price",
    "personal consumption expenditures",
    "non-farm",
    "nonfarm",
    "nfp",
    "fomc",
    "federal funds",
    "fed funds",
    "interest rate decision",
    "rate decision",
    "powell",
    "fed chair",
    "federal reserve chair",
)

_current_trade_idea = core.LiveTrader._trade_idea
_current_refresh = core.LiveTrader.refresh_state
_current_record = core.LiveTrader._maybe_record_opinion
_current_learning_summary = core.LiveTrader.learning_summary
_current_runtime_status = core.LiveTrader.runtime_status
_current_answer = core.LiveTrader.answer


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


def _event_window(event_name: str) -> tuple[str, int, int]:
    text = " ".join(str(event_name or "").lower().split())
    major = any(marker in text for marker in MAJOR_EVENT_MARKERS)
    return ("major", 45, 30) if major else ("high", 30, 15)


def build_manual_event(symbol: str, event_date: str, event_time: str, event_name: str) -> dict[str, Any]:
    name = " ".join(str(event_name or "").strip().split())
    if not name:
        raise ValueError("Event name is required.")
    if len(name) > 180:
        raise ValueError("Event name is too long.")
    try:
        naive = datetime.fromisoformat(f"{str(event_date).strip()}T{str(event_time).strip()}")
    except ValueError as exc:
        raise ValueError("Enter a valid date and time exactly as shown on Forex Factory.") from exc
    if naive.second or naive.microsecond:
        naive = naive.replace(second=0, microsecond=0)
    local = naive.replace(tzinfo=UK)
    utc = local.astimezone(timezone.utc)
    # Reject a nonexistent UK wall-clock time around the spring DST transition.
    if utc.astimezone(UK).replace(tzinfo=None) != naive:
        raise ValueError("That UK clock time does not exist because of the daylight-saving change.")
    event_class, pre_minutes, post_minutes = _event_window(name)
    raw = f"{symbol}|USD|{utc.isoformat()}|{name.lower()}"
    event_id = hashlib.sha1(raw.encode()).hexdigest()[:24]
    return {
        "event_id": event_id,
        "symbol": symbol,
        "currency": "USD",
        "event_name": name,
        "scheduled_at": utc.isoformat(),
        "scheduled_local": local.isoformat(),
        "source_timezone": NEWS_TIMEZONE,
        "impact": "high",
        "event_class": event_class,
        "pre_minutes": pre_minutes,
        "post_minutes": post_minutes,
        "source": NEWS_SOURCE,
        "enabled": True,
        "updated_at": core.utc_now().isoformat(),
    }


def _decorate_event(row: dict[str, Any]) -> dict[str, Any] | None:
    scheduled = _parse_time(row.get("scheduled_at"))
    if scheduled is None:
        return None
    pre = max(0, int(core.number(row.get("pre_minutes"), 30)))
    post = max(0, int(core.number(row.get("post_minutes"), 15)))
    local = scheduled.astimezone(UK)
    return {
        "event_id": str(row.get("event_id") or ""),
        "currency": "USD",
        "event_name": str(row.get("event_name") or "High-impact USD event"),
        "scheduled_at": scheduled.isoformat(),
        "scheduled_local": local.isoformat(),
        "event_class": str(row.get("event_class") or "high"),
        "impact": "high",
        "pre_minutes": pre,
        "post_minutes": post,
        "blackout_start": (scheduled - timedelta(minutes=pre)).isoformat(),
        "blackout_end": (scheduled + timedelta(minutes=post)).isoformat(),
        "source": str(row.get("source") or NEWS_SOURCE),
    }


def news_status_from_rows(rows: list[dict[str, Any]], at: datetime) -> dict[str, Any]:
    now = at.astimezone(timezone.utc)
    items = [item for item in (_decorate_event(row) for row in rows) if item is not None]
    items.sort(key=lambda item: str(item.get("scheduled_at") or ""))
    active: list[dict[str, Any]] = []
    for item in items:
        start = _parse_time(item.get("blackout_start"))
        end = _parse_time(item.get("blackout_end"))
        if start is not None and end is not None and start <= now < end:
            active.append(item)
    future = [item for item in items if (_parse_time(item.get("scheduled_at")) or now - timedelta(days=1)) >= now]
    next_event = future[0] if future else None
    next_time = _parse_time((next_event or {}).get("scheduled_at"))
    active_end = max((_parse_time(item.get("blackout_end")) for item in active), default=None)
    active_start = min((_parse_time(item.get("blackout_start")) for item in active), default=None)
    return {
        "version": NEWS_VERSION,
        "status": "blackout" if active else ("armed" if next_event else "clear"),
        "available": True,
        "new_trade_blocked": bool(active),
        "forward_learning_blocked": bool(active),
        "active": bool(active),
        "active_events": active,
        "active_event_ids": [str(item.get("event_id") or "") for item in active],
        "active_window_start": active_start.isoformat() if active_start else None,
        "active_window_end": active_end.isoformat() if active_end else None,
        "next_event": next_event,
        "minutes_to_next_event": round((next_time - now).total_seconds() / 60.0, 1) if next_time else None,
        "events": items,
        "event_count": len(items),
        "input_timezone": NEWS_TIMEZONE,
        "source": NEWS_SOURCE,
        "policy": NEWS_POLICY,
    }


def _unavailable_status(error: Exception | str) -> dict[str, Any]:
    return {
        "version": NEWS_VERSION,
        "status": "unavailable",
        "available": False,
        "new_trade_blocked": True,
        "forward_learning_blocked": True,
        "active": False,
        "active_events": [],
        "active_event_ids": [],
        "active_window_start": None,
        "active_window_end": None,
        "next_event": None,
        "minutes_to_next_event": None,
        "events": [],
        "event_count": 0,
        "input_timezone": NEWS_TIMEZONE,
        "source": NEWS_SOURCE,
        "policy": NEWS_POLICY,
        "error": str(error)[:240],
    }


async def _load_calendar(self: core.LiveTrader, *, force: bool = False) -> dict[str, Any]:
    now = core.utc_now()
    cached_at = getattr(self, "_news_calendar_cache_at_v35", None)
    cached_rows = getattr(self, "_news_calendar_rows_v35", None)
    if (
        not force
        and isinstance(cached_at, datetime)
        and isinstance(cached_rows, list)
        and (now - cached_at).total_seconds() < CALENDAR_CACHE_SECONDS
    ):
        return news_status_from_rows(cached_rows, now)
    start = now - timedelta(hours=CALENDAR_LOOKBACK_HOURS)
    end = now + timedelta(days=CALENDAR_LOOKAHEAD_DAYS)
    try:
        rows = await self.repo.client.get(
            "live_trader_news_events",
            params={
                "select": "event_id,event_name,scheduled_at,event_class,pre_minutes,post_minutes,source",
                "symbol": f"eq.{self.symbol}",
                "currency": "eq.USD",
                "enabled": "eq.true",
                "and": f"(scheduled_at.gte.{start.isoformat()},scheduled_at.lte.{end.isoformat()})",
                "order": "scheduled_at.asc,event_name.asc",
                "limit": "100",
            },
        )
        self._news_calendar_rows_v35 = list(rows)
        self._news_calendar_cache_at_v35 = now
        return news_status_from_rows(list(rows), now)
    except Exception as exc:
        core.logger.warning("Live Trader could not read manual red-folder calendar: %s", exc)
        return _unavailable_status(exc)


def _news_blocks_new_trade(self: core.LiveTrader) -> bool:
    if not getattr(self, "_live_campaign_loaded_v28", False):
        return False
    status = getattr(self, "_news_status_v35", None)
    return not isinstance(status, dict) or bool(status.get("new_trade_blocked"))


def _pause_pending_campaign(self: core.LiveTrader, campaign: dict[str, Any], status: dict[str, Any]) -> None:
    if str(campaign.get("status") or "").lower() != "pending":
        return
    if not campaign.get("news_pause_started_at"):
        campaign["news_pause_started_at"] = core.utc_now().isoformat()
        self._live_campaign_dirty = True
    campaign["news_suspended"] = True
    campaign["news_suspended_until"] = status.get("active_window_end")
    campaign["news_suspended_event_ids"] = list(status.get("active_event_ids") or [])


def _resume_pending_campaign(self: core.LiveTrader, campaign: dict[str, Any]) -> None:
    if str(campaign.get("status") or "").lower() != "pending":
        return
    started = _parse_time(campaign.get("news_pause_started_at"))
    if started is not None:
        elapsed = max(0.0, (core.utc_now() - started).total_seconds())
        expires = _parse_time(campaign.get("expires_at"))
        if expires is not None and elapsed > 0:
            campaign["expires_at"] = (expires + timedelta(seconds=elapsed)).isoformat()
        self._live_campaign_dirty = True
    for key in ("news_pause_started_at", "news_suspended", "news_suspended_until", "news_suspended_event_ids"):
        campaign.pop(key, None)


def _event_names(status: dict[str, Any]) -> str:
    names = [str(item.get("event_name") or "") for item in status.get("active_events") or []]
    names = [name for name in names if name]
    return ", ".join(names) if names else "high-impact USD news"


def _trade_idea_v35(
    self: core.LiveTrader,
    price: float,
    atr: float,
    bias: dict[str, Any],
    zones: dict[str, list[dict[str, Any]]],
    liquidity: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, Any]]:
    # Keep deterministic/offline strategy tests free of runtime calendar state.
    if not getattr(self, "_live_campaign_loaded_v28", False):
        return _current_trade_idea(self, price, atr, bias, zones, liquidity)
    # Broker closure remains the stronger guard and keeps its established wording.
    if not academy.broker_market_open(core.utc_now()):
        return _current_trade_idea(self, price, atr, bias, zones, liquidity)

    status = getattr(self, "_news_status_v35", None)
    unavailable = not isinstance(status, dict) or not bool(status.get("available"))
    blocked = unavailable or bool(status.get("new_trade_blocked"))
    campaign = getattr(self, "_live_campaign", None)

    if isinstance(campaign, dict) and str(campaign.get("status") or "").lower() == "pending":
        if blocked:
            safe_status = status if isinstance(status, dict) else _unavailable_status("calendar not loaded")
            _pause_pending_campaign(self, campaign, safe_status)
            trade = lock._campaign_trade(campaign)
            trade["news_suspended"] = True
            trade["news_risk"] = "calendar_unavailable" if unavailable else "high_impact_blackout"
            trade["news_events"] = list(safe_status.get("active_events") or [])
            reason = (
                "The red-folder calendar is temporarily unavailable, so EVE is holding this pending idea closed-safe."
                if unavailable
                else f"High-impact USD news blackout: {_event_names(safe_status)}. The pending order is suspended and cannot trigger, invalidate or expire until the blackout ends."
            )
            return {"status": "NEWS BLACKOUT — PENDING IDEA SUSPENDED", "reason": reason}, trade
        _resume_pending_campaign(self, campaign)

    if blocked and not isinstance(campaign, dict):
        reason = (
            "EVE cannot confirm the red-folder calendar, so no new XAU/USD trade will be published until calendar status is restored."
            if unavailable
            else f"High-impact USD news blackout: {_event_names(status)}. EVE will not publish a new XAU/USD entry during this window."
        )
        return (
            {"status": "HIGH-IMPACT NEWS — NO NEW TRADE", "reason": reason},
            {
                "action": "WAIT",
                "order_type": "none",
                "reason": reason,
                "manual_only": True,
                "automatic_order_placement": False,
                "news_blackout": not unavailable,
                "news_calendar_unavailable": unavailable,
            },
        )

    setup, trade = _current_trade_idea(self, price, atr, bias, zones, liquidity)
    setup = dict(setup or {})
    trade = dict(trade or {})
    # A triggered trade stays exactly as published. News changes risk context, not geometry.
    if isinstance(campaign, dict) and str(campaign.get("status") or "").lower() == "active" and blocked:
        trade["news_risk"] = "calendar_unavailable" if unavailable else "high_impact_blackout"
        trade["news_events"] = list((status or {}).get("active_events") or [])
        setup["news_warning"] = (
            "Red-folder calendar unavailable; active locked campaign continues to its published stop/target."
            if unavailable
            else f"High-impact USD news active: {_event_names(status)}. The triggered campaign remains locked to its published stop and target."
        )
    return setup, trade


def _window_intersects_known_news(self: core.LiveTrader, observed: datetime, horizon_minutes: int) -> bool:
    status = getattr(self, "_news_status_v35", None)
    if not isinstance(status, dict) or not bool(status.get("available")):
        return True
    horizon = observed + timedelta(minutes=max(1, int(horizon_minutes)))
    for item in status.get("events") or []:
        start = _parse_time(item.get("blackout_start"))
        end = _parse_time(item.get("blackout_end"))
        if start is None or end is None:
            continue
        if observed < end and horizon > start:
            return True
    return False


async def _record_v35(self: core.LiveTrader, state: dict[str, Any]) -> None:
    if not getattr(self, "_live_campaign_loaded_v28", False):
        await _current_record(self, state)
        return
    observed = hardening._market_observation_time(state)
    if observed is None:
        return
    horizon = int(self.settings.live_trader_learning_horizon_minutes)
    if _window_intersects_known_news(self, observed, horizon):
        return
    await _current_record(self, state)


async def _refresh_v35(self: core.LiveTrader, *, force_rows: bool = False) -> dict[str, Any]:
    # Calendar must be loaded before underlying refresh calls the synchronous trade engine.
    status = await _load_calendar(self)
    self._news_status_v35 = status
    state = await _current_refresh(self, force_rows=force_rows)
    state["news_risk"] = status
    hours = dict(state.get("market_hours") or {})
    if bool(hours.get("tradable")) and (bool(status.get("new_trade_blocked")) or not bool(status.get("available"))):
        campaign = state.get("trade_campaign")
        campaign_status = str((campaign or {}).get("status") or "").lower() if isinstance(campaign, dict) else ""
        if campaign_status == "active":
            warning = (
                "The red-folder calendar is temporarily unavailable. The triggered campaign stays locked; no replacement trade will be issued."
                if not status.get("available")
                else f"High-impact USD news risk is active: {_event_names(status)}. The live campaign stays locked to its published stop and target."
            )
            setup = dict(state.get("setup") or {})
            setup["news_warning"] = warning
            state["setup"] = setup
            trade = dict(state.get("trade") or {})
            trade["news_risk"] = "calendar_unavailable" if not status.get("available") else "high_impact_blackout"
            state["trade"] = trade
            state["opinion"] = f"Micky, {warning}"
        elif campaign_status == "pending":
            state["opinion"] = (
                "Micky, high-impact USD news protection is active. The pending campaign is suspended unchanged and cannot trigger until the blackout is over."
                if status.get("available")
                else "Micky, I cannot confirm the red-folder calendar right now, so the pending campaign is suspended closed-safe until calendar status is restored."
            )
        else:
            state["opinion"] = (
                f"Micky, high-impact USD news protection is active for {_event_names(status)}. I will not publish a new gold trade until the blackout ends."
                if status.get("available")
                else "Micky, I cannot confirm the red-folder calendar right now, so I will not publish a new gold trade until calendar status is restored."
            )
    self._latest_state = state
    return state


async def _learning_summary_v35(self: core.LiveTrader) -> dict[str, Any]:
    summary = dict(await _current_learning_summary(self))
    status = getattr(self, "_news_status_v35", None)
    if not isinstance(status, dict):
        status = await _load_calendar(self)
        self._news_status_v35 = status
    summary["news_risk"] = status
    return summary


async def _add_news_event(self: core.LiveTrader, event_date: str, event_time: str, event_name: str) -> dict[str, Any]:
    row = build_manual_event(self.symbol, event_date, event_time, event_name)
    await self.repo.client.upsert(
        "live_trader_news_events",
        row,
        on_conflict="event_id",
        return_rows=False,
    )
    self._news_calendar_cache_at_v35 = None
    status = await _load_calendar(self, force=True)
    self._news_status_v35 = status
    return {"ok": True, "event": _decorate_event(row), "news_risk": status}


async def _remove_news_event(self: core.LiveTrader, event_id: str) -> dict[str, Any]:
    key = str(event_id or "").strip()
    if not key:
        raise ValueError("Event id is required.")
    await self.repo.client.patch(
        "live_trader_news_events",
        {"enabled": False, "updated_at": core.utc_now().isoformat()},
        filters={"event_id": f"eq.{key}", "symbol": f"eq.{self.symbol}"},
    )
    self._news_calendar_cache_at_v35 = None
    status = await _load_calendar(self, force=True)
    self._news_status_v35 = status
    return {"ok": True, "removed_event_id": key, "news_risk": status}


async def _answer_v35(self: core.LiveTrader, question: str) -> dict[str, Any]:
    text = str(question or "").strip()
    if text.startswith("__EVE_NEWS_ADD__|"):
        parts = text.split("|", 3)
        if len(parts) != 4:
            return {"answer": "Could not add the red-folder event: date, time and event name are required."}
        try:
            result = await _add_news_event(self, parts[1], parts[2], parts[3])
        except Exception as exc:
            return {"answer": f"Could not add the red-folder event: {str(exc)[:200]}"}
        event = result.get("event") or {}
        label = "MAJOR" if str(event.get("event_class")) == "major" else "HIGH"
        return {
            "answer": f"Added {event.get('event_name')} as a {label} USD red-folder event. EVE's news blackout is armed automatically.",
            **result,
        }
    if text.startswith("__EVE_NEWS_REMOVE__|"):
        event_id = text.split("|", 1)[1] if "|" in text else ""
        try:
            result = await _remove_news_event(self, event_id)
        except Exception as exc:
            return {"answer": f"Could not remove the red-folder event: {str(exc)[:200]}"}
        return {"answer": "Removed that red-folder event from EVE's weekly calendar.", **result}
    return await _current_answer(self, question)


def _runtime_status_v35(self: core.LiveTrader) -> dict[str, Any]:
    status = dict(_current_runtime_status(self))
    news = getattr(self, "_news_status_v35", None)
    status.update(
        {
            "red_folder_news_version": NEWS_VERSION,
            "red_folder_news_source": NEWS_SOURCE,
            "red_folder_news_timezone": NEWS_TIMEZONE,
            "red_folder_news_status": (news or {}).get("status") if isinstance(news, dict) else "starting",
            "red_folder_new_trade_blocked": _news_blocks_new_trade(self),
            "red_folder_news_policy": NEWS_POLICY,
        }
    )
    return status


# Install the latest runtime layer.
core.LiveTrader._trade_idea = _trade_idea_v35  # type: ignore[method-assign]
core.LiveTrader.refresh_state = _refresh_v35  # type: ignore[method-assign]
core.LiveTrader._maybe_record_opinion = _record_v35  # type: ignore[method-assign]
core.LiveTrader.learning_summary = _learning_summary_v35  # type: ignore[method-assign]
core.LiveTrader.answer = _answer_v35  # type: ignore[method-assign]
core.LiveTrader.runtime_status = _runtime_status_v35  # type: ignore[method-assign]
core.LiveTrader.add_news_event = _add_news_event  # type: ignore[attr-defined]
core.LiveTrader.remove_news_event = _remove_news_event  # type: ignore[attr-defined]

# Preserve legacy public aliases asserted by the existing regression suite while pointing
# them at the newest wrappers. Captured predecessors above still execute the older audited layers.
lock._trade_idea_v28 = _trade_idea_v35
lock._refresh_state_v28 = _refresh_v35
runtime._refresh_state_v30 = _refresh_v35
hardening._record_v26 = _record_v35
