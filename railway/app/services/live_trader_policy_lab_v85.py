from __future__ import annotations

import hashlib
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from typing import Any

from app.services import live_trader as core
from app.services import live_trader_audit_hardening_v26 as hardening
from app.services import live_trader_clear_bias_gate_v45 as clear_gate
from app.services import live_trader_forward_shadow_learning_v83 as v83
from app.services import live_trader_historical_runtime_v30 as historical_runtime
from app.services import live_trader_learning_v2 as v2
from app.services import live_trader_london_session_gate_v46 as session_gate
from app.services import live_trader_trade_lock_v28 as lock
from app.services import live_trader_trade_outcomes_v38 as outcomes
from app.services import live_trader_zone_retrace_integrity_v64 as v64
from app.services import live_trader_zone_retrace_specialist_v58 as v58

VERSION = "eve-live-policy-lab-v85"
LEARNING_VERSION = "eve-live-policy-lab-v1"
TARGET_R = 1.5
MIN_ZONE_QUALITY = 55.0
RESOLVE_LIMIT = 16
RESOLVE_INTERVAL_SECONDS = 45.0
SUMMARY_CACHE_SECONDS = 60.0
MIN_CANDIDATE_TRIGGERED = 30
MIN_CANDIDATE_EXPECTANCY_R = 0.10

_current_refresh_state = core.LiveTrader.refresh_state
_current_learning_summary = core.LiveTrader.learning_summary
_current_runtime_status = core.LiveTrader.runtime_status


def _num(value: Any, default: float = 0.0) -> float:
    return core.number(value, default)


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


def _matching_zone(state: dict[str, Any], bias: str) -> dict[str, Any] | None:
    zones = dict(state.get("zones") or {})
    items = [
        dict(item or {})
        for item in list(zones.get("demand" if bias == "bullish" else "supply") or [])
        if isinstance(item, dict) and _num(item.get("quality")) >= MIN_ZONE_QUALITY
    ]
    if not items:
        return None
    items.sort(key=lambda item: (_num(item.get("distance_atr"), 999.0), -_num(item.get("quality"))))
    return items[0]


def _market_trade(
    *,
    side: str,
    price: float,
    atr: float,
    zone: dict[str, Any],
    policy_key: str,
    policy_reason: str,
    diagnostics: dict[str, Any],
) -> dict[str, Any] | None:
    low = _num(zone.get("low"))
    high = _num(zone.get("high"))
    if low <= 0 or high <= 0 or high < low:
        return None
    stop = low - 0.20 * atr if side == "BUY" else high + 0.20 * atr
    risk = abs(price - stop)
    if risk < 0.35 * atr or risk > 3.0 * atr:
        stop = price - 0.85 * atr if side == "BUY" else price + 0.85 * atr
    trade = v83._trade_geometry(
        side=side,
        order_type="market",
        entry=price,
        stop=stop,
        target_r=TARGET_R,
        variant=policy_key,
    )
    if not trade:
        return None
    trade["policy_lab"] = {
        "version": VERSION,
        "policy_key": policy_key,
        "reason": policy_reason,
        "publication_authority": False,
        "live_gate_unchanged": True,
        **diagnostics,
    }
    return trade


def _policy_candidates(state: dict[str, Any]) -> list[dict[str, Any]]:
    bias_payload = dict(state.get("bias") or {})
    overall = str(bias_payload.get("overall") or "neutral").lower()
    if overall not in {"bullish", "bearish"}:
        return []

    zone = _matching_zone(state, overall)
    if zone is None:
        return []

    price = _num(state.get("price"))
    atr = max(_num((state.get("market") or {}).get("atr")), 0.01)
    if price <= 0:
        return []

    side = "BUY" if overall == "bullish" else "SELL"
    distance = _num(zone.get("distance_atr"), 999.0)
    quality = _num(zone.get("quality"))
    timeframes = dict(bias_payload.get("timeframes") or {})
    m5_aligned = str((timeframes.get("M5") or {}).get("direction") or "") == overall
    m15_aligned = str((timeframes.get("M15") or {}).get("direction") or "") == overall
    clear, assessment = clear_gate._clear_bias_assessment(bias_payload, dict(state.get("liquidity") or {}))
    diagnostics = {
        "overall_bias": overall,
        "bias_confidence": int(round(_num(bias_payload.get("confidence")))),
        "clear_bias": bool(clear),
        "clear_bias_reasons": list(assessment.get("reasons") or []),
        "m5_aligned": m5_aligned,
        "m15_aligned": m15_aligned,
        "zone_quality": round(quality, 2),
        "zone_distance_atr": round(distance, 3),
        "zone_rank": zone.get("rank"),
        "zone_role": zone.get("zone_role"),
    }

    candidates: list[dict[str, Any]] = []

    def add_market(key: str, reason: str, enabled: bool = True) -> None:
        if not enabled:
            return
        trade = _market_trade(
            side=side,
            price=price,
            atr=atr,
            zone=zone,
            policy_key=key,
            policy_reason=reason,
            diagnostics=diagnostics,
        )
        if trade:
            candidates.append(trade)

    # Broad reference: tells the lab whether directional bias plus a quality zone
    # contains any edge at all. Never visible to the user as a trade.
    add_market(
        "directional_quality_market",
        "Directional bias plus nearest quality matching zone; no live clear-bias or distance requirement.",
    )

    # Systematically test which production restrictions add value rather than
    # assuming stricter is always better.
    add_market(
        "clear_bias_market",
        "Current clear-bias gate passed; no zone-distance requirement.",
        clear,
    )
    add_market(
        "clear_bias_zone_3_5atr",
        "Current clear-bias gate passed and matching zone is within 3.5 ATR.",
        clear and distance <= 3.5,
    )
    add_market(
        "clear_bias_zone_2_5atr",
        "Current clear-bias gate passed and matching zone is within 2.5 ATR.",
        clear and distance <= 2.5,
    )
    add_market(
        "m5_m15_zone_3_5atr",
        "M5 and M15 align with directional bias and matching zone is within 3.5 ATR.",
        m5_aligned and m15_aligned and distance <= 3.5,
    )

    low = _num(zone.get("low"))
    high = _num(zone.get("high"))
    if low > 0 and high > 0:
        if side == "BUY" and high < price:
            limit = v83._trade_geometry(
                side=side,
                order_type="buy_limit",
                entry=high,
                stop=low - 0.20 * atr,
                target_r=TARGET_R,
                variant="quality_zone_touch_limit",
            )
        elif side == "SELL" and low > price:
            limit = v83._trade_geometry(
                side=side,
                order_type="sell_limit",
                entry=low,
                stop=high + 0.20 * atr,
                target_r=TARGET_R,
                variant="quality_zone_touch_limit",
            )
        else:
            limit = None
        if limit:
            limit["policy_lab"] = {
                "version": VERSION,
                "policy_key": "quality_zone_touch_limit",
                "reason": "First touch of the nearest quality matching zone.",
                "publication_authority": False,
                "live_gate_unchanged": True,
                **diagnostics,
            }
            candidates.append(limit)

    if side == "BUY":
        confirm_entry = price + 0.15 * atr
        confirm_stop = price - 0.85 * atr
        order_type = "buy_stop"
    else:
        confirm_entry = price - 0.15 * atr
        confirm_stop = price + 0.85 * atr
        order_type = "sell_stop"
    confirm = v83._trade_geometry(
        side=side,
        order_type=order_type,
        entry=confirm_entry,
        stop=confirm_stop,
        target_r=TARGET_R,
        variant="directional_momentum_confirmation",
    )
    if confirm:
        confirm["policy_lab"] = {
            "version": VERSION,
            "policy_key": "directional_momentum_confirmation",
            "reason": "Directional bias with a simple 0.15 ATR momentum confirmation trigger.",
            "publication_authority": False,
            "live_gate_unchanged": True,
            **diagnostics,
        }
        candidates.append(confirm)

    return candidates


def _policy_episode(state: dict[str, Any], observed: datetime, policy_key: str) -> tuple[str, str]:
    family = str(state.get("setup_family") or state.get("setup_signature") or "unknown")
    symbol = str(state.get("symbol") or "XAU/USD")
    session = str((state.get("market") or {}).get("session") or "unknown")
    bucket = observed.replace(minute=(observed.minute // 30) * 30, second=0, microsecond=0)
    family_key = hashlib.sha1(f"{family}|{policy_key}".encode()).hexdigest()[:20]
    episode = hashlib.sha1(
        f"{symbol}|{bucket.isoformat()}|{session}|{family}|{policy_key}".encode()
    ).hexdigest()[:24]
    return family_key, episode


async def _record_policy_candidates(self: core.LiveTrader, state: dict[str, Any]) -> dict[str, Any]:
    observed = v83._recent_observation_time(state)
    if observed is None:
        return {"status": "skipped", "reason": "no_recent_connected_observation"}
    session = session_gate._session_status()
    if not bool(session.get("open")):
        return {"status": "skipped", "reason": "outside_user_facing_trade_window"}

    bucket = observed.replace(minute=(observed.minute // 5) * 5, second=0, microsecond=0)
    if getattr(self, "_policy_lab_last_bucket_v85", None) == bucket:
        return {"status": "throttled", "bucket": bucket.isoformat()}
    self._policy_lab_last_bucket_v85 = bucket

    candidates = _policy_candidates(state)
    if not candidates:
        return {"status": "skipped", "reason": "no_policy_candidate"}

    inserted = 0
    existing = 0
    errors: list[str] = []
    for trade in candidates:
        policy = dict(trade.get("policy_lab") or {})
        key = str(policy.get("policy_key") or trade.get("shadow_variant") or "unknown")
        family, episode = _policy_episode(state, observed, key)
        try:
            rows = await self.repo.client.get(
                "live_trader_opinions",
                params={
                    "select": "id",
                    "learning_version": f"eq.{LEARNING_VERSION}",
                    "setup_family": f"eq.{family}",
                    "episode_key": f"eq.{episode}",
                    "limit": "1",
                },
            )
            if rows:
                existing += 1
                continue
            descriptor = dict(state.get("setup_family_descriptor") or {})
            descriptor["policy_lab_key"] = key
            await self.repo.client.insert(
                "live_trader_opinions",
                {
                    "observed_at": observed.isoformat(),
                    "symbol": self.symbol,
                    "price": state.get("price"),
                    "bias": (state.get("bias") or {}).get("overall"),
                    "confidence": (state.get("bias") or {}).get("confidence"),
                    "horizon_minutes": self.settings.live_trader_learning_horizon_minutes,
                    "setup_signature": family,
                    "setup_family": family,
                    "episode_key": episode,
                    "learning_version": LEARNING_VERSION,
                    "independent_sample": False,
                    "market_state": {
                        "market": state.get("market"),
                        "bias": state.get("bias"),
                        "liquidity": state.get("liquidity"),
                        "setup_family_descriptor": descriptor,
                        "policy_lab": policy,
                    },
                    "zones": state.get("zones") or {},
                    "trade_idea": trade,
                    "opinion_text": f"Research-only policy lab candidate: {key}. Never publish or execute.",
                    "status": "open",
                },
                return_rows=False,
            )
            inserted += 1
        except Exception as exc:
            errors.append(str(exc)[:180])
            core.logger.warning("Live Trader policy lab record failed for %s: %s", key, exc)

    return {
        "status": "ok" if not errors else "partial",
        "inserted": inserted,
        "already_present": existing,
        "candidates": len(candidates),
        "errors": errors[:3],
        "bucket": bucket.isoformat(),
    }


async def _resolve_policy_outcomes(self: core.LiveTrader) -> dict[str, Any]:
    now = core.utc_now()
    last = getattr(self, "_policy_lab_last_resolution_v85", None)
    if isinstance(last, datetime) and now - last < timedelta(seconds=RESOLVE_INTERVAL_SECONDS):
        return {"status": "throttled"}
    self._policy_lab_last_resolution_v85 = now
    cutoff = now - timedelta(minutes=self.settings.live_trader_learning_horizon_minutes)

    try:
        rows = await self.repo.client.get(
            "live_trader_opinions",
            params={
                "select": "id,observed_at,price,bias,horizon_minutes,market_state,trade_idea",
                "learning_version": f"eq.{LEARNING_VERSION}",
                "status": "eq.open",
                "observed_at": f"lte.{cutoff.isoformat()}",
                "order": "observed_at.asc",
                "limit": str(RESOLVE_LIMIT),
            },
        )
    except Exception as exc:
        return {"status": "error", "reason": str(exc)[:240]}

    resolved = 0
    for row in rows:
        observed = _parse_time(row.get("observed_at"))
        if observed is None:
            continue
        horizon_minutes = int(_num(row.get("horizon_minutes"), self.settings.live_trader_learning_horizon_minutes))
        horizon = observed + timedelta(minutes=max(horizon_minutes, 1))
        try:
            source_rows = await hardening._source_m1_rows(self, observed, horizon)
            path = hardening._causal_m1_path(source_rows, observed, horizon)
            endpoint = path.get("endpoint_price")
            endpoint_time = path.get("endpoint_time")
            endpoint_lag = path.get("endpoint_lag_seconds")
            if endpoint is None or endpoint_time is None or endpoint_lag is None:
                continue
            if float(endpoint_lag) > hardening.MAX_ENDPOINT_LAG_SECONDS:
                continue

            path_complete = (
                path.get("initial_gap_seconds") is not None
                and float(path.get("initial_gap_seconds") or 0.0) <= 1.0
                and int(path.get("gap_count") or 0) == 0
            )
            trade = dict(row.get("trade_idea") or {})
            if path_complete:
                result = v2._trade_path_result(trade, list(path.get("bars") or []), float(endpoint))
            else:
                result = {
                    "entry_triggered": None,
                    "trade_outcome": "insufficient_m1_path",
                    "realised_r": None,
                    "learning_success": None,
                }

            market_state = dict(row.get("market_state") or {})
            market_state["policy_lab_resolution"] = {
                "version": VERSION,
                "resolved_at": now.isoformat(),
                "horizon_at": horizon.isoformat(),
                "resolved_price_time": endpoint_time.isoformat(),
                "m1_path_bars": len(path.get("bars") or []),
                "path_complete": path_complete,
                "initial_gap_seconds": path.get("initial_gap_seconds"),
                "gap_count": path.get("gap_count"),
                "endpoint_lag_seconds": endpoint_lag,
            }
            await self.repo.client.patch(
                "live_trader_opinions",
                {
                    "status": "resolved",
                    "resolved_at": now.isoformat(),
                    "resolved_price": float(endpoint),
                    "entry_triggered": result.get("entry_triggered"),
                    "trade_outcome": result.get("trade_outcome"),
                    "realised_r": result.get("realised_r"),
                    "learning_success": result.get("learning_success"),
                    "market_state": market_state,
                },
                filters={"id": f"eq.{row.get('id')}"},
            )
            resolved += 1
        except Exception as exc:
            core.logger.warning("Live Trader policy lab resolution failed: %s", exc)
    return {"status": "ok", "resolved": resolved, "eligible": len(rows)}


def _max_drawdown(values: list[float]) -> float:
    equity = 0.0
    peak = 0.0
    worst = 0.0
    for value in values:
        equity += value
        peak = max(peak, equity)
        worst = min(worst, equity - peak)
    return round(abs(worst), 3)


def _policy_stats(rows: list[dict[str, Any]]) -> dict[str, Any]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        trade = dict(row.get("trade_idea") or {})
        policy = dict(trade.get("policy_lab") or {})
        key = str(policy.get("policy_key") or trade.get("shadow_variant") or "unknown")
        grouped[key].append(row)

    leaderboard: list[dict[str, Any]] = []
    for key, items in grouped.items():
        ordered = sorted(items, key=lambda row: str(row.get("observed_at") or ""))
        triggered = [
            row for row in ordered
            if row.get("entry_triggered") is True and row.get("realised_r") is not None
        ]
        values = [_num(row.get("realised_r")) for row in triggered]
        wins = sum(1 for value in values if value > 0)
        losses = sum(1 for value in values if value < 0)
        total_r = sum(values)
        expectancy = total_r / len(values) if values else None
        days = {
            str(row.get("observed_at") or "")[:10]
            for row in triggered
            if row.get("observed_at")
        }
        candidate = bool(
            len(triggered) >= MIN_CANDIDATE_TRIGGERED
            and expectancy is not None
            and expectancy >= MIN_CANDIDATE_EXPECTANCY_R
        )
        leaderboard.append(
            {
                "policy_key": key,
                "resolved": len(items),
                "triggered": len(triggered),
                "wins": wins,
                "losses": losses,
                "total_r": round(total_r, 3),
                "expectancy_r": round(expectancy, 3) if expectancy is not None else None,
                "win_rate": round(wins / len(triggered), 3) if triggered else None,
                "max_drawdown_r": _max_drawdown(values),
                "independent_days": len(days),
                "forward_candidate": candidate,
                "minimum_triggered": MIN_CANDIDATE_TRIGGERED,
                "minimum_expectancy_r": MIN_CANDIDATE_EXPECTANCY_R,
                "publication_authority": False,
            }
        )

    leaderboard.sort(
        key=lambda item: (
            bool(item.get("forward_candidate")),
            _num(item.get("expectancy_r"), -999.0),
            int(item.get("triggered") or 0),
        ),
        reverse=True,
    )
    return {
        "version": VERSION,
        "learning_version": LEARNING_VERSION,
        "leader": leaderboard[0] if leaderboard else None,
        "leaderboard": leaderboard,
        "live_policy_unchanged": True,
        "automatic_promotion": False,
        "purpose": (
            "Research multiple execution/gating policies in parallel using causal M1 outcomes. "
            "A policy can become a forward candidate, but this lab never publishes or executes it."
        ),
    }


async def _policy_lab_summary(self: core.LiveTrader) -> dict[str, Any]:
    now = core.utc_now()
    cached_at = getattr(self, "_policy_lab_summary_at_v85", None)
    cached = getattr(self, "_policy_lab_summary_v85", None)
    if isinstance(cached_at, datetime) and isinstance(cached, dict):
        if now - cached_at < timedelta(seconds=SUMMARY_CACHE_SECONDS):
            return dict(cached)
    try:
        rows = await self.repo.client.get(
            "live_trader_opinions",
            params={
                "select": "observed_at,entry_triggered,realised_r,trade_outcome,trade_idea",
                "learning_version": f"eq.{LEARNING_VERSION}",
                "status": "eq.resolved",
                "order": "observed_at.asc",
                "limit": "5000",
            },
        )
    except Exception as exc:
        result = {"version": VERSION, "status": "error", "reason": str(exc)[:240]}
    else:
        result = _policy_stats(list(rows))
    self._policy_lab_summary_at_v85 = now
    self._policy_lab_summary_v85 = dict(result)
    return result


async def _refresh_state_v85(self: core.LiveTrader, *, force_rows: bool = False) -> dict[str, Any]:
    state = dict(await _current_refresh_state(self, force_rows=force_rows))
    recording = await _record_policy_candidates(self, state)
    resolution = await _resolve_policy_outcomes(self)
    state["policy_lab_health"] = {
        "version": VERSION,
        "recording": recording,
        "resolution": resolution,
        "live_policy_unchanged": True,
        "publication_authority": False,
    }
    self._latest_state = state
    return state


async def _learning_summary_v85(self: core.LiveTrader) -> dict[str, Any]:
    summary = dict(await _current_learning_summary(self))
    summary["policy_lab"] = await _policy_lab_summary(self)
    summary["policy_lab_health"] = dict((self._latest_state or {}).get("policy_lab_health") or {})
    return summary


def _runtime_status_v85(self: core.LiveTrader) -> dict[str, Any]:
    status = dict(_current_runtime_status(self))
    status.update(
        {
            "policy_lab_version": VERSION,
            "policy_lab_learning_version": LEARNING_VERSION,
            "policy_lab_parallel_forward_research": True,
            "policy_lab_automatic_promotion": False,
            "policy_lab_publication_authority": False,
            "visible_trade_gate_unchanged": True,
        }
    )
    return status


core.LiveTrader.refresh_state = _refresh_state_v85  # type: ignore[method-assign]
core.LiveTrader.learning_summary = _learning_summary_v85  # type: ignore[method-assign]
core.LiveTrader.runtime_status = _runtime_status_v85  # type: ignore[method-assign]

# Keep established compatibility aliases pointed at the newest refresh wrapper.
lock._refresh_state_v28 = _refresh_state_v85
historical_runtime._refresh_state_v30 = _refresh_state_v85
outcomes._refresh_v38 = _refresh_state_v85
v58._refresh_state_v58 = _refresh_state_v85
v64.v58._refresh_state_v58 = _refresh_state_v85
v64.historical_runtime._refresh_state_v30 = _refresh_state_v85
v64.outcomes._refresh_v38 = _refresh_state_v85
