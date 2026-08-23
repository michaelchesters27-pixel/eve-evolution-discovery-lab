from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone
from typing import Any

from app.services import live_trader as core
from app.services import live_trader_historical_runtime_v30 as runtime
from app.services import live_trader_red_folder_news_v35 as news
from app.services import live_trader_trade_lock_v28 as lock

OUTCOME_VERSION = "eve-live-weekly-trade-outcomes-v1"
REVIEW_VERSION = "eve-live-post-trade-review-v1"
SUMMARY_CACHE_SECONDS = 15
TERMINAL = {"won", "lost", "invalidated", "expired"}
OPEN = {"pending", "active"}

_current_refresh = core.LiveTrader.refresh_state
_current_learning_summary = core.LiveTrader.learning_summary
_current_runtime_status = core.LiveTrader.runtime_status


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


def _number(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _week_window(at: datetime) -> tuple[date, datetime, datetime]:
    local = at.astimezone(news.UK)
    days_since_sunday = (local.date().weekday() + 1) % 7
    week_start = local.date() - timedelta(days=days_since_sunday)
    next_week = week_start + timedelta(days=7)
    start_local = datetime.combine(week_start, time.min, tzinfo=news.UK)
    end_local = datetime.combine(next_week, time.min, tzinfo=news.UK)
    return week_start, start_local.astimezone(timezone.utc), end_local.astimezone(timezone.utc)


def _campaign_realised_r(campaign: dict[str, Any]) -> float:
    status = str(campaign.get("status") or "").lower()
    if status == "lost":
        return -1.0
    if status != "won":
        return 0.0
    rr = _number(campaign.get("risk_reward"), 0.0)
    if rr > 0:
        return round(rr, 3)
    entry = _number(campaign.get("entry"))
    stop = _number(campaign.get("stop"))
    target = _number(campaign.get("target"))
    risk = abs(entry - stop)
    reward = abs(target - entry)
    return round(reward / risk, 3) if risk > 0 else 0.0


def _context_snapshot(state: dict[str, Any]) -> dict[str, Any]:
    bias = dict(state.get("bias") or {})
    market = dict(state.get("market") or {})
    liquidity = dict(state.get("liquidity") or {})
    trade = dict(state.get("trade") or {})
    news_risk = dict(state.get("news_risk") or {})
    return {
        "setup_family": state.get("setup_family"),
        "setup_family_descriptor": dict(state.get("setup_family_descriptor") or {}),
        "bias": {
            "overall": bias.get("overall"),
            "confidence": bias.get("confidence"),
            "htf_alignment": bias.get("htf_alignment"),
            "all_alignment": bias.get("all_alignment"),
        },
        "market": {
            "session": market.get("session"),
            "regime": market.get("regime"),
            "atr": market.get("atr"),
            "fabric_time": market.get("fabric_time"),
        },
        "liquidity": {
            "primary_event": dict(liquidity.get("primary_event") or {}),
        },
        "trade": {
            "side": trade.get("side"),
            "order_type": trade.get("order_type"),
            "entry": trade.get("entry"),
            "stop": trade.get("stop"),
            "target": trade.get("target"),
            "risk_reward": trade.get("risk_reward"),
            "confidence": trade.get("confidence"),
        },
        "news": {
            "status": news_risk.get("status"),
            "week_confirmed": news_risk.get("week_confirmed"),
            "active_event_ids": list(news_risk.get("active_event_ids") or []),
        },
        "captured_at": core.utc_now().isoformat(),
    }


def _publication_is_current(campaign: dict[str, Any]) -> bool:
    created = _parse_time(campaign.get("created_at"))
    if created is None:
        return False
    return abs((core.utc_now() - created).total_seconds()) <= 120


async def _capture_publication_context(self: core.LiveTrader, state: dict[str, Any]) -> None:
    campaign = getattr(self, "_live_campaign", None)
    if not isinstance(campaign, dict) or str(campaign.get("status") or "").lower() not in OPEN | TERMINAL:
        return
    if campaign.get("outcome_learning_v38"):
        return

    if _publication_is_current(campaign):
        snapshot = _context_snapshot(state)
        campaign["setup_family"] = snapshot.get("setup_family")
        campaign["setup_family_descriptor"] = snapshot.get("setup_family_descriptor") or {}
        quality = "publication_snapshot"
    else:
        # Never pretend the current market is the original context for a campaign
        # created before this feature existed.
        snapshot = {
            "trade": dict(campaign.get("published_trade") or {}),
            "captured_at": core.utc_now().isoformat(),
            "note": "Legacy campaign predates v38; original setup-family context was not reconstructed from later market state.",
        }
        quality = "legacy_partial"

    campaign["outcome_learning_v38"] = {
        "version": OUTCOME_VERSION,
        "publication_context_quality": quality,
        "publication_context": snapshot,
    }
    self._live_campaign = campaign
    self._live_campaign_dirty = True
    try:
        await lock._persist_campaign(self, campaign)
    except Exception as exc:
        core.logger.warning("Live Trader v3.8 could not persist campaign learning context: %s", exc)


def _review_payload(campaign: dict[str, Any], state: dict[str, Any]) -> dict[str, Any]:
    status = str(campaign.get("status") or "").lower()
    realised_r = _campaign_realised_r(campaign)
    learning = dict(campaign.get("outcome_learning_v38") or {})
    context_quality = str(learning.get("publication_context_quality") or "unknown")
    signal = "negative" if status == "lost" else "positive" if status == "won" else "neutral"
    if status == "lost":
        lesson = (
            "This published execution lost 1R. Preserve it as negative execution evidence. One loss must not rewrite EVE's rules; "
            "repeated independent losses in the same semantic family/order type should be compared with Historical Academy challenger evidence before execution preference changes."
        )
    elif status == "won":
        lesson = (
            "This published execution reached its target. Preserve it as positive execution evidence without treating one win as proof of an edge."
        )
    elif status == "invalidated":
        lesson = (
            "The setup invalidated before entry. Preserve this as setup-selection evidence, not a trading loss, because capital was never exposed."
        )
    else:
        lesson = (
            "The setup expired without triggering. Preserve this as opportunity/entry-selection evidence, not a trading win or loss."
        )
    return {
        "signal": signal,
        "priority": "high" if status == "lost" else "normal",
        "lesson": lesson,
        "context_quality": context_quality,
        "order_type": campaign.get("order_type"),
        "side": campaign.get("side"),
        "risk_reward": campaign.get("risk_reward"),
        "realised_r": realised_r,
        "evidence_role": "execution_postmortem_not_second_independent_sample",
        "forward_family_policy": (
            "The existing forward-learning family/governor remains the authority for confidence and veto decisions. This review labels the exact locked-campaign execution outcome so losses can be diagnosed without double-counting the same live experience."
        ),
        "completed_state_family": state.get("setup_family"),
    }


async def _ensure_review(self: core.LiveTrader, state: dict[str, Any]) -> None:
    campaign = getattr(self, "_live_campaign", None)
    if not isinstance(campaign, dict):
        campaign = state.get("trade_campaign")
    if not isinstance(campaign, dict):
        return
    status = str(campaign.get("status") or "").lower()
    if status not in TERMINAL:
        return
    campaign_id = str(campaign.get("id") or "")
    completed_at = _parse_time(campaign.get("completed_at"))
    if not campaign_id or completed_at is None:
        return

    reviewed = getattr(self, "_trade_reviews_written_v38", set())
    if campaign_id in reviewed:
        return
    week_start, _, _ = _week_window(completed_at)
    learning = dict(campaign.get("outcome_learning_v38") or {})
    publication = dict(learning.get("publication_context") or {})
    family = campaign.get("setup_family")
    descriptor = dict(campaign.get("setup_family_descriptor") or {})
    review = _review_payload(campaign, state)
    try:
        await self.repo.client.upsert(
            "live_trader_trade_reviews",
            {
                "campaign_id": campaign_id,
                "symbol": self.symbol,
                "completed_at": completed_at.isoformat(),
                "week_start": week_start.isoformat(),
                "outcome": status,
                "triggered": bool(campaign.get("triggered_at")),
                "realised_r": _campaign_realised_r(campaign),
                "setup_family": family,
                "setup_family_descriptor": descriptor,
                "publication_context": publication,
                "completion_context": _context_snapshot(state),
                "review": review,
                "review_version": REVIEW_VERSION,
                "updated_at": core.utc_now().isoformat(),
            },
            on_conflict="campaign_id",
            return_rows=False,
        )
        reviewed = set(reviewed)
        reviewed.add(campaign_id)
        self._trade_reviews_written_v38 = reviewed
    except Exception as exc:
        core.logger.warning("Live Trader v3.8 could not persist post-trade review: %s", exc)
        self._trade_review_last_error_v38 = str(exc)[:240]


async def _weekly_outcomes(self: core.LiveTrader, *, force: bool = False) -> dict[str, Any]:
    now = core.utc_now()
    cached_at = getattr(self, "_weekly_outcomes_cache_at_v38", None)
    cached = getattr(self, "_weekly_outcomes_cache_v38", None)
    if (
        not force
        and isinstance(cached_at, datetime)
        and isinstance(cached, dict)
        and (now - cached_at).total_seconds() < SUMMARY_CACHE_SECONDS
    ):
        return dict(cached)

    week_start, start_utc, end_utc = _week_window(now)
    try:
        completed = await self.repo.client.get(
            "live_trader_campaigns",
            params={
                "select": "id,status,side,order_type,entry,stop,target,risk_reward,created_at,triggered_at,completed_at,result,campaign",
                "symbol": f"eq.{self.symbol}",
                "completed_at": f"gte.{start_utc.isoformat()}",
                "and": f"(completed_at.lt.{end_utc.isoformat()})",
                "order": "completed_at.desc",
                "limit": "100",
            },
        )
        open_rows = await self.repo.client.get(
            "live_trader_campaigns",
            params={
                "select": "id,status,side,order_type,entry,stop,target,risk_reward,created_at,triggered_at,completed_at,result,campaign",
                "symbol": f"eq.{self.symbol}",
                "status": "in.(pending,active)",
                "order": "created_at.desc",
                "limit": "10",
            },
        )
        reviews = await self.repo.client.get(
            "live_trader_trade_reviews",
            params={
                "select": "campaign_id,outcome,realised_r,setup_family,review,completed_at",
                "symbol": f"eq.{self.symbol}",
                "week_start": f"eq.{week_start.isoformat()}",
                "order": "completed_at.desc",
                "limit": "100",
            },
        )
    except Exception as exc:
        core.logger.warning("Live Trader v3.8 could not build weekly outcome summary: %s", exc)
        return {
            "version": OUTCOME_VERSION,
            "available": False,
            "error": str(exc)[:240],
            "week_start": week_start.isoformat(),
            "week_end": (week_start + timedelta(days=6)).isoformat(),
        }

    terminal_rows: list[dict[str, Any]] = []
    for row in completed or []:
        campaign = dict((row or {}).get("campaign") or {})
        merged = {**dict(row or {}), **campaign}
        status = str(merged.get("status") or "").lower()
        if status in TERMINAL:
            terminal_rows.append(merged)

    wins = sum(1 for row in terminal_rows if str(row.get("status") or "").lower() == "won")
    losses = sum(1 for row in terminal_rows if str(row.get("status") or "").lower() == "lost")
    invalidated = sum(1 for row in terminal_rows if str(row.get("status") or "").lower() == "invalidated")
    expired = sum(1 for row in terminal_rows if str(row.get("status") or "").lower() == "expired")
    triggered_finished = wins + losses
    net_r = round(sum(_campaign_realised_r(row) for row in terminal_rows), 3)
    win_rate = round((wins / triggered_finished) * 100.0, 1) if triggered_finished else None
    result_label = "PROFIT" if net_r > 0 else "LOSS" if net_r < 0 else "FLAT"
    review_rows = list(reviews or [])
    loss_reviews = sum(1 for row in review_rows if str((row or {}).get("outcome") or "") == "lost")

    recent = []
    for row in terminal_rows[:10]:
        recent.append(
            {
                "campaign_id": row.get("id"),
                "status": row.get("status"),
                "side": row.get("side"),
                "order_type": row.get("order_type"),
                "entry": row.get("entry"),
                "stop": row.get("stop"),
                "target": row.get("target"),
                "risk_reward": row.get("risk_reward"),
                "realised_r": _campaign_realised_r(row),
                "completed_at": row.get("completed_at"),
                "result": row.get("result"),
            }
        )

    opens = []
    for row in open_rows or []:
        campaign = dict((row or {}).get("campaign") or {})
        merged = {**dict(row or {}), **campaign}
        opens.append(
            {
                "campaign_id": merged.get("id"),
                "status": merged.get("status"),
                "side": merged.get("side"),
                "order_type": merged.get("order_type"),
                "entry": merged.get("entry"),
                "stop": merged.get("stop"),
                "target": merged.get("target"),
                "risk_reward": merged.get("risk_reward"),
                "created_at": merged.get("created_at"),
                "triggered_at": merged.get("triggered_at"),
            }
        )

    summary = {
        "version": OUTCOME_VERSION,
        "review_version": REVIEW_VERSION,
        "available": True,
        "week_start": week_start.isoformat(),
        "week_end": (week_start + timedelta(days=6)).isoformat(),
        "completed_campaigns": len(terminal_rows),
        "triggered_finished": triggered_finished,
        "wins": wins,
        "losses": losses,
        "invalidated": invalidated,
        "expired": expired,
        "win_rate_pct": win_rate,
        "net_r": net_r,
        "result_label": result_label,
        "open_campaigns": len(opens),
        "open": opens,
        "recent": recent,
        "post_trade_reviews": len(review_rows),
        "loss_reviews": loss_reviews,
        "learning_policy": (
            "Every finished locked campaign gets one idempotent execution review. Wins and losses are expressed in R, not cash P/L. "
            "A target win contributes its published R:R, a stop loss contributes -1R, and invalidated/expired untriggered ideas contribute 0R. "
            "Loss reviews are retained for execution diagnosis but are not double-counted as a second independent sample in EVE's forward family governor."
        ),
        "cash_profit_known": False,
        "cash_profit_note": "Cash P/L is not inferred because Live Trader does not know the actual stake/fill. Net R is the honest strategy-level weekly result.",
        "last_review_error": getattr(self, "_trade_review_last_error_v38", None),
    }
    self._weekly_outcomes_cache_at_v38 = now
    self._weekly_outcomes_cache_v38 = dict(summary)
    return summary


async def _refresh_v38(self: core.LiveTrader, *, force_rows: bool = False) -> dict[str, Any]:
    state = await _current_refresh(self, force_rows=force_rows)
    await _capture_publication_context(self, state)
    await _ensure_review(self, state)
    # A just-finished trade should be visible immediately rather than waiting for cache expiry.
    campaign = state.get("trade_campaign")
    if isinstance(campaign, dict) and str(campaign.get("status") or "").lower() in TERMINAL:
        self._weekly_outcomes_cache_at_v38 = None
    return state


async def _learning_summary_v38(self: core.LiveTrader) -> dict[str, Any]:
    summary = dict(await _current_learning_summary(self))
    weekly = await _weekly_outcomes(self)
    summary["weekly_trade_outcomes"] = weekly
    summary["trade_outcome_learning"] = {
        "version": REVIEW_VERSION,
        "reviews_recorded_this_week": weekly.get("post_trade_reviews", 0),
        "losses_reviewed_this_week": weekly.get("loss_reviews", 0),
        "policy": weekly.get("learning_policy"),
    }
    return summary


def _runtime_status_v38(self: core.LiveTrader) -> dict[str, Any]:
    status = dict(_current_runtime_status(self))
    status.update(
        {
            "weekly_trade_outcome_version": OUTCOME_VERSION,
            "post_trade_review_version": REVIEW_VERSION,
            "post_trade_review_last_error": getattr(self, "_trade_review_last_error_v38", None),
        }
    )
    return status


core.LiveTrader.refresh_state = _refresh_v38  # type: ignore[method-assign]
core.LiveTrader.learning_summary = _learning_summary_v38  # type: ignore[method-assign]
core.LiveTrader.runtime_status = _runtime_status_v38  # type: ignore[method-assign]
core.LiveTrader.weekly_trade_outcomes = _weekly_outcomes  # type: ignore[attr-defined]

# Keep the established compatibility aliases pointing at the newest runtime refresh.
lock._refresh_state_v28 = _refresh_v38
runtime._refresh_state_v30 = _refresh_v38
