from __future__ import annotations

import hashlib
import json
from datetime import datetime, time, timedelta, timezone
from typing import Any

from app.services import live_trader as core
from app.services import live_trader_red_folder_all_day_v37 as all_day
from app.services import live_trader_red_folder_news_confirmation_v36 as confirmation
from app.services import live_trader_red_folder_news_v35 as news

VERSION = "eve-live-news-confirmation-workflow-v95"
ATTESTATION_TOKEN = "I_HAVE_CHECKED_FOREX_FACTORY"
CONFIRMATION_METHOD = "explicit_operator_forex_factory_attestation"

_current_answer = core.LiveTrader.answer
_current_runtime_status = core.LiveTrader.runtime_status


def _week_bounds(at: datetime) -> tuple[datetime, datetime]:
    start_day = confirmation._week_start(at)
    start_local = datetime.combine(start_day, time.min, tzinfo=news.UK)
    end_local = datetime.combine(start_day + timedelta(days=7), time.min, tzinfo=news.UK)
    return start_local.astimezone(timezone.utc), end_local.astimezone(timezone.utc)


def _normalise_inventory(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for row in rows:
        scheduled = news._parse_time(row.get("scheduled_at"))
        if scheduled is None:
            continue
        items.append(
            {
                "event_id": str(row.get("event_id") or ""),
                "currency": str(row.get("currency") or ""),
                "event_name": " ".join(str(row.get("event_name") or "").split()),
                "scheduled_at": scheduled.isoformat(),
                "event_class": str(row.get("event_class") or "high"),
                "pre_minutes": int(core.number(row.get("pre_minutes"), 0)),
                "post_minutes": int(core.number(row.get("post_minutes"), 0)),
                "source": str(row.get("source") or ""),
            }
        )
    items.sort(key=lambda item: (item["scheduled_at"], item["event_id"], item["event_name"]))
    return items


def _inventory_digest(items: list[dict[str, Any]]) -> str:
    raw = json.dumps(items, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(raw.encode()).hexdigest()


async def _week_inventory(self: core.LiveTrader, at: datetime) -> dict[str, Any]:
    start, end = _week_bounds(at)
    rows = await self.repo.client.get(
        "live_trader_news_events",
        params={
            "select": "event_id,currency,event_name,scheduled_at,event_class,pre_minutes,post_minutes,source,enabled",
            "symbol": f"eq.{self.symbol}",
            "currency": "in.(USD,ALL)",
            "enabled": "eq.true",
            "and": f"(scheduled_at.gte.{start.isoformat()},scheduled_at.lt.{end.isoformat()})",
            "order": "scheduled_at.asc,event_name.asc",
            "limit": "200",
        },
    )
    items = _normalise_inventory(list(rows or []))
    return {
        "week_start": confirmation._week_start(at).isoformat(),
        "week_end": (confirmation._week_start(at) + timedelta(days=6)).isoformat(),
        "event_count": len(items),
        "event_ids": [item["event_id"] for item in items],
        "event_digest": _inventory_digest(items),
        "events": items,
    }


async def _week_confirmation_v95(
    self: core.LiveTrader,
    at: datetime,
    *,
    force: bool = False,
) -> dict[str, Any] | None:
    start = confirmation._week_start(at)
    cached_at = getattr(self, "_news_week_cache_at_v95", None)
    cached_start = getattr(self, "_news_week_start_v95", None)
    cached = getattr(self, "_news_week_row_v95", None)
    if (
        not force
        and isinstance(cached_at, datetime)
        and cached_start == start.isoformat()
        and isinstance(cached, dict)
        and (at - cached_at).total_seconds() < confirmation.CONFIRMATION_CACHE_SECONDS
    ):
        return dict(cached)

    rows = await self.repo.client.get(
        "live_trader_news_weeks",
        params={
            "select": (
                "week_key,week_start,confirmed_at,source,source_timezone,"
                "confirmation_version,confirmation_method,calendar_checked_at,"
                "confirmed_event_count,confirmed_event_digest,confirmed_event_ids,"
                "source_reference,confirmation_note,confirmation_details"
            ),
            "symbol": f"eq.{self.symbol}",
            "week_start": f"eq.{start.isoformat()}",
            "limit": "1",
        },
    )
    stored = dict(rows[0]) if rows else {}
    inventory = await _week_inventory(self, at)
    result = {
        **stored,
        "week_start": start.isoformat(),
        "_current_event_count": inventory["event_count"],
        "_current_event_digest": inventory["event_digest"],
        "_current_event_ids": inventory["event_ids"],
        "_current_inventory": inventory["events"],
    }
    self._news_week_cache_at_v95 = at
    self._news_week_start_v95 = start.isoformat()
    self._news_week_row_v95 = dict(result)
    # Keep the legacy cache coherent for v36 diagnostics.
    self._news_week_cache_at_v36 = at
    self._news_week_start_v36 = start.isoformat()
    self._news_week_row_v36 = dict(result)
    return result


def _apply_confirmation_v95(
    status: dict[str, Any],
    row: dict[str, Any] | None,
    at: datetime,
) -> dict[str, Any]:
    result = dict(status)
    start = confirmation._week_start(at)
    item = dict(row or {})
    current_count = int(core.number(item.get("_current_event_count"), 0))
    current_digest = str(item.get("_current_event_digest") or "")
    current_ids = list(item.get("_current_event_ids") or [])

    same_week = str(item.get("week_start") or "") == start.isoformat()
    has_confirmation = bool(item.get("confirmed_at"))
    protocol_current = str(item.get("confirmation_version") or "") == VERSION
    stored_count = item.get("confirmed_event_count")
    stored_digest = str(item.get("confirmed_event_digest") or "")
    inventory_matches = bool(
        protocol_current
        and stored_count is not None
        and int(core.number(stored_count, -1)) == current_count
        and stored_digest
        and stored_digest == current_digest
    )
    confirmed = bool(same_week and has_confirmation and inventory_matches)

    if confirmed:
        confirmation_state = "confirmed_current_inventory"
        block_reason = None
    elif has_confirmation and not protocol_current:
        confirmation_state = "legacy_confirmation_requires_recheck"
        block_reason = "weekly_confirmation_protocol_upgrade_required"
    elif has_confirmation and protocol_current and not inventory_matches:
        confirmation_state = "calendar_changed_since_confirmation"
        block_reason = "weekly_calendar_changed_since_confirmation"
    else:
        confirmation_state = "missing"
        block_reason = "weekly_calendar_not_confirmed"

    result.update(
        {
            "confirmation_version": VERSION,
            "confirmation_method_required": CONFIRMATION_METHOD,
            "week_start": start.isoformat(),
            "week_end": (start + timedelta(days=6)).isoformat(),
            "week_confirmed": confirmed,
            "week_confirmation_state": confirmation_state,
            "week_confirmed_at": item.get("confirmed_at") if confirmed else None,
            "calendar_checked_at": item.get("calendar_checked_at") if confirmed else None,
            "current_week_event_count": current_count,
            "current_week_event_digest": current_digest,
            "current_week_event_ids": current_ids,
            "confirmed_event_count": int(core.number(stored_count, 0)) if stored_count is not None else None,
            "confirmed_event_digest": stored_digest or None,
            "source_reference": item.get("source_reference") if confirmed else None,
            "confirmation_action_required": not confirmed,
            "confirmation_instruction": (
                "Check the full Sunday-Saturday Forex Factory calendar, enter every timed USD RED event and relevant RED All/Tentative macro event, then explicitly attest that the checked event count matches EVE's current-week inventory."
                if not confirmed
                else "Weekly Forex Factory inventory is explicitly checked and still matches the confirmed snapshot."
            ),
        }
    )

    if result.get("available") and not confirmed:
        result["status"] = (
            "week_confirmation_stale"
            if confirmation_state == "calendar_changed_since_confirmation"
            else "week_unconfirmed"
        )
        result["new_trade_blocked"] = True
        result["forward_learning_blocked"] = True
        result["block_reason"] = block_reason
    elif confirmed:
        result.pop("block_reason", None)
    return result


async def _confirm_current_week_v95(
    self: core.LiveTrader,
    *,
    calendar_checked: bool = False,
    expected_event_count: int | None = None,
    source_reference: str = "",
    note: str = "",
) -> dict[str, Any]:
    if not calendar_checked:
        raise ValueError(
            "Weekly confirmation requires an explicit attestation that the full Forex Factory Sunday-Saturday calendar was checked."
        )
    if expected_event_count is None:
        raise ValueError("Expected current-week event count is required for confirmation.")
    expected = int(expected_event_count)
    if expected < 0 or expected > 200:
        raise ValueError("Expected event count must be between 0 and 200.")

    reference = " ".join(str(source_reference or "").split())
    if not reference:
        raise ValueError("A source reference is required for the manual Forex Factory check.")

    now = core.utc_now()
    inventory = await _week_inventory(self, now)
    actual = int(inventory["event_count"])
    if expected != actual:
        raise ValueError(
            f"Confirmation rejected: you attested to {expected} events but EVE currently has {actual} enabled events for this week."
        )

    start = confirmation._week_start(now)
    row = {
        "week_key": confirmation._week_key(self.symbol, start),
        "symbol": self.symbol,
        "week_start": start.isoformat(),
        "source": news.NEWS_SOURCE,
        "source_timezone": news.NEWS_TIMEZONE,
        "confirmed_at": now.isoformat(),
        "calendar_checked_at": now.isoformat(),
        "confirmation_version": VERSION,
        "confirmation_method": CONFIRMATION_METHOD,
        "confirmed_event_count": actual,
        "confirmed_event_digest": inventory["event_digest"],
        "confirmed_event_ids": inventory["event_ids"],
        "source_reference": reference[:500],
        "confirmation_note": str(note or "")[:1000] or None,
        "confirmation_details": {
            "attestation": ATTESTATION_TOKEN,
            "week_end": inventory["week_end"],
            "event_inventory": inventory["events"],
            "empty_week_explicitly_attested": actual == 0,
        },
        "updated_at": now.isoformat(),
    }
    await self.repo.client.upsert(
        "live_trader_news_weeks",
        row,
        on_conflict="week_key",
        return_rows=False,
    )

    self._news_week_cache_at_v95 = None
    self._news_week_cache_at_v36 = None
    self._news_calendar_cache_at_v35 = None
    self._news_calendar_cache_at_v37 = None
    status = await news._load_calendar(self, force=True)
    self._news_status_v35 = status
    if status.get("week_confirmed") is not True:
        raise RuntimeError("Weekly confirmation was written but did not validate against the current event inventory.")
    return {
        "ok": True,
        "week": start.isoformat(),
        "confirmed_event_count": actual,
        "confirmed_event_digest": inventory["event_digest"],
        "news_risk": status,
    }


async def _workflow_status_v95(self: core.LiveTrader, *, force: bool = True) -> dict[str, Any]:
    status = await news._load_calendar(self, force=force)
    self._news_status_v35 = status
    now = core.utc_now()
    inventory = await _week_inventory(self, now)
    return {
        "version": VERSION,
        "symbol": self.symbol,
        "source": news.NEWS_SOURCE,
        "source_timezone": news.NEWS_TIMEZONE,
        "week_start": inventory["week_start"],
        "week_end": inventory["week_end"],
        "week_confirmed": bool(status.get("week_confirmed")),
        "week_confirmation_state": status.get("week_confirmation_state"),
        "confirmation_action_required": bool(status.get("confirmation_action_required")),
        "block_reason": status.get("block_reason"),
        "current_week_event_count": inventory["event_count"],
        "current_week_event_digest": inventory["event_digest"],
        "current_week_event_ids": inventory["event_ids"],
        "current_week_events": inventory["events"],
        "news_risk": status,
        "confirmation_contract": {
            "automatic_confirmation": False,
            "explicit_calendar_checked_attestation_required": True,
            "expected_event_count_must_match": True,
            "event_inventory_hash_must_remain_unchanged": True,
            "calendar_change_after_confirmation_fails_closed": True,
        },
    }


async def _answer_v95(self: core.LiveTrader, question: str) -> dict[str, Any]:
    text = str(question or "").strip()
    if text == "__EVE_NEWS_CONFIRM_WEEK__":
        return {
            "ok": False,
            "answer": (
                "Weekly news confirmation now requires an explicit Forex Factory attestation and the exact current-week event count. "
                "Use the weekly confirmation control after checking the full calendar."
            ),
            "news_risk": await news._load_calendar(self, force=True),
        }
    prefix = "__EVE_NEWS_CONFIRM_WEEK__|"
    if text.startswith(prefix):
        parts = text.split("|", 3)
        if len(parts) < 3 or parts[2] != ATTESTATION_TOKEN:
            return {"ok": False, "answer": "Weekly confirmation rejected: explicit Forex Factory attestation is missing."}
        try:
            expected = int(parts[1])
            reference = parts[3] if len(parts) > 3 and parts[3].strip() else "Forex Factory weekly calendar manually checked in EVE"
            result = await _confirm_current_week_v95(
                self,
                calendar_checked=True,
                expected_event_count=expected,
                source_reference=reference,
            )
        except Exception as exc:
            return {"ok": False, "answer": f"Could not confirm the weekly red-folder check: {str(exc)[:300]}"}
        return {
            "answer": (
                f"This week's Forex Factory calendar is explicitly confirmed against {result['confirmed_event_count']} enabled event(s). "
                "If the event inventory changes, EVE will automatically block again until it is rechecked."
            ),
            **result,
        }
    return await _current_answer(self, question)


def _runtime_status_v95(self: core.LiveTrader) -> dict[str, Any]:
    status = dict(_current_runtime_status(self))
    news_status = getattr(self, "_news_status_v35", None)
    status.update(
        {
            "news_confirmation_workflow_version": VERSION,
            "news_confirmation_automatic": False,
            "news_confirmation_explicit_attestation_required": True,
            "news_confirmation_inventory_digest_required": True,
            "news_confirmation_state": (
                news_status.get("week_confirmation_state")
                if isinstance(news_status, dict)
                else "starting"
            ),
            "news_confirmation_action_required": (
                news_status.get("confirmation_action_required")
                if isinstance(news_status, dict)
                else True
            ),
            "news_confirmation_current_week_event_count": (
                news_status.get("current_week_event_count")
                if isinstance(news_status, dict)
                else None
            ),
        }
    )
    return status


# v36 resolves these names dynamically inside its existing safety loader.
confirmation._week_confirmation = _week_confirmation_v95
confirmation._apply_confirmation = _apply_confirmation_v95
confirmation._confirm_current_week = _confirm_current_week_v95

core.LiveTrader.answer = _answer_v95  # type: ignore[method-assign]
core.LiveTrader.runtime_status = _runtime_status_v95  # type: ignore[method-assign]
core.LiveTrader.confirm_news_week = _confirm_current_week_v95  # type: ignore[attr-defined]
core.LiveTrader.news_confirmation_status = _workflow_status_v95  # type: ignore[attr-defined]
