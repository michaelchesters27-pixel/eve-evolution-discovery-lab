from __future__ import annotations

import hashlib
from datetime import datetime, timedelta, timezone
from typing import Any

from app.services import live_trader as core
from app.services import live_trader_audit_hardening_v26 as hardening
from app.services import live_trader_learning_v2 as v2
from app.services import live_trader_learning_v22 as v22
from app.services import live_trader_london_session_gate_v46 as session_gate

VERSION = "eve-live-forward-shadow-learning-v83"
SHADOW_VERSION = "eve-live-shadow-trades-v1"
SHADOW_TARGET_R = 1.5
SHADOW_MIN_ZONE_QUALITY = 55.0
SHADOW_MAX_ZONE_DISTANCE_ATR = 2.75
MAX_OBSERVATION_AGE_SECONDS = 120.0
SHADOW_RESOLVE_LIMIT = 8
SHADOW_RESOLVE_INTERVAL_SECONDS = 45.0
TRADE_SKILL_CACHE_SECONDS = 60.0

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


def _recent_observation_time(state: dict[str, Any], *, now: datetime | None = None) -> datetime | None:
    """Return the freshest decision timestamp that is safe to learn from.

    v2.6 originally preferred state.as_of. The live state has since gained several
    wrappers, so use the explicit feed timestamp first and only fall back to
    state.as_of. This makes forward learning self-healing if a display wrapper
    changes as_of semantics without changing the market observation itself.
    """
    current = now or core.utc_now()
    feed = dict(state.get("feed") or {})
    if not bool(feed.get("connected")):
        return None
    observed = _parse_time(feed.get("last_tick_at")) or _parse_time(state.get("as_of"))
    if observed is None or observed > current + timedelta(seconds=5):
        return None
    age = (current - observed).total_seconds()
    if age < 0 or age > MAX_OBSERVATION_AGE_SECONDS:
        return None
    return observed


def _forward_episode_key(state: dict[str, Any]) -> str:
    return v22.episode_key(state)


async def _ensure_forward_observation(self: core.LiveTrader, state: dict[str, Any]) -> dict[str, Any]:
    diagnostics = {
        "version": VERSION,
        "status": "skipped",
        "learning_version": hardening.LEARNING_NAMESPACE,
    }
    observed = _recent_observation_time(state)
    if observed is None:
        diagnostics["reason"] = "no_recent_connected_observation"
        return diagnostics

    family = str(state.get("setup_family") or state.get("setup_signature") or "")
    if not family:
        diagnostics["reason"] = "no_setup_family"
        return diagnostics
    episode = _forward_episode_key(state)

    try:
        existing = await self.repo.client.get(
            "live_trader_opinions",
            params={
                "select": "id,observed_at,status",
                "learning_version": f"eq.{hardening.LEARNING_NAMESPACE}",
                "setup_family": f"eq.{family}",
                "episode_key": f"eq.{episode}",
                "limit": "1",
            },
        )
        if existing:
            diagnostics.update({"status": "present", "episode_key": episode, "setup_family": family})
            return diagnostics

        recorded_at = core.utc_now()
        market_state = {
            "market": state.get("market"),
            "bias": state.get("bias"),
            "liquidity": state.get("liquidity"),
            "setup_family_descriptor": state.get("setup_family_descriptor"),
            "learning_observation": {
                "policy": hardening.OBSERVATION_POLICY,
                "market_observed_at": observed.isoformat(),
                "recorded_at": recorded_at.isoformat(),
                "engine_version": hardening.ENGINE_VERSION,
                "outcome_schema": hardening.OUTCOME_SCHEMA,
                "forward_recorder": VERSION,
                "self_healing_fallback": True,
            },
        }
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
                "learning_version": hardening.LEARNING_NAMESPACE,
                "independent_sample": True,
                "market_state": market_state,
                "zones": state.get("zones") or {},
                "trade_idea": state.get("trade") or {},
                "opinion_text": state.get("opinion") or "",
                "status": "open",
            },
            return_rows=False,
        )
        diagnostics.update(
            {
                "status": "inserted",
                "episode_key": episode,
                "setup_family": family,
                "observed_at": observed.isoformat(),
            }
        )
        return diagnostics
    except Exception as exc:
        diagnostics.update({"status": "error", "reason": str(exc)[:240]})
        core.logger.warning("Live Trader v83 forward-learning fallback failed: %s", exc)
        return diagnostics


def _matching_zone(state: dict[str, Any], bias: str) -> dict[str, Any] | None:
    zones = dict(state.get("zones") or {})
    items = list(zones.get("demand" if bias == "bullish" else "supply") or [])
    if not items:
        return None
    zone = dict(items[0] or {})
    if _num(zone.get("quality")) < SHADOW_MIN_ZONE_QUALITY:
        return None
    if _num(zone.get("distance_atr"), 999.0) > SHADOW_MAX_ZONE_DISTANCE_ATR:
        return None
    return zone


def _trade_geometry(
    *,
    side: str,
    order_type: str,
    entry: float,
    stop: float,
    target_r: float,
    variant: str,
) -> dict[str, Any] | None:
    risk = abs(entry - stop)
    if entry <= 0 or stop <= 0 or risk <= 0:
        return None
    target = entry + risk * target_r if side == "BUY" else entry - risk * target_r
    if target <= 0:
        return None
    return {
        "action": f"SHADOW {side}",
        "side": side,
        "order_type": order_type,
        "entry": round(entry, 3),
        "stop": round(stop, 3),
        "target": round(target, 3),
        "risk_reward": round(target_r, 2),
        "confidence": None,
        "manual_only": True,
        "automatic_order_placement": False,
        "shadow_only": True,
        "shadow_variant": variant,
        "reason": "Research-only candidate. Never publish or execute this order from the Live Trader UI.",
    }


def _shadow_candidates(state: dict[str, Any]) -> list[dict[str, Any]]:
    bias = str((state.get("bias") or {}).get("overall") or "neutral").lower()
    if bias not in {"bullish", "bearish"}:
        return []
    zone = _matching_zone(state, bias)
    if zone is None:
        return []

    price = _num(state.get("price"))
    atr = max(_num((state.get("market") or {}).get("atr")), 0.01)
    if price <= 0:
        return []
    side = "BUY" if bias == "bullish" else "SELL"
    zone_low = _num(zone.get("low"))
    zone_high = _num(zone.get("high"))
    if zone_low <= 0 or zone_high <= 0 or zone_high < zone_low:
        return []

    candidates: list[dict[str, Any]] = []

    # Variant 1: immediate market probe. It is deliberately shadow-only and is
    # useful for learning whether waiting for retracement adds value.
    market_stop = zone_low - 0.20 * atr if side == "BUY" else zone_high + 0.20 * atr
    market_risk = abs(price - market_stop)
    if market_risk < 0.35 * atr or market_risk > 3.0 * atr:
        market_stop = price - 0.85 * atr if side == "BUY" else price + 0.85 * atr
    market = _trade_geometry(
        side=side,
        order_type="market",
        entry=price,
        stop=market_stop,
        target_r=SHADOW_TARGET_R,
        variant="market_probe",
    )
    if market:
        candidates.append(market)

    # Variant 2: first-touch retracement into the matching zone.
    if side == "BUY" and zone_high < price:
        limit = _trade_geometry(
            side=side,
            order_type="buy_limit",
            entry=zone_high,
            stop=zone_low - 0.20 * atr,
            target_r=SHADOW_TARGET_R,
            variant="zone_touch_limit",
        )
        if limit:
            candidates.append(limit)
    elif side == "SELL" and zone_low > price:
        limit = _trade_geometry(
            side=side,
            order_type="sell_limit",
            entry=zone_low,
            stop=zone_high + 0.20 * atr,
            target_r=SHADOW_TARGET_R,
            variant="zone_touch_limit",
        )
        if limit:
            candidates.append(limit)

    # Variant 3: simple momentum confirmation. This is intentionally generic so
    # EVE can compare confirmation against market/zone-touch execution without
    # weakening the much stricter user-facing confirmation policy.
    if side == "BUY":
        entry = price + 0.15 * atr
        stop = price - 0.85 * atr
        order_type = "buy_stop"
    else:
        entry = price - 0.15 * atr
        stop = price + 0.85 * atr
        order_type = "sell_stop"
    confirm = _trade_geometry(
        side=side,
        order_type=order_type,
        entry=entry,
        stop=stop,
        target_r=SHADOW_TARGET_R,
        variant="momentum_confirmation",
    )
    if confirm:
        candidates.append(confirm)

    return candidates


def _shadow_ids(state: dict[str, Any], variant: str) -> tuple[str, str]:
    family = str(state.get("setup_family") or state.get("setup_signature") or "unknown")
    as_of = str(state.get("as_of") or "")
    day = as_of[:10] if len(as_of) >= 10 else core.utc_now().date().isoformat()
    session = str((state.get("market") or {}).get("session") or "unknown")
    symbol = str(state.get("symbol") or "XAU/USD")
    shadow_family = hashlib.sha1(f"{family}|{variant}".encode()).hexdigest()[:20]
    episode = hashlib.sha1(f"{symbol}|{day}|{session}|{family}|{variant}".encode()).hexdigest()[:24]
    return shadow_family, episode


async def _record_shadow_variants(self: core.LiveTrader, state: dict[str, Any]) -> dict[str, Any]:
    observed = _recent_observation_time(state)
    if observed is None:
        return {"status": "skipped", "reason": "no_recent_connected_observation"}
    session = session_gate._session_status()
    if not bool(session.get("open")):
        return {"status": "skipped", "reason": "outside_user_facing_trade_window"}

    bucket = observed.replace(minute=(observed.minute // 5) * 5, second=0, microsecond=0)
    if getattr(self, "_shadow_last_bucket_v83", None) == bucket:
        return {"status": "throttled", "bucket": bucket.isoformat()}
    self._shadow_last_bucket_v83 = bucket

    candidates = _shadow_candidates(state)
    if not candidates:
        return {"status": "skipped", "reason": "no_shadow_candidate"}

    inserted = 0
    existing_count = 0
    errors: list[str] = []
    for trade in candidates:
        variant = str(trade.get("shadow_variant") or "unknown")
        family, episode = _shadow_ids(state, variant)
        try:
            existing = await self.repo.client.get(
                "live_trader_opinions",
                params={
                    "select": "id",
                    "learning_version": f"eq.{SHADOW_VERSION}",
                    "setup_family": f"eq.{family}",
                    "episode_key": f"eq.{episode}",
                    "limit": "1",
                },
            )
            if existing:
                existing_count += 1
                continue
            descriptor = dict(state.get("setup_family_descriptor") or {})
            descriptor["shadow_variant"] = variant
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
                    "learning_version": SHADOW_VERSION,
                    "independent_sample": False,
                    "market_state": {
                        "market": state.get("market"),
                        "bias": state.get("bias"),
                        "liquidity": state.get("liquidity"),
                        "setup_family_descriptor": descriptor,
                        "shadow_research": {
                            "version": VERSION,
                            "variant": variant,
                            "publication_authority": False,
                            "visible_trade_gate_unchanged": True,
                            "observed_at": observed.isoformat(),
                        },
                    },
                    "zones": state.get("zones") or {},
                    "trade_idea": trade,
                    "opinion_text": "Research-only shadow trade; never shown as a Live Trader recommendation.",
                    "status": "open",
                },
                return_rows=False,
            )
            inserted += 1
        except Exception as exc:
            errors.append(str(exc)[:160])
            core.logger.warning("Live Trader v83 shadow record failed for %s: %s", variant, exc)

    return {
        "status": "ok" if not errors else "partial",
        "inserted": inserted,
        "already_present": existing_count,
        "candidates": len(candidates),
        "errors": errors[:3],
        "bucket": bucket.isoformat(),
    }


async def _resolve_shadow_outcomes(self: core.LiveTrader) -> dict[str, Any]:
    now = core.utc_now()
    last = getattr(self, "_shadow_last_resolution_v83", None)
    if isinstance(last, datetime) and now - last < timedelta(seconds=SHADOW_RESOLVE_INTERVAL_SECONDS):
        return {"status": "throttled"}
    self._shadow_last_resolution_v83 = now
    cutoff = now - timedelta(minutes=self.settings.live_trader_learning_horizon_minutes)

    try:
        rows = await self.repo.client.get(
            "live_trader_opinions",
            params={
                "select": "id,observed_at,price,bias,horizon_minutes,market_state,trade_idea",
                "learning_version": f"eq.{SHADOW_VERSION}",
                "status": "eq.open",
                "observed_at": f"lte.{cutoff.isoformat()}",
                "order": "observed_at.asc",
                "limit": str(SHADOW_RESOLVE_LIMIT),
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
            market_state["shadow_resolution"] = {
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
            core.logger.warning("Live Trader v83 shadow resolution failed: %s", exc)
    return {"status": "ok", "resolved": resolved, "eligible": len(rows)}


def _trade_skill_from_reviews(reviews: list[dict[str, Any]]) -> dict[str, Any]:
    triggered = [row for row in reviews if bool(row.get("triggered")) and row.get("realised_r") is not None]
    n = len(triggered)
    total_r = sum(_num(row.get("realised_r")) for row in triggered)
    avg_r = total_r / n if n else 0.0
    wins = sum(1 for row in triggered if _num(row.get("realised_r")) > 0)
    losses = sum(1 for row in triggered if _num(row.get("realised_r")) < 0)
    breakeven = n - wins - losses
    win_rate = wins / n if n else 0.0

    performance = core.clamp((avg_r + 0.25) / 0.75, 0.0, 1.0)
    win_component = core.clamp(win_rate / 0.55, 0.0, 1.0)
    evidence = min(1.0, n / 30.0)
    score = 10.0 * (0.55 * performance + 0.25 * win_component + 0.20 * evidence)
    if n < 10:
        score = min(score, 3.0)
    elif n < 30:
        score = min(score, 6.5)
    score = round(core.clamp(score, 0.0, 10.0), 2)

    if n < 30:
        grade = "UNPROVEN"
    elif score < 4.0:
        grade = "POOR"
    elif score < 6.0:
        grade = "DEVELOPING"
    elif score < 7.5:
        grade = "PROMISING"
    else:
        grade = "PROVEN"

    return {
        "version": VERSION,
        "score": score,
        "grade": grade,
        "published_triggered": n,
        "wins": wins,
        "losses": losses,
        "breakeven": breakeven,
        "total_r": round(total_r, 3),
        "average_r": round(avg_r, 3) if n else None,
        "win_rate": round(win_rate, 3) if n else None,
        "minimum_proven_sample": 30,
        "meaning": (
            "Trade Skill is intentionally conservative. Only completed published forward campaigns can make this score high; "
            "historical backtests and shadow research are shown separately and cannot disguise poor live results."
        ),
    }


def _shadow_stats(rows: list[dict[str, Any]]) -> dict[str, Any]:
    triggered = [row for row in rows if row.get("entry_triggered") is True and row.get("realised_r") is not None]
    total_r = sum(_num(row.get("realised_r")) for row in triggered)
    wins = sum(1 for row in triggered if _num(row.get("realised_r")) > 0)
    losses = sum(1 for row in triggered if _num(row.get("realised_r")) < 0)
    return {
        "resolved": len(rows),
        "triggered": len(triggered),
        "wins": wins,
        "losses": losses,
        "total_r": round(total_r, 3),
        "average_r": round(total_r / len(triggered), 3) if triggered else None,
        "research_only": True,
        "publication_authority": False,
    }


async def _trade_skill(self: core.LiveTrader) -> dict[str, Any]:
    now = core.utc_now()
    cached_at = getattr(self, "_trade_skill_cache_at_v83", None)
    cached = getattr(self, "_trade_skill_cache_v83", None)
    if isinstance(cached_at, datetime) and isinstance(cached, dict):
        if now - cached_at < timedelta(seconds=TRADE_SKILL_CACHE_SECONDS):
            return dict(cached)

    try:
        reviews = await self.repo.client.get(
            "live_trader_trade_reviews",
            params={
                "select": "triggered,realised_r,outcome,completed_at",
                "symbol": f"eq.{self.symbol}",
                "order": "completed_at.desc",
                "limit": "500",
            },
        )
    except Exception:
        reviews = []
    try:
        shadow = await self.repo.client.get(
            "live_trader_opinions",
            params={
                "select": "entry_triggered,realised_r,trade_outcome,observed_at",
                "learning_version": f"eq.{SHADOW_VERSION}",
                "status": "eq.resolved",
                "order": "observed_at.desc",
                "limit": "2000",
            },
        )
    except Exception:
        shadow = []

    result = _trade_skill_from_reviews(list(reviews))
    result["shadow_research"] = _shadow_stats(list(shadow))
    self._trade_skill_cache_at_v83 = now
    self._trade_skill_cache_v83 = dict(result)
    return result


async def _refresh_state_v83(self: core.LiveTrader, *, force_rows: bool = False) -> dict[str, Any]:
    state = dict(await _current_refresh_state(self, force_rows=force_rows))
    forward = await _ensure_forward_observation(self, state)
    shadow = await _record_shadow_variants(self, state)
    resolution = await _resolve_shadow_outcomes(self)
    diagnostics = dict(state.get("forward_learning_health") or {})
    diagnostics.update(
        {
            "version": VERSION,
            "forward": forward,
            "shadow_recording": shadow,
            "shadow_resolution": resolution,
            "visible_trade_gate_unchanged": True,
            "shadow_trades_never_published": True,
        }
    )
    state["forward_learning_health"] = diagnostics
    self._latest_state = state
    return state


async def _learning_summary_v83(self: core.LiveTrader) -> dict[str, Any]:
    summary = dict(await _current_learning_summary(self))
    summary["trade_skill"] = await _trade_skill(self)
    summary["forward_learning_health"] = dict((self._latest_state or {}).get("forward_learning_health") or {})
    summary["system_maturity_note"] = (
        "The existing intelligence index measures architecture and evidence maturity. It is not the Trade Skill score."
    )
    return summary


def _runtime_status_v83(self: core.LiveTrader) -> dict[str, Any]:
    status = dict(_current_runtime_status(self))
    status.update(
        {
            "forward_shadow_learning_version": VERSION,
            "shadow_learning_version": SHADOW_VERSION,
            "forward_learning_self_healing": True,
            "shadow_trades_publication_authority": False,
            "visible_trade_gate_unchanged": True,
        }
    )
    return status


core.LiveTrader.refresh_state = _refresh_state_v83  # type: ignore[method-assign]
core.LiveTrader.learning_summary = _learning_summary_v83  # type: ignore[method-assign]
core.LiveTrader.runtime_status = _runtime_status_v83  # type: ignore[method-assign]
