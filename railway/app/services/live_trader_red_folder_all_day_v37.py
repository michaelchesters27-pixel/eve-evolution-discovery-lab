from __future__ import annotations

import hashlib
from datetime import date, datetime, time, timedelta, timezone
from typing import Any

from app.services import live_trader as core
from app.services import live_trader_red_folder_news_confirmation_v36 as confirmation
from app.services import live_trader_red_folder_news_v35 as news

ALL_DAY_VERSION = "eve-live-red-folder-all-day-v1"
ALL_DAY_POLICY = (
    "Forex Factory RED events shown as All/Tentative with no exact release time may be entered as all-day macro risk. "
    "EVE blocks new XAU/USD campaigns for the full Europe/London calendar day, suspends pending campaigns without "
    "changing their geometry or consuming their validity clock, keeps already-triggered campaigns locked to their "
    "published stop/target, and excludes overlapping forward-learning samples from normal-market evidence."
)

_current_answer = core.LiveTrader.answer
_current_runtime_status = core.LiveTrader.runtime_status
_current_decorate_event = news._decorate_event


def build_all_day_event(symbol: str, event_date: str, event_name: str) -> dict[str, Any]:
    name = " ".join(str(event_name or "").strip().split())
    if not name:
        raise ValueError("Event name is required.")
    if len(name) > 180:
        raise ValueError("Event name is too long.")
    try:
        day = date.fromisoformat(str(event_date).strip())
    except ValueError as exc:
        raise ValueError("Enter a valid Forex Factory date.") from exc

    # Noon is only the stable storage/sort anchor. The risk window itself is
    # calculated from local midnight to the next local midnight, so BST/GMT
    # transitions remain correct even on 23/25-hour days.
    local_noon = datetime.combine(day, time(12, 0), tzinfo=news.UK)
    utc_noon = local_noon.astimezone(timezone.utc)
    raw = f"{symbol}|ALL|{day.isoformat()}|{name.lower()}"
    event_id = hashlib.sha1(raw.encode()).hexdigest()[:24]
    return {
        "event_id": event_id,
        "symbol": symbol,
        "currency": "ALL",
        "event_name": name,
        "scheduled_at": utc_noon.isoformat(),
        "scheduled_local": local_noon.isoformat(),
        "source_timezone": news.NEWS_TIMEZONE,
        "impact": "high",
        "event_class": "all_day",
        "pre_minutes": 0,
        "post_minutes": 0,
        "source": news.NEWS_SOURCE,
        "enabled": True,
        "updated_at": core.utc_now().isoformat(),
    }


def _decorate_event_v37(row: dict[str, Any]) -> dict[str, Any] | None:
    if str(row.get("event_class") or "") != "all_day":
        return _current_decorate_event(row)

    scheduled = news._parse_time(row.get("scheduled_at"))
    if scheduled is None:
        return None
    local_day = scheduled.astimezone(news.UK).date()
    start_local = datetime.combine(local_day, time.min, tzinfo=news.UK)
    end_local = datetime.combine(local_day + timedelta(days=1), time.min, tzinfo=news.UK)
    return {
        "event_id": str(row.get("event_id") or ""),
        "currency": str(row.get("currency") or "ALL"),
        "event_name": str(row.get("event_name") or "All-day macro event"),
        "scheduled_at": scheduled.isoformat(),
        "scheduled_local": scheduled.astimezone(news.UK).isoformat(),
        "event_class": "all_day",
        "impact": "high",
        "pre_minutes": 0,
        "post_minutes": 0,
        "blackout_start": start_local.astimezone(timezone.utc).isoformat(),
        "blackout_end": end_local.astimezone(timezone.utc).isoformat(),
        "all_day": True,
        "all_day_date": local_day.isoformat(),
        "source": str(row.get("source") or news.NEWS_SOURCE),
    }


async def _load_calendar_with_all(self: core.LiveTrader, *, force: bool = False) -> dict[str, Any]:
    now = core.utc_now()
    cached_at = getattr(self, "_news_calendar_cache_at_v37", None)
    cached_rows = getattr(self, "_news_calendar_rows_v37", None)
    if (
        not force
        and isinstance(cached_at, datetime)
        and isinstance(cached_rows, list)
        and (now - cached_at).total_seconds() < news.CALENDAR_CACHE_SECONDS
    ):
        result = news.news_status_from_rows(cached_rows, now)
        result["all_day_version"] = ALL_DAY_VERSION
        result["all_day_policy"] = ALL_DAY_POLICY
        return result

    start = now - timedelta(hours=news.CALENDAR_LOOKBACK_HOURS)
    end = now + timedelta(days=news.CALENDAR_LOOKAHEAD_DAYS)
    try:
        rows = await self.repo.client.get(
            "live_trader_news_events",
            params={
                "select": "event_id,currency,event_name,scheduled_at,event_class,pre_minutes,post_minutes,source",
                "symbol": f"eq.{self.symbol}",
                "currency": "in.(USD,ALL)",
                "enabled": "eq.true",
                "and": f"(scheduled_at.gte.{start.isoformat()},scheduled_at.lte.{end.isoformat()})",
                "order": "scheduled_at.asc,event_name.asc",
                "limit": "100",
            },
        )
        self._news_calendar_rows_v37 = list(rows)
        self._news_calendar_cache_at_v37 = now
        result = news.news_status_from_rows(list(rows), now)
        result["all_day_version"] = ALL_DAY_VERSION
        result["all_day_policy"] = ALL_DAY_POLICY
        return result
    except Exception as exc:
        core.logger.warning("Live Trader could not read timed + all-day red-folder calendar: %s", exc)
        result = news._unavailable_status(exc)
        result["all_day_version"] = ALL_DAY_VERSION
        result["all_day_policy"] = ALL_DAY_POLICY
        return result


async def _add_all_day_event(self: core.LiveTrader, event_date: str, event_name: str) -> dict[str, Any]:
    row = build_all_day_event(self.symbol, event_date, event_name)
    await self.repo.client.upsert(
        "live_trader_news_events",
        row,
        on_conflict="event_id",
        return_rows=False,
    )
    self._news_calendar_cache_at_v37 = None
    self._news_calendar_cache_at_v35 = None
    status = await news._load_calendar(self, force=True)
    self._news_status_v35 = status
    return {"ok": True, "event": _decorate_event_v37(row), "news_risk": status}


async def _answer_v37(self: core.LiveTrader, question: str) -> dict[str, Any]:
    text = str(question or "").strip()
    if text.startswith("__EVE_NEWS_ADD_ALL_DAY__|"):
        parts = text.split("|", 2)
        if len(parts) != 3:
            return {"answer": "Could not add the all-day red-folder event: date and event name are required."}
        try:
            result = await _add_all_day_event(self, parts[1], parts[2])
        except Exception as exc:
            return {"answer": f"Could not add the all-day red-folder event: {str(exc)[:200]}"}
        event = result.get("event") or {}
        return {
            "answer": (
                f"Added {event.get('event_name')} as an ALL-DAY red-folder macro-risk event. "
                "EVE will block new gold setups for that full UK calendar day."
            ),
            **result,
        }
    return await _current_answer(self, question)


def _runtime_status_v37(self: core.LiveTrader) -> dict[str, Any]:
    status = dict(_current_runtime_status(self))
    status.update(
        {
            "red_folder_all_day_version": ALL_DAY_VERSION,
            "red_folder_all_day_policy": ALL_DAY_POLICY,
        }
    )
    return status


# v35's status builder resolves its decorator dynamically; v36 resolves its base
# calendar loader dynamically. Rebinding both inserts all-day support into the same
# audited trade/learning guard rather than creating a parallel safety path.
news._decorate_event = _decorate_event_v37
confirmation._current_calendar_loader = _load_calendar_with_all

core.LiveTrader.answer = _answer_v37  # type: ignore[method-assign]
core.LiveTrader.runtime_status = _runtime_status_v37  # type: ignore[method-assign]
core.LiveTrader.add_all_day_news_event = _add_all_day_event  # type: ignore[attr-defined]
