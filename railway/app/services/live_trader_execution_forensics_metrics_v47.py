from __future__ import annotations

import math
from datetime import datetime, timedelta, timezone
from typing import Any


def parse_time(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        out = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    return (out if out.tzinfo else out.replace(tzinfo=timezone.utc)).astimezone(timezone.utc)


def num(value: Any, default: float = 0.0) -> float:
    try:
        out = float(value)
    except (TypeError, ValueError):
        return default
    return out if math.isfinite(out) else default


def ceil_minute(value: datetime) -> datetime:
    base = value.replace(second=0, microsecond=0)
    return base if value == base else base + timedelta(minutes=1)


def bar_time(bar: dict[str, Any]) -> datetime | None:
    return parse_time(bar.get("candle_time"))


def entry_maturity_score(context: dict[str, Any], side: str) -> dict[str, Any]:
    if not context or context.get("note"):
        return {"score": None, "available": False, "reason": "Original publication context is incomplete.", "components": {}}
    side = str(side or "").upper()
    direction = "bullish" if side == "BUY" else "bearish" if side == "SELL" else "neutral"
    bias = dict(context.get("bias") or {})
    desc = dict(context.get("setup_family_descriptor") or {})
    event = dict((context.get("liquidity") or {}).get("primary_event") or {})
    c = max(0.0, min(25.0, (num(bias.get("confidence")) - 45.0) / 45.0 * 25.0))
    htf = 20.0 if desc.get("htf_alignment") == direction else 8.0 if desc.get("htf_alignment") == "mixed" else 0.0
    intra = 20.0 if desc.get("intraday_alignment") == direction else 7.0 if desc.get("intraday_alignment") == "mixed" else 0.0
    zone = {"high": 15.0, "good": 11.0, "medium": 6.0}.get(str(desc.get("zone_quality")), 0.0)
    loc = str(desc.get("location") or "middle")
    correct = {"in_demand", "near_demand", "middle_demand_side"} if side == "BUY" else {"in_supply", "near_supply", "middle_supply_side"}
    location = 10.0 if loc in correct and loc.startswith(("in_", "near_")) else 6.0 if loc in correct else 4.0 if loc == "middle" else 0.0
    implication = str(event.get("implication") or "neutral")
    liquidity = 10.0 if implication == direction else 5.0 if implication == "neutral" else 0.0
    score = int(round(max(0.0, min(100.0, c + htf + intra + zone + location + liquidity))))
    return {
        "score": score,
        "available": True,
        "reason": "Diagnostic publication-quality score only; it does not arm or veto trades.",
        "components": {"directional_confidence": round(c, 1), "higher_timeframe_alignment": htf, "intraday_alignment": intra, "zone_quality": zone, "location_quality": location, "liquidity_event": liquidity},
    }


def path_metrics(campaign: dict[str, Any], bars: list[dict[str, Any]]) -> dict[str, Any]:
    side = str(campaign.get("side") or "").upper()
    entry, stop, target = (num(campaign.get(k)) for k in ("entry", "stop", "target"))
    risk = abs(entry - stop)
    created, triggered, completed = (parse_time(campaign.get(k)) for k in ("created_at", "triggered_at", "completed_at"))
    status = str(campaign.get("status") or "").lower()
    rr = num(campaign.get("risk_reward"), abs(target-entry)/risk if risk else 0.0)
    out: dict[str, Any] = {
        "path_bars": len(bars),
        "mfe_r": None,
        "mae_r": None,
        "post_completion_best_r": None,
        "target_reached_after_completion": False,
        "time_to_trigger_minutes": None,
        "active_minutes": None,
        "risk_price": round(risk, 5) if risk else None,
        "active_path_full_bars": 0,
        "boundary_policy": "exclude_partial_trigger_and_completion_m1_candles",
    }
    if created and triggered:
        out["time_to_trigger_minutes"] = round((triggered-created).total_seconds()/60, 1)
    if triggered and completed:
        out["active_minutes"] = round((completed-triggered).total_seconds()/60, 1)
    if side not in {"BUY", "SELL"} or not entry or not risk or not completed:
        return out
    if triggered:
        # An M1 candle is used for MFE/MAE only when the entire candle is known to
        # be after entry and before completion. Sub-minute trigger/exit candles are
        # deliberately excluded because their internal high/low ordering is unknown.
        active_start = ceil_minute(triggered)
        active_end = completed.replace(second=0, microsecond=0)
        mfe = mae = 0.0
        active_bars = 0
        for bar in bars:
            stamp = bar_time(bar)
            if not stamp or stamp < active_start or stamp >= active_end:
                continue
            active_bars += 1
            hi, lo = num(bar.get("high")), num(bar.get("low"))
            fav, adv = ((hi-entry)/risk, (entry-lo)/risk) if side == "BUY" else ((entry-lo)/risk, (hi-entry)/risk)
            mfe, mae = max(mfe, fav), max(mae, adv)
        if status == "lost":
            mae = max(mae, 1.0)
        if status == "won":
            mfe = max(mfe, rr)
        out["active_path_full_bars"] = active_bars
        out["mfe_r"], out["mae_r"] = round(max(0.0, mfe), 3), round(max(0.0, mae), 3)
    post_start, post_best, hit = ceil_minute(completed), 0.0, False
    for bar in bars:
        stamp = bar_time(bar)
        if not stamp or stamp < post_start:
            continue
        hi, lo = num(bar.get("high")), num(bar.get("low"))
        post_best = max(post_best, (hi-entry)/risk if side == "BUY" else (entry-lo)/risk)
        hit = hit or (hi >= target if side == "BUY" else lo <= target)
    out["post_completion_best_r"], out["target_reached_after_completion"] = round(max(0.0, post_best), 3), bool(hit)
    return out


def diagnose(campaign: dict[str, Any], metrics: dict[str, Any], opinion: dict[str, Any] | None) -> dict[str, Any]:
    status = str(campaign.get("status") or "").lower()
    rr, mfe, post = num(campaign.get("risk_reward")), num(metrics.get("mfe_r")), num(metrics.get("post_completion_best_r"))
    target_after, wait, active = bool(metrics.get("target_reached_after_completion")), metrics.get("time_to_trigger_minutes"), metrics.get("active_minutes")
    direction = opinion.get("direction_correct") if opinion else None
    thesis = "supported_at_learning_horizon" if direction is True else "not_supported_at_learning_horizon" if direction is False else "eventually_supported" if target_after or post >= 1 else "not_supported" if status == "lost" and mfe < .2 and post < .5 else "mixed_or_unproven"
    if status in {"invalidated", "expired"} and not campaign.get("triggered_at"):
        entry_timing = "never_triggered"
    elif status == "lost" and wait is not None and float(wait) >= 90 and active is not None and float(active) <= 20:
        entry_timing = "aged_setup_triggered_late"
    elif status == "lost" and active is not None and float(active) <= 10 and mfe < .2:
        entry_timing = "rapid_failure_after_entry"
    elif mfe >= .5:
        entry_timing = "entry_worked_initially"
    else:
        entry_timing = "mixed_or_unproven"
    if status == "lost" and (target_after or post >= 2):
        stop_diag = "timing_or_stop_geometry_suspect"
    elif status == "lost" and mfe >= 1:
        stop_diag = "gave_back_one_r_or_more_before_stop"
    elif status == "lost" and active is not None and float(active) <= 10 and mfe < .2:
        stop_diag = "rapid_stop_failure"
    elif status == "lost":
        stop_diag = "not_isolated_from_entry_or_direction"
    else:
        stop_diag = "not_applicable"
    if status == "won":
        target_diag = "reached"
    elif target_after:
        target_diag = "reachable_after_stop"
    elif status == "lost" and rr >= 4 and max(mfe, post) < 1:
        target_diag = "aggressive_and_unproven"
    elif status == "lost" and rr > 0 and mfe >= rr*.75:
        target_diag = "nearly_reached_before_failure"
    elif status == "lost":
        target_diag = "not_reached"
    else:
        target_diag = "not_applicable"
    if status == "won":
        primary, confidence = "successful_execution", "high"
    elif status in {"invalidated", "expired"} and not campaign.get("triggered_at"):
        primary, confidence = "setup_selection_or_entry_timing", "high"
    elif status == "lost" and (target_after or post >= 2):
        primary, confidence = "execution_timing_or_stop", "high"
    elif status == "lost" and entry_timing == "aged_setup_triggered_late":
        primary, confidence = "aged_setup_trigger", "high"
    elif status == "lost" and direction is False and mfe < .2:
        primary, confidence = "direction_and_execution_failed", "medium"
    elif status == "lost" and mfe >= 1:
        primary, confidence = "risk_management_or_stop", "medium"
    elif status == "lost":
        primary, confidence = "normal_or_unresolved_loss", "low"
    else:
        primary, confidence = "untriggered_setup_evidence", "medium"
    lessons = {
        "execution_timing_or_stop": "The trade lost, but price later moved strongly in EVE's published direction. Treat this as execution-timing/stop evidence, not automatic proof the thesis was wrong.",
        "aged_setup_trigger": "The order waited a long time before triggering and then failed quickly. Setup age may matter before arming this execution again.",
        "direction_and_execution_failed": "The publication-horizon direction was not supported and the trade never developed meaningful favorable excursion. This is negative thesis and execution evidence, subject to repeated confirmation.",
        "risk_management_or_stop": "The trade developed at least 1R favorable excursion before stopping. Investigate protection/stop behaviour separately from entry quality.",
        "successful_execution": "The published execution reached target. Keep the path metrics as positive evidence without treating one win as proof.",
        "setup_selection_or_entry_timing": "Capital was never exposed. Keep this as setup-selection and entry-timing evidence rather than a trading loss.",
        "normal_or_unresolved_loss": "The trade lost, but this path does not isolate a specific fault confidently. Keep it as negative evidence and wait for repeated independent cases.",
        "untriggered_setup_evidence": "Keep the untriggered setup as selection evidence without treating it as a trading result.",
    }
    return {"primary": primary, "confidence": confidence, "thesis": thesis, "entry_timing": entry_timing, "stop": stop_diag, "target": target_diag, "lesson": lessons[primary]}
