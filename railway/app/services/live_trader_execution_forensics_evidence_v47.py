from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from app.services import live_trader_execution_integrity_v39 as integrity
from app.services.live_trader_execution_forensics_metrics_v47 import bar_time, ceil_minute, diagnose, entry_maturity_score, num, parse_time, path_metrics


def forward_opinion(opinion: dict[str, Any] | None) -> dict[str, Any]:
    if not opinion:
        return {"available": False, "direction_correct_at_learning_horizon": None, "trade_outcome_at_learning_horizon": None, "realised_r_at_learning_horizon": None}
    return {"available": True, "observed_at": opinion.get("observed_at"), "resolved_at": opinion.get("resolved_at"), "bias": opinion.get("bias"), "confidence": opinion.get("confidence"), "direction_correct_at_learning_horizon": opinion.get("direction_correct"), "trade_outcome_at_learning_horizon": opinion.get("trade_outcome"), "realised_r_at_learning_horizon": opinion.get("realised_r"), "learning_success_at_learning_horizon": opinion.get("learning_success")}


def proxy_challengers(campaign: dict[str, Any], bars: list[dict[str, Any]]) -> dict[str, Any]:
    side = str(campaign.get("side") or "").upper()
    entry, stop, target = (num(campaign.get(k)) for k in ("entry", "stop", "target"))
    risk = abs(entry-stop)
    if side not in {"BUY", "SELL"} or not entry or not stop or not target or not risk or not bars:
        return {"available": False, "reason": "Insufficient causal path or trade geometry."}
    original = {"side": side, "order_type": campaign.get("order_type"), "entry": entry, "stop": stop, "target": target, "risk_reward": campaign.get("risk_reward"), "invalidation_price": campaign.get("invalidation_price"), "invalidation": campaign.get("invalidation")}
    candidates = {"original_replay": original}
    confirm_entry = entry + risk*.25 if side == "BUY" else entry-risk*.25
    if abs(confirm_entry-stop) > 0:
        candidates["quarter_r_confirmation_proxy"] = {**original, "order_type": "buy_stop" if side == "BUY" else "sell_stop", "entry": round(confirm_entry, 5), "risk_reward": round(abs(target-confirm_entry)/abs(confirm_entry-stop), 3), "invalidation_price": stop}
    if abs(target-entry)/risk > 2.05:
        candidates["two_r_target_proxy"] = {**original, "target": round(entry+risk*2 if side == "BUY" else entry-risk*2, 5), "risk_reward": 2.0}
    endpoint, scored, best_name, best_r = num(bars[-1].get("close"), entry), {}, "no_trade", 0.0
    for name, trade in candidates.items():
        result = integrity._trade_path_result_v39(trade, bars, endpoint)
        scored[name] = result
        r = result.get("realised_r")
        if result.get("entry_triggered") and r is not None and num(r, -999) > best_r:
            best_name, best_r = name, num(r)
    return {"available": True, "policy": "Diagnostic proxies only. They replay the same causal M1 path and never replace the official campaign result or change live rules automatically.", "best_proxy": best_name, "results": scored}


def historical_summary(rows: list[dict[str, Any]]) -> dict[str, Any]:
    if not rows: return {"available": False, "episodes": 0, "best_counts": {}, "alternatives": {}}
    best_counts: dict[str, int] = {}; alternatives: dict[str, dict[str, float]] = {}
    for row in rows:
        best = str(row.get("best_challenger") or "")
        if best: best_counts[best] = best_counts.get(best, 0)+1
        for name, payload in dict(row.get("challenger_results") or {}).items():
            r = dict(payload or {}).get("realised_r")
            if r is None: continue
            s = alternatives.setdefault(str(name), {"samples": 0.0, "sum_r": 0.0, "wins": 0.0})
            s["samples"] += 1; s["sum_r"] += num(r); s["wins"] += int(bool(dict(payload or {}).get("learning_success")))
    compact = {name: {"samples": int(s["samples"]), "avg_r": round(s["sum_r"]/s["samples"], 3), "success_rate": round(s["wins"]/s["samples"], 3)} for name, s in alternatives.items() if s["samples"]}
    return {"available": True, "episodes": len(rows), "dominant_best_challenger": max(best_counts, key=best_counts.get) if best_counts else None, "best_counts": best_counts, "alternatives": compact}


def forward_family_summary(rows: list[dict[str, Any]]) -> dict[str, Any]:
    scored = [r for r in rows if r.get("learning_success") is not None]
    samples, wins = len(scored), sum(bool(r.get("learning_success")) for r in scored)
    days = len({str(r.get("observed_at"))[:10] for r in scored if r.get("observed_at")})
    accuracy = wins/samples if samples else None; posterior = (wins+6)/(samples+12) if samples else .5; mature = samples >= 12 and days >= 3
    return {"samples": samples, "days": days, "accuracy": round(accuracy, 3) if accuracy is not None else None, "posterior_accuracy": round(posterior, 3), "mature": mature, "confidence": int(round(posterior*100)) if mature else None, "status": "mature" if mature else "building", "policy": "Forward-proven confidence stays unavailable until at least 12 independent scored outcomes across 3 days."}


def build_forensics(campaign: dict[str, Any], review_row: dict[str, Any], bars: list[dict[str, Any]], opinion: dict[str, Any] | None, historical_rows: list[dict[str, Any]], forward_rows: list[dict[str, Any]], version: str, max_bars: int) -> dict[str, Any]:
    publication = dict(review_row.get("publication_context") or {}); metrics = path_metrics(campaign, bars); maturity = entry_maturity_score(publication, str(campaign.get("side") or "")); forward = forward_family_summary(forward_rows)
    created = parse_time(campaign.get("created_at")); causal = [b for b in bars if created is None or (bar_time(b) or datetime.min.replace(tzinfo=timezone.utc)) >= ceil_minute(created)]
    bias = dict(publication.get("bias") or {})
    return {"version": version, "diagnostic_only": True, "official_campaign_result_unchanged": True, "entry_maturity": maturity, "confidence_split": {"market_direction": bias.get("confidence"), "execution_maturity": maturity.get("score"), "forward_proven": forward.get("confidence"), "forward_evidence": forward, "diagnostic_only": True}, "path": metrics, "forward_opinion_reconciliation": forward_opinion(opinion), "diagnosis": diagnose(campaign, metrics, opinion), "proxy_challengers": proxy_challengers(campaign, causal), "historical_family_challengers": historical_summary(historical_rows), "memory_policy": f"One campaign at a time; at most {max_bars} M1 bars are held temporarily. Results are persisted and the candle list is discarded after analysis."}
