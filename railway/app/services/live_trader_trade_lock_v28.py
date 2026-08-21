from __future__ import annotations

import hashlib
import re
from datetime import datetime, timedelta, timezone
from typing import Any

from app.services import live_trader as core

CAMPAIGN_VERSION = "eve-live-trade-lock-v1"
PENDING_EXPIRY_MINUTES = 180
TERMINAL_HOLD_SECONDS = 60
OPEN_STATUSES = {"pending", "active"}
TERMINAL_STATUSES = {"won", "lost", "invalidated", "expired"}

_original_refresh_state = core.LiveTrader.refresh_state
_original_trade_idea = core.LiveTrader._trade_idea
_original_calibration = core.LiveTrader._calibration
_original_persist_state = core.LiveTrader._maybe_persist_state
_original_runtime_status = core.LiveTrader.runtime_status
_original_trade_sentence = core.LiveTrader._trade_sentence
_original_opinion_text = core.LiveTrader._opinion_text


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


def _num(value: Any, default: float = 0.0) -> float:
    return core.number(value, default)


def _actionable(trade: dict[str, Any] | None) -> bool:
    if not isinstance(trade, dict):
        return False
    order_type = str(trade.get("order_type") or "none").lower()
    action = str(trade.get("action") or "").upper()
    return order_type != "none" and action not in {"", "WAIT", "NO TRADE"}


def _invalidation_price(trade: dict[str, Any]) -> float:
    text = str(trade.get("invalidation") or "")
    matches = re.findall(r"(?<!\d)(\d{3,6}(?:\.\d+)?)(?!\d)", text)
    if matches:
        return _num(matches[-1], _num(trade.get("stop")))
    return _num(trade.get("stop"))


def _campaign_id(symbol: str, created_at: str, trade: dict[str, Any]) -> str:
    raw = "|".join(
        [
            str(symbol),
            str(created_at),
            str(trade.get("side") or ""),
            str(trade.get("order_type") or ""),
            f"{_num(trade.get('entry')):.5f}",
            f"{_num(trade.get('stop')):.5f}",
            f"{_num(trade.get('target')):.5f}",
        ]
    )
    return hashlib.sha1(raw.encode()).hexdigest()[:20]


def _new_campaign(self: core.LiveTrader, trade: dict[str, Any], price: float) -> dict[str, Any]:
    now = core.utc_now()
    created_at = now.isoformat()
    order_type = str(trade.get("order_type") or "none").lower()
    status = "active" if order_type == "market" else "pending"
    side = str(trade.get("side") or ("BUY" if "buy" in order_type else "SELL")).upper()
    campaign = {
        "version": CAMPAIGN_VERSION,
        "id": _campaign_id(self.symbol, created_at, trade),
        "symbol": self.symbol,
        "status": status,
        "side": side,
        "order_type": order_type,
        "entry": round(_num(trade.get("entry")), 3),
        "stop": round(_num(trade.get("stop")), 3),
        "target": round(_num(trade.get("target")), 3),
        "risk_reward": trade.get("risk_reward"),
        "confidence": trade.get("confidence"),
        "reason": trade.get("reason") or "",
        "invalidation": trade.get("invalidation") or "",
        "invalidation_price": round(_invalidation_price(trade), 3),
        "created_at": created_at,
        "expires_at": (now + timedelta(minutes=PENDING_EXPIRY_MINUTES)).isoformat() if status == "pending" else None,
        "triggered_at": created_at if status == "active" else None,
        "completed_at": None,
        "result": None,
        "last_price": round(price, 3),
        "last_checked_at": created_at,
        "published_trade": {
            key: trade.get(key)
            for key in (
                "action",
                "side",
                "order_type",
                "entry",
                "stop",
                "target",
                "risk_reward",
                "confidence",
                "reason",
                "invalidation",
                "manual_only",
                "automatic_order_placement",
                "market_event",
            )
            if key in trade
        },
    }
    self._live_campaign_dirty = True
    self._live_campaign_new_v28 = True
    return campaign


def _complete(campaign: dict[str, Any], status: str, result: str, price: float, now: datetime) -> dict[str, Any]:
    campaign["status"] = status
    campaign["result"] = result
    campaign["completed_at"] = now.isoformat()
    campaign["last_price"] = round(price, 3)
    campaign["last_checked_at"] = now.isoformat()
    return campaign


def _advance_campaign(
    self: core.LiveTrader,
    campaign: dict[str, Any],
    price: float,
    *,
    allow_price_events: bool = True,
) -> dict[str, Any] | None:
    now = core.utc_now()
    status = str(campaign.get("status") or "").lower()

    if status in TERMINAL_STATUSES:
        completed_at = _parse_time(campaign.get("completed_at"))
        if completed_at and (now - completed_at).total_seconds() >= TERMINAL_HOLD_SECONDS:
            self._live_campaign = None
            return None
        return campaign

    before = dict(campaign)
    side = str(campaign.get("side") or "").upper()
    order_type = str(campaign.get("order_type") or "").lower()
    entry = _num(campaign.get("entry"))
    stop = _num(campaign.get("stop"))
    target = _num(campaign.get("target"))
    invalidation = _num(campaign.get("invalidation_price"), stop)

    if status == "pending":
        expires_at = _parse_time(campaign.get("expires_at"))
        if expires_at is not None and now >= expires_at:
            campaign = _complete(campaign, "expired", "NO TRIGGER — SETUP EXPIRED", price, now)
        elif allow_price_events:
            triggered = False
            invalidated = False
            if order_type == "buy_stop":
                invalidated = invalidation > 0 and price <= invalidation
                triggered = not invalidated and price >= entry
            elif order_type == "sell_stop":
                invalidated = invalidation > 0 and price >= invalidation
                triggered = not invalidated and price <= entry
            elif order_type == "buy_limit":
                triggered = price <= entry
            elif order_type == "sell_limit":
                triggered = price >= entry
            elif order_type == "market":
                triggered = True

            if invalidated:
                campaign = _complete(campaign, "invalidated", "CANCELLED — INVALID BEFORE ENTRY", price, now)
            elif triggered:
                campaign["status"] = "active"
                campaign["triggered_at"] = now.isoformat()

    if str(campaign.get("status") or "").lower() == "active" and allow_price_events:
        if side == "BUY":
            if stop > 0 and price <= stop:
                campaign = _complete(campaign, "lost", "LOSS — STOP HIT", price, now)
            elif target > 0 and price >= target:
                campaign = _complete(campaign, "won", "WIN — TARGET HIT", price, now)
        elif side == "SELL":
            if stop > 0 and price >= stop:
                campaign = _complete(campaign, "lost", "LOSS — STOP HIT", price, now)
            elif target > 0 and price <= target:
                campaign = _complete(campaign, "won", "WIN — TARGET HIT", price, now)

    campaign["last_price"] = round(price, 3)
    campaign["last_checked_at"] = now.isoformat()
    if campaign != before:
        self._live_campaign_dirty = True
    return campaign


def _campaign_trade(campaign: dict[str, Any]) -> dict[str, Any]:
    published = dict(campaign.get("published_trade") or {})
    status = str(campaign.get("status") or "").lower()
    side = str(campaign.get("side") or "").upper()
    action_by_status = {
        "pending": str(published.get("action") or f"{side} ORDER"),
        "active": f"{side} ACTIVE",
        "won": "WIN — TARGET HIT",
        "lost": "LOSS — STOP HIT",
        "invalidated": "CANCEL — INVALIDATED",
        "expired": "EXPIRED — NO TRIGGER",
    }
    published.update(
        {
            "action": action_by_status.get(status, published.get("action") or "WAIT"),
            "side": side,
            "order_type": campaign.get("order_type"),
            "entry": campaign.get("entry"),
            "stop": campaign.get("stop"),
            "target": campaign.get("target"),
            "risk_reward": campaign.get("risk_reward"),
            "confidence": campaign.get("confidence"),
            "reason": campaign.get("reason") or "",
            "invalidation": campaign.get("invalidation") or "",
            "manual_only": True,
            "automatic_order_placement": False,
            "campaign_id": campaign.get("id"),
            "campaign_version": CAMPAIGN_VERSION,
            "campaign_status": status,
            "campaign_locked": status in OPEN_STATUSES,
            "campaign_result": campaign.get("result"),
            "campaign_created_at": campaign.get("created_at"),
            "campaign_triggered_at": campaign.get("triggered_at"),
            "campaign_completed_at": campaign.get("completed_at"),
            "campaign_expires_at": campaign.get("expires_at"),
            "invalidation_price": campaign.get("invalidation_price"),
        }
    )
    return published


def _campaign_setup(campaign: dict[str, Any]) -> dict[str, Any]:
    status = str(campaign.get("status") or "").lower()
    messages = {
        "pending": (
            "IDEA LOCKED",
            "One trade idea is locked. EVE is following this exact entry, stop and target and will not issue another idea until it finishes.",
        ),
        "active": (
            "TRADE ACTIVE",
            "The locked idea has triggered. EVE is following it to the published target or stop; no replacement trade can be issued.",
        ),
        "won": ("TRADE WON", "The locked campaign reached its published target."),
        "lost": ("TRADE LOST", "The locked campaign reached its published stop."),
        "invalidated": ("IDEA INVALIDATED", "The pending idea hit its published pre-entry invalidation before triggering."),
        "expired": ("IDEA EXPIRED", "The pending idea did not trigger within its three-hour validity window."),
    }
    label, reason = messages.get(status, ("WATCHING", "EVE is monitoring the locked campaign."))
    return {"status": label, "reason": reason}


def _trade_idea_v28(
    self: core.LiveTrader,
    price: float,
    atr: float,
    bias: dict[str, Any],
    zones: dict[str, list[dict[str, Any]]],
    liquidity: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, Any]]:
    campaign = getattr(self, "_live_campaign", None)
    if isinstance(campaign, dict):
        campaign = _advance_campaign(self, campaign, price, allow_price_events=self._feed_is_fresh())
        self._live_campaign = campaign
        if isinstance(campaign, dict):
            return _campaign_setup(campaign), _campaign_trade(campaign)

    setup, trade = _original_trade_idea(self, price, atr, bias, zones, liquidity)
    setup = dict(setup or {})
    trade = dict(trade or {})
    if not _actionable(trade):
        return setup, trade

    if not self._feed_is_fresh():
        return (
            {"status": "WATCHING", "reason": "A trade candidate exists, but the live feed is not fresh enough to publish and lock it."},
            {
                "action": "WAIT",
                "order_type": "none",
                "reason": "EVE will not publish a new campaign from a stale price feed.",
                "manual_only": True,
            },
        )

    campaign = _new_campaign(self, trade, price)
    self._live_campaign = campaign
    return _campaign_setup(campaign), _campaign_trade(campaign)


async def _restore_campaign(self: core.LiveTrader) -> None:
    if getattr(self, "_live_campaign_loaded_v28", False):
        return
    self._live_campaign_loaded_v28 = True
    self._live_campaign = None
    self._live_campaign_dirty = False
    self._live_campaign_new_v28 = False
    self._live_campaign_last_persisted_fingerprint = None
    try:
        open_rows = await self.repo.client.get(
            "live_trader_campaigns",
            params={
                "select": "campaign,status,updated_at",
                "symbol": f"eq.{self.symbol}",
                "status": "in.(pending,active)",
                "order": "updated_at.desc",
                "limit": "1",
            },
        )
        if open_rows:
            self._live_campaign = dict((open_rows[0] or {}).get("campaign") or {})
            return
        rows = await self.repo.client.get(
            "live_trader_campaigns",
            params={
                "select": "campaign,status,updated_at",
                "symbol": f"eq.{self.symbol}",
                "order": "updated_at.desc",
                "limit": "1",
            },
        )
    except Exception as exc:
        core.logger.warning("Live Trader v2.8 could not restore campaign ledger: %s", exc)
        return
    if not rows:
        return
    row = dict(rows[0] or {})
    campaign = dict(row.get("campaign") or {})
    status = str(campaign.get("status") or row.get("status") or "").lower()
    if status in TERMINAL_STATUSES:
        completed_at = _parse_time(campaign.get("completed_at"))
        if completed_at and (core.utc_now() - completed_at).total_seconds() < TERMINAL_HOLD_SECONDS:
            self._live_campaign = campaign


async def _refresh_state_v28(self: core.LiveTrader, *, force_rows: bool = False) -> dict[str, Any]:
    await _restore_campaign(self)
    state = await _original_refresh_state(self, force_rows=force_rows)
    campaign = getattr(self, "_live_campaign", None)
    if isinstance(campaign, dict):
        state["trade_campaign"] = dict(campaign)
        state["trade_lock"] = {
            "version": CAMPAIGN_VERSION,
            "one_trade_at_a_time": True,
            "status": campaign.get("status"),
            "campaign_id": campaign.get("id"),
            "new_ideas_blocked": str(campaign.get("status") or "").lower() in OPEN_STATUSES,
            "pending_expiry_minutes": PENDING_EXPIRY_MINUTES,
            "terminal_hold_seconds": TERMINAL_HOLD_SECONDS,
        }
    else:
        state["trade_campaign"] = None
        state["trade_lock"] = {
            "version": CAMPAIGN_VERSION,
            "one_trade_at_a_time": True,
            "status": "searching",
            "campaign_id": None,
            "new_ideas_blocked": False,
            "pending_expiry_minutes": PENDING_EXPIRY_MINUTES,
            "terminal_hold_seconds": TERMINAL_HOLD_SECONDS,
        }
    self._latest_state = state
    return state


async def _calibration_v28(self: core.LiveTrader, signature: str) -> dict[str, Any]:
    learning = await _original_calibration(self, signature)
    campaign = getattr(self, "_live_campaign", None)
    state = getattr(self, "_learning_governor_pending_state", None)
    if (
        isinstance(campaign, dict)
        and str(campaign.get("status") or "").lower() in OPEN_STATUSES
        and not getattr(self, "_live_campaign_new_v28", False)
        and isinstance(state, dict)
    ):
        governor = dict(state.get("learning_governor") or {})
        if governor.get("decision") == "veto":
            governor["decision"] = "locked_campaign_continues"
            governor["reason"] = (
                "This family would be vetoed for a new trade, but the one-trade rule forbids EVE from rewriting or cancelling an already published campaign."
            )
            state["learning_governor"] = governor
            state["setup"] = _campaign_setup(campaign)
            state["trade"] = _campaign_trade(campaign)
    return learning


def _campaign_fingerprint(campaign: dict[str, Any]) -> str:
    raw = "|".join(
        [
            str(campaign.get("id") or ""),
            str(campaign.get("status") or ""),
            str(campaign.get("triggered_at") or ""),
            str(campaign.get("completed_at") or ""),
            str(campaign.get("result") or ""),
            str(campaign.get("last_price") or ""),
        ]
    )
    return hashlib.sha1(raw.encode()).hexdigest()


async def _persist_campaign(self: core.LiveTrader, campaign: dict[str, Any]) -> None:
    fingerprint = _campaign_fingerprint(campaign)
    if (
        not getattr(self, "_live_campaign_dirty", False)
        and fingerprint == getattr(self, "_live_campaign_last_persisted_fingerprint", None)
    ):
        return
    try:
        await self.repo.client.upsert(
            "live_trader_campaigns",
            {
                "id": campaign.get("id"),
                "symbol": self.symbol,
                "status": campaign.get("status"),
                "side": campaign.get("side"),
                "order_type": campaign.get("order_type"),
                "entry": campaign.get("entry"),
                "stop": campaign.get("stop"),
                "target": campaign.get("target"),
                "risk_reward": campaign.get("risk_reward"),
                "confidence": campaign.get("confidence"),
                "created_at": campaign.get("created_at"),
                "expires_at": campaign.get("expires_at"),
                "triggered_at": campaign.get("triggered_at"),
                "completed_at": campaign.get("completed_at"),
                "result": campaign.get("result"),
                "campaign": campaign,
                "updated_at": core.utc_now().isoformat(),
            },
            on_conflict="id",
        )
        self._live_campaign_last_persisted_fingerprint = fingerprint
        self._live_campaign_dirty = False
        self._live_campaign_new_v28 = False
    except Exception as exc:
        core.logger.warning("Live Trader v2.8 could not persist campaign ledger: %s", exc)


async def _maybe_persist_state_v28(self: core.LiveTrader, state: dict[str, Any]) -> None:
    campaign = getattr(self, "_live_campaign", None)
    governor = dict(state.get("learning_governor") or {})
    if (
        isinstance(campaign, dict)
        and getattr(self, "_live_campaign_new_v28", False)
        and governor.get("decision") == "veto"
    ):
        self._live_campaign = None
        self._live_campaign_dirty = False
        self._live_campaign_new_v28 = False
        state["trade_campaign"] = None
        state["trade_lock"] = {
            "version": CAMPAIGN_VERSION,
            "one_trade_at_a_time": True,
            "status": "searching",
            "campaign_id": None,
            "new_ideas_blocked": False,
        }
        await _original_persist_state(self, state)
        return

    if isinstance(campaign, dict):
        state["trade_campaign"] = dict(campaign)
        state["trade_lock"] = {
            "version": CAMPAIGN_VERSION,
            "one_trade_at_a_time": True,
            "status": campaign.get("status"),
            "campaign_id": campaign.get("id"),
            "new_ideas_blocked": str(campaign.get("status") or "").lower() in OPEN_STATUSES,
        }
        await _persist_campaign(self, campaign)
    await _original_persist_state(self, state)


def _campaign_sentence(state: dict[str, Any]) -> str | None:
    campaign = state.get("trade_campaign")
    if not isinstance(campaign, dict):
        return None
    status = str(campaign.get("status") or "").lower()
    side = str(campaign.get("side") or "")
    entry = _num(campaign.get("entry"))
    stop = _num(campaign.get("stop"))
    target = _num(campaign.get("target"))
    if status == "pending":
        return (
            f"Micky, I already have one locked trade idea: {side} {str(campaign.get('order_type') or '').replace('_',' ').upper()}, "
            f"entry {entry:.2f}, stop {stop:.2f}, target {target:.2f}. It has not triggered yet. "
            "I will not give you another trade idea unless this one triggers and finishes, invalidates, or expires."
        )
    if status == "active":
        return (
            f"Micky, the locked {side} trade is active. Entry {entry:.2f}, stop {stop:.2f}, target {target:.2f}. "
            "I am following this trade only until target or stop is hit."
        )
    if status == "won":
        return f"Micky, the locked trade is finished — target hit. WIN. Entry {entry:.2f}, target {target:.2f}."
    if status == "lost":
        return f"Micky, the locked trade is finished — stop hit. LOSS. Entry {entry:.2f}, stop {stop:.2f}."
    if status == "invalidated":
        return "Micky, the pending trade idea is finished and cancelled because its published invalidation was hit before entry."
    if status == "expired":
        return "Micky, the pending trade idea is finished and expired without triggering."
    return None


def _trade_sentence_v28(self: core.LiveTrader, state: dict[str, Any]) -> str:
    locked = _campaign_sentence(state)
    if locked:
        return locked
    return _original_trade_sentence(self, state)


def _opinion_text_v28(self: core.LiveTrader, state: dict[str, Any]) -> str:
    base = _original_opinion_text(self, state)
    campaign = state.get("trade_campaign")
    if not isinstance(campaign, dict):
        trade = state.get("trade") or {}
        if trade.get("campaign_id"):
            campaign = getattr(self, "_live_campaign", None)
    if not isinstance(campaign, dict):
        return base
    status = str(campaign.get("status") or "").lower()
    if status == "pending":
        return f"{base} One-trade lock is active: I am following the published idea and will not replace it."
    if status == "active":
        return f"{base} The locked trade has triggered; I am following its original stop and target only."
    if status in TERMINAL_STATUSES:
        return f"{base} The previous locked campaign is finished: {campaign.get('result') or status}."
    return base


def _runtime_status_v28(self: core.LiveTrader) -> dict[str, Any]:
    status = dict(_original_runtime_status(self))
    campaign = getattr(self, "_live_campaign", None)
    status.update(
        {
            "trade_lock_version": CAMPAIGN_VERSION,
            "one_trade_at_a_time": True,
            "pending_campaign_expiry_minutes": PENDING_EXPIRY_MINUTES,
            "campaign_status": campaign.get("status") if isinstance(campaign, dict) else "searching",
            "campaign_id": campaign.get("id") if isinstance(campaign, dict) else None,
            "new_trade_ideas_blocked": (
                str(campaign.get("status") or "").lower() in OPEN_STATUSES if isinstance(campaign, dict) else False
            ),
        }
    )
    return status


core.LiveTrader._trade_idea = _trade_idea_v28  # type: ignore[method-assign]
core.LiveTrader._calibration = _calibration_v28  # type: ignore[method-assign]
core.LiveTrader.refresh_state = _refresh_state_v28  # type: ignore[method-assign]
core.LiveTrader._maybe_persist_state = _maybe_persist_state_v28  # type: ignore[method-assign]
core.LiveTrader._trade_sentence = _trade_sentence_v28  # type: ignore[method-assign]
core.LiveTrader._opinion_text = _opinion_text_v28  # type: ignore[method-assign]
core.LiveTrader.runtime_status = _runtime_status_v28  # type: ignore[method-assign]
