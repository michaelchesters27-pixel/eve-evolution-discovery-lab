from __future__ import annotations

from datetime import timedelta
from typing import Any

from app.services import live_trader as core
from app.services import live_trader_clear_bias_gate_v45 as clear_gate
from app.services import live_trader_execution_forensics_v47 as forensics
from app.services import live_trader_execution_integrity_v39 as integrity
from app.services import live_trader_trade_lock_v28 as lock
from app.services.live_trader_execution_forensics_metrics_v47 import bar_time, parse_time

GUARD_VERSION = "eve-live-zone-target-guard-v1"
TARGET_POLICY_VERSION = "eve-live-target-cap-v1"
TARGET_REPLAY_VERSION = "eve-live-target-replay-v1"
MAX_TARGET_R = 1.50
MAX_PENDING_AGE_MINUTES = 90
TARGET_REPLAY_R = (1.0, 1.25, 1.5, 2.0)

_current_trade_idea = core.LiveTrader._trade_idea
_current_runtime_status = core.LiveTrader.runtime_status
_base_new_campaign = lock._new_campaign
_base_build_forensics = forensics.build_forensics


def _num(value: Any, default: float = 0.0) -> float:
    return core.number(value, default)


def _zone_kind_for_side(side: str) -> str | None:
    side = str(side or "").upper()
    return "demand" if side == "BUY" else "supply" if side == "SELL" else None


def _preferred_zone(zones: dict[str, list[dict[str, Any]]], side: str) -> dict[str, Any] | None:
    kind = _zone_kind_for_side(side)
    if not kind:
        return None
    items = list(zones.get(kind) or [])
    return dict(items[0]) if items else None


def _zone_matches_entry(zone: dict[str, Any], side: str, entry: float, atr: float) -> bool:
    if not zone or entry <= 0:
        return False
    expected = _num(zone.get("high" if str(side).upper() == "BUY" else "low"))
    tolerance = max(0.05, atr * 0.08)
    return expected > 0 and abs(expected - entry) <= tolerance


def _bind_source_zone(campaign: dict[str, Any], zones: dict[str, list[dict[str, Any]]], atr: float) -> None:
    order_type = str(campaign.get("order_type") or "").lower()
    if order_type not in {"buy_limit", "sell_limit", "market"}:
        campaign["source_zone_required"] = False
        return

    side = str(campaign.get("side") or "").upper()
    zone = _preferred_zone(zones, side)
    campaign["source_zone_required"] = True
    if not zone:
        campaign["source_zone"] = None
        return

    entry = _num(campaign.get("entry"))
    if order_type != "market" and not _zone_matches_entry(zone, side, entry, atr):
        campaign["source_zone"] = None
        return

    campaign["source_zone"] = {
        "id": zone.get("id"),
        "kind": zone.get("kind") or _zone_kind_for_side(side),
        "low": zone.get("low"),
        "high": zone.get("high"),
        "quality": zone.get("quality"),
        "origin_time": zone.get("origin_time"),
        "bound_at": core.utc_now().isoformat(),
    }


def _apply_target_cap(trade: dict[str, Any]) -> dict[str, Any]:
    result = dict(trade or {})
    side = str(result.get("side") or "").upper()
    entry = _num(result.get("entry"))
    stop = _num(result.get("stop"))
    target = _num(result.get("target"))
    if side not in {"BUY", "SELL"} or entry <= 0 or stop <= 0 or target <= 0:
        return result

    risk = abs(entry - stop)
    if risk <= 0:
        return result

    current_r = ((target - entry) / risk) if side == "BUY" else ((entry - target) / risk)
    if current_r <= MAX_TARGET_R:
        result["target_policy"] = {
            "version": TARGET_POLICY_VERSION,
            "cap_r": MAX_TARGET_R,
            "applied": False,
            "original_target": round(target, 3),
            "original_r": round(current_r, 3),
        }
        return result

    capped_target = entry + risk * MAX_TARGET_R if side == "BUY" else entry - risk * MAX_TARGET_R
    result["structural_target"] = round(target, 3)
    result["target"] = round(capped_target, 3)
    result["risk_reward"] = round(MAX_TARGET_R, 2)
    result["target_policy"] = {
        "version": TARGET_POLICY_VERSION,
        "cap_r": MAX_TARGET_R,
        "applied": True,
        "original_target": round(target, 3),
        "original_r": round(current_r, 3),
        "reason": "Hardened-gate replay shows material deterioration above the 1R-1.5R target band.",
    }
    return result


def _new_campaign_v49(self: core.LiveTrader, trade: dict[str, Any], price: float) -> dict[str, Any]:
    context = dict(getattr(self, "_zone_target_context_v49", {}) or {})
    adjusted = _apply_target_cap(dict(trade or {}))
    campaign = _base_new_campaign(self, adjusted, price)
    zones = dict(context.get("zones") or {})
    atr = max(_num(context.get("atr")), 0.01)
    _bind_source_zone(campaign, zones, atr)
    campaign["target_policy"] = adjusted.get("target_policy")
    if adjusted.get("structural_target") is not None:
        campaign["structural_target"] = adjusted.get("structural_target")

    published = dict(campaign.get("published_trade") or {})
    if adjusted.get("target_policy") is not None:
        published["target_policy"] = adjusted.get("target_policy")
    if adjusted.get("structural_target") is not None:
        published["structural_target"] = adjusted.get("structural_target")
    campaign["published_trade"] = published
    return campaign


def _cancel_pending(
    self: core.LiveTrader,
    campaign: dict[str, Any],
    price: float,
    *,
    result: str,
    reason: str,
    code: str,
    detail: dict[str, Any] | None = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    now = core.utc_now()
    campaign = lock._complete(campaign, "invalidated", result, price, now)
    campaign["pending_revalidation"] = {
        "version": GUARD_VERSION,
        "reason": code,
        "message": reason,
        "cancelled_at": now.isoformat(),
        **(detail or {}),
    }
    self._live_campaign = campaign
    self._live_campaign_dirty = True
    trade = lock._campaign_trade(campaign)
    trade.update(
        {
            "action": "CANCEL — CONTEXT CHANGED",
            "order_type": "none",
            "reason": reason,
            "campaign_locked": False,
            "pending_revalidation": campaign["pending_revalidation"],
        }
    )
    return {"status": "IDEA CANCELLED", "reason": reason}, trade


def _revalidate_pending(
    self: core.LiveTrader,
    campaign: dict[str, Any],
    price: float,
    atr: float,
    bias: dict[str, Any],
    zones: dict[str, list[dict[str, Any]]],
    liquidity: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, Any]] | None:
    created = parse_time(campaign.get("created_at"))
    if created is not None and core.utc_now() - created >= timedelta(minutes=MAX_PENDING_AGE_MINUTES):
        return _cancel_pending(
            self,
            campaign,
            price,
            result="CANCELLED — PENDING IDEA AGED OUT BEFORE ENTRY",
            reason=f"Pending idea cancelled because it remained untriggered for {MAX_PENDING_AGE_MINUTES} minutes.",
            code="pending_age_limit",
            detail={"max_pending_age_minutes": MAX_PENDING_AGE_MINUTES},
        )

    order_type = str(campaign.get("order_type") or "").lower()
    side = str(campaign.get("side") or "").upper()
    if order_type in {"buy_limit", "sell_limit", "market"}:
        preferred = _preferred_zone(zones, side)
        source = dict(campaign.get("source_zone") or {})

        # Legacy pending campaigns created before v49 are allowed to bind only if
        # their exact entry still matches today's current best zone boundary.
        if not source:
            if preferred and _zone_matches_entry(preferred, side, _num(campaign.get("entry")), atr):
                _bind_source_zone(campaign, zones, atr)
                self._live_campaign_dirty = True
                source = dict(campaign.get("source_zone") or {})
            else:
                return _cancel_pending(
                    self,
                    campaign,
                    price,
                    result="CANCELLED — SOURCE ZONE UNVERIFIED BEFORE ENTRY",
                    reason="Pending idea cancelled because its original supply/demand zone is no longer the current best zone.",
                    code="source_zone_unverified",
                )

        source_id = str(source.get("id") or "")
        preferred_id = str((preferred or {}).get("id") or "")
        if not preferred or not source_id or preferred_id != source_id:
            return _cancel_pending(
                self,
                campaign,
                price,
                result="CANCELLED — SOURCE ZONE REPLACED BEFORE ENTRY",
                reason="Pending idea cancelled because the supply/demand zone that created it has been replaced by current structure.",
                code="source_zone_replaced",
                detail={
                    "source_zone_id": source_id or None,
                    "current_best_zone_id": preferred_id or None,
                    "source_zone": source or None,
                    "current_best_zone": preferred or None,
                },
            )

    # Pending orders must still pass the exact hardened bias/liquidity assessment.
    # This does not change the v45 gate; it reuses it to stop an old idea surviving
    # after the market context that justified publication has materially changed.
    if clear_gate._is_modern_structural_bias(dict(bias or {})):
        clear, assessment = clear_gate._clear_bias_assessment(bias, liquidity)
        expected = "bullish" if side == "BUY" else "bearish" if side == "SELL" else ""
        if not clear or str(assessment.get("overall") or "") != expected:
            return _cancel_pending(
                self,
                campaign,
                price,
                result="CANCELLED — TRADE CONTEXT CHANGED BEFORE ENTRY",
                reason="Pending idea cancelled because the live bias/liquidity context no longer satisfies the hardened gate.",
                code="hardened_context_changed",
                detail={"clear_bias_gate": assessment},
            )
    return None


def _trade_idea_v49(
    self: core.LiveTrader,
    price: float,
    atr: float,
    bias: dict[str, Any],
    zones: dict[str, list[dict[str, Any]]],
    liquidity: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, Any]]:
    campaign = getattr(self, "_live_campaign", None)
    if isinstance(campaign, dict) and str(campaign.get("status") or "").lower() == "pending":
        cancelled = _revalidate_pending(self, campaign, price, atr, bias, zones, liquidity)
        if cancelled is not None:
            return cancelled

    self._zone_target_context_v49 = {"zones": zones, "atr": atr}
    try:
        return _current_trade_idea(self, price, atr, bias, zones, liquidity)
    finally:
        self._zone_target_context_v49 = {}


def _zone_sentence_v49(self: core.LiveTrader, kind: str, state: dict[str, Any]) -> str:
    zones = ((state.get("zones") or {}).get(kind) or [])
    as_of = str(state.get("as_of") or "")
    stamp = as_of[11:16] + " UTC" if len(as_of) >= 16 else "this refresh"
    if not zones:
        return f"Micky, as of {stamp}, I do not have a current {kind} zone clean enough to rank."
    zone = zones[0]
    return (
        f"Micky, as of {stamp}, my CURRENT best {kind} is "
        f"{_num(zone.get('low')):.2f} to {_num(zone.get('high')):.2f}. "
        f"Zone ID {zone.get('id')}; {zone.get('quality_label','medium')} "
        f"({int(_num(zone.get('quality')))}/100). If this zone is replaced, this answer becomes historical."
    )


def _fixed_target_replays(campaign: dict[str, Any], bars: list[dict[str, Any]]) -> dict[str, Any]:
    triggered = parse_time(campaign.get("triggered_at"))
    completed = parse_time(campaign.get("completed_at"))
    if not triggered or not completed:
        return {"version": TARGET_REPLAY_VERSION, "available": False}

    # Use only full M1 bars after the trigger minute and through the official
    # completion minute. This avoids crediting a target from an unknowable partial
    # trigger candle. Same-bar stop/target ambiguity is resolved stop-first.
    start = triggered.replace(second=0, microsecond=0) + timedelta(minutes=1)
    end = completed.replace(second=0, microsecond=0)
    usable = []
    for bar in bars:
        stamp = bar_time(bar)
        if stamp is not None and start <= stamp <= end:
            usable.append(bar)
    if not usable:
        return {"version": TARGET_REPLAY_VERSION, "available": False}

    side = str(campaign.get("side") or "").upper()
    entry = _num(campaign.get("entry"))
    stop = _num(campaign.get("stop"))
    risk = abs(entry - stop)
    if side not in {"BUY", "SELL"} or entry <= 0 or risk <= 0:
        return {"version": TARGET_REPLAY_VERSION, "available": False}

    results: dict[str, Any] = {}
    for rr in TARGET_REPLAY_R:
        target = entry + risk * rr if side == "BUY" else entry - risk * rr
        outcome = "open_at_official_completion"
        realised_r: float | None = None
        for bar in usable:
            low = _num(bar.get("low"))
            high = _num(bar.get("high"))
            stop_hit = low <= stop if side == "BUY" else high >= stop
            target_hit = high >= target if side == "BUY" else low <= target
            if stop_hit:
                outcome = "stop"
                realised_r = -1.0
                break
            if target_hit:
                outcome = "target"
                realised_r = rr
                break
        results[f"{rr:g}R"] = {
            "target": round(target, 3),
            "trade_outcome": outcome,
            "realised_r": realised_r,
            "learning_success": True if outcome == "target" else False if outcome == "stop" else None,
        }

    return {
        "version": TARGET_REPLAY_VERSION,
        "available": True,
        "policy": "Same published entry and stop; only target changes. Full M1 bars after trigger are scored stop-first through official completion.",
        "results": results,
    }


def _build_forensics_v49(
    campaign: dict[str, Any],
    row: dict[str, Any],
    bars: list[dict[str, Any]],
    opinion: dict[str, Any] | None,
    historical: list[dict[str, Any]],
    forward: list[dict[str, Any]],
    version: str,
    max_source_bars: int,
) -> dict[str, Any]:
    fx = _base_build_forensics(campaign, row, bars, opinion, historical, forward, version, max_source_bars)
    fx["target_alternative_replay"] = _fixed_target_replays(campaign, bars)
    return fx


def _runtime_status_v49(self: core.LiveTrader) -> dict[str, Any]:
    state = dict(_current_runtime_status(self))
    state.update(
        {
            "zone_target_guard_version": GUARD_VERSION,
            "pending_source_zone_revalidation": True,
            "pending_hardened_context_revalidation": True,
            "pending_max_age_minutes": MAX_PENDING_AGE_MINUTES,
            "new_trade_target_cap_r": MAX_TARGET_R,
            "target_alternative_replay_version": TARGET_REPLAY_VERSION,
            "hardened_gate_modified": False,
        }
    )
    return state


lock._new_campaign = _new_campaign_v49
forensics.build_forensics = _build_forensics_v49
core.LiveTrader._trade_idea = _trade_idea_v49  # type: ignore[method-assign]
core.LiveTrader._zone_sentence = _zone_sentence_v49  # type: ignore[method-assign]
core.LiveTrader.runtime_status = _runtime_status_v49  # type: ignore[method-assign]
