from __future__ import annotations

import hashlib
from datetime import datetime, timedelta, timezone
from typing import Any

from app.services.live_trader import LiveTrader, clamp, number, utc_now

LEARNING_VERSION = "eve-live-learning-v2"
MIN_INDEPENDENT_EPISODES = 12
MIN_INDEPENDENT_DAYS = 3
PRIOR_WINS = 6.0
PRIOR_LOSSES = 6.0


def _parse_time(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _direction(value: Any) -> int:
    text = str(value or "neutral").lower()
    return 1 if text == "bullish" else -1 if text == "bearish" else 0


def _alignment_bucket(timeframes: dict[str, Any], names: tuple[str, ...]) -> str:
    score = sum(_direction((timeframes.get(name) or {}).get("direction")) for name in names)
    if score >= 2:
        return "bullish"
    if score <= -2:
        return "bearish"
    return "mixed"


def _momentum_bucket(value: Any) -> str:
    move = number(value)
    if move >= 0.04:
        return "up"
    if move <= -0.04:
        return "down"
    return "flat"


def _quality_bucket(zone: dict[str, Any] | None) -> str:
    if not zone:
        return "none"
    quality = number(zone.get("quality"))
    if quality >= 72:
        return "high"
    if quality >= 58:
        return "good"
    return "medium"


def _location_bucket(zones: dict[str, Any]) -> tuple[str, dict[str, Any] | None]:
    demand = (zones.get("demand") or [None])[0]
    supply = (zones.get("supply") or [None])[0]
    demand_distance = number(demand.get("distance_atr"), 999.0) if demand else 999.0
    supply_distance = number(supply.get("distance_atr"), 999.0) if supply else 999.0
    demand_status = str(demand.get("status") or "") if demand else ""
    supply_status = str(supply.get("status") or "") if supply else ""
    if demand and demand_status == "IN ZONE":
        return "in_demand", demand
    if supply and supply_status == "IN ZONE":
        return "in_supply", supply
    if demand and demand_distance <= 1.25 and demand_distance <= supply_distance:
        return "near_demand", demand
    if supply and supply_distance <= 1.25:
        return "near_supply", supply
    if demand_distance < supply_distance:
        return "middle_demand_side", demand
    if supply:
        return "middle_supply_side", supply
    return "middle", None


def setup_family_descriptor(state: dict[str, Any]) -> dict[str, str]:
    bias = state.get("bias") or {}
    timeframes = bias.get("timeframes") or {}
    market = state.get("market") or {}
    trade = state.get("trade") or {}
    zones = state.get("zones") or {}
    location, relevant_zone = _location_bucket(zones)
    return {
        "bias": str(bias.get("overall") or "neutral"),
        "session": str(market.get("session") or "unknown"),
        "regime": str(market.get("regime") or "unknown"),
        "order_type": str(trade.get("order_type") or "none"),
        "htf_alignment": _alignment_bucket(timeframes, ("D1", "H4", "H1")),
        "intraday_alignment": _alignment_bucket(timeframes, ("M30", "M15", "M5")),
        "location": location,
        "zone_quality": _quality_bucket(relevant_zone),
        "momentum_12": _momentum_bucket(market.get("return_12_pct")),
        "momentum_48": _momentum_bucket(market.get("return_48_pct")),
    }


def family_signature(state: dict[str, Any]) -> str:
    descriptor = setup_family_descriptor(state)
    raw = "|".join(f"{key}={descriptor[key]}" for key in sorted(descriptor))
    return hashlib.sha1(raw.encode()).hexdigest()[:20]


def episode_key(state: dict[str, Any]) -> str:
    zones = state.get("zones") or {}
    demand = (zones.get("demand") or [{}])[0]
    supply = (zones.get("supply") or [{}])[0]
    as_of = str(state.get("as_of") or "")
    day = as_of[:10] if len(as_of) >= 10 else utc_now().date().isoformat()
    session = str((state.get("market") or {}).get("session") or "unknown")
    raw = "|".join(
        [
            str(state.get("symbol") or "XAU/USD"),
            day,
            session,
            str(demand.get("id") or "no-demand"),
            str(supply.get("id") or "no-supply"),
        ]
    )
    return hashlib.sha1(raw.encode()).hexdigest()[:24]


def calibration_from_rows(rows: list[dict[str, Any]]) -> dict[str, Any]:
    independent: dict[str, dict[str, Any]] = {}
    for row in rows:
        outcome = row.get("learning_success")
        key = str(row.get("episode_key") or "")
        if outcome is None or not key or key in independent:
            continue
        independent[key] = row
    clean = list(independent.values())
    outcomes = [bool(row.get("learning_success")) for row in clean]
    days = {
        str(row.get("observed_at"))[:10]
        for row in clean
        if row.get("observed_at") and len(str(row.get("observed_at"))) >= 10
    }
    samples = len(outcomes)
    correct = sum(1 for value in outcomes if value)
    raw_accuracy = correct / samples if samples else None
    posterior_accuracy = (correct + PRIOR_WINS) / (samples + PRIOR_WINS + PRIOR_LOSSES) if samples else 0.5
    active = samples >= MIN_INDEPENDENT_EPISODES and len(days) >= MIN_INDEPENDENT_DAYS
    adjustment = clamp((posterior_accuracy - 0.5) * 20.0, -6.0, 6.0) if active else 0.0
    return {
        "samples": samples,
        "accuracy": round(raw_accuracy, 3) if raw_accuracy is not None else None,
        "posterior_accuracy": round(posterior_accuracy, 3),
        "confidence_adjustment": round(adjustment, 1),
        "independent_days": len(days),
        "active": active,
        "minimum_samples": MIN_INDEPENDENT_EPISODES,
        "minimum_days": MIN_INDEPENDENT_DAYS,
        "learning_version": LEARNING_VERSION,
    }


def _trade_path_result(
    trade: dict[str, Any],
    bars: list[dict[str, Any]],
    resolved_price: float,
) -> dict[str, Any]:
    order_type = str(trade.get("order_type") or "none")
    side = str(trade.get("side") or "").upper()
    if order_type == "none" or side not in {"BUY", "SELL"}:
        return {"entry_triggered": None, "trade_outcome": None, "realised_r": None, "learning_success": None}
    entry = number(trade.get("entry"))
    stop = number(trade.get("stop"))
    target = number(trade.get("target"))
    risk = abs(entry - stop)
    if entry <= 0 or risk <= 0 or target <= 0:
        return {"entry_triggered": False, "trade_outcome": "invalid", "realised_r": None, "learning_success": None}

    triggered = order_type == "market"
    for bar in bars:
        low = number(bar.get("low"))
        high = number(bar.get("high"))
        if not triggered:
            if order_type == "buy_limit":
                triggered = low <= entry
            elif order_type == "buy_stop":
                triggered = high >= entry
            elif order_type == "sell_limit":
                triggered = high >= entry
            elif order_type == "sell_stop":
                triggered = low <= entry
        if not triggered:
            continue
        # Conservative same-bar ambiguity rule: stop is assumed first, matching EVE's M1 replay safety policy.
        if side == "BUY":
            stop_hit = low <= stop
            target_hit = high >= target
        else:
            stop_hit = high >= stop
            target_hit = low <= target
        if stop_hit:
            return {"entry_triggered": True, "trade_outcome": "stop", "realised_r": -1.0, "learning_success": False}
        if target_hit:
            rr = abs(target - entry) / risk
            return {"entry_triggered": True, "trade_outcome": "target", "realised_r": round(rr, 3), "learning_success": True}

    if not triggered:
        return {"entry_triggered": False, "trade_outcome": "not_triggered", "realised_r": 0.0, "learning_success": None}
    mtm_r = (resolved_price - entry) / risk if side == "BUY" else (entry - resolved_price) / risk
    mtm_r = round(clamp(mtm_r, -1.0, max(number(trade.get("risk_reward")), 3.0)), 3)
    if mtm_r >= 0.15:
        outcome = "expired_win"
        success: bool | None = True
    elif mtm_r <= -0.15:
        outcome = "expired_loss"
        success = False
    else:
        outcome = "expired_flat"
        success = None
    return {"entry_triggered": True, "trade_outcome": outcome, "realised_r": mtm_r, "learning_success": success}


def _direction_result(row: dict[str, Any], resolved_price: float) -> tuple[bool, float, float]:
    start_price = number(row.get("price"))
    if start_price <= 0:
        return False, 0.0, 0.025
    move_pct = (resolved_price / start_price - 1.0) * 100.0
    market_state = row.get("market_state") or {}
    market = market_state.get("market") or {}
    atr = number(market.get("atr"))
    atr_pct = (atr / start_price) * 100.0 if atr > 0 else 0.0
    threshold = max(0.025, min(0.12, atr_pct * 0.5))
    bias = str(row.get("bias") or "neutral")
    correct = move_pct > threshold if bias == "bullish" else move_pct < -threshold if bias == "bearish" else abs(move_pct) <= threshold
    return correct, move_pct, threshold


def _signature_v2(self: LiveTrader, state: dict[str, Any]) -> str:
    descriptor = setup_family_descriptor(state)
    signature = family_signature(state)
    state["setup_family"] = signature
    state["setup_family_descriptor"] = descriptor
    state["learning_version"] = LEARNING_VERSION
    return signature


async def _calibration_v2(self: LiveTrader, signature: str) -> dict[str, Any]:
    try:
        rows = await self.repo.client.get(
            "live_trader_opinions",
            params={
                "select": "learning_success,episode_key,observed_at",
                "setup_family": f"eq.{signature}",
                "learning_version": f"eq.{LEARNING_VERSION}",
                "independent_sample": "eq.true",
                "status": "eq.resolved",
                "order": "observed_at.desc",
                "limit": "300",
            },
        )
    except Exception:
        return calibration_from_rows([])
    return calibration_from_rows(rows)


async def _maybe_record_opinion_v2(self: LiveTrader, state: dict[str, Any]) -> None:
    family = str(state.get("setup_family") or state.get("setup_signature") or family_signature(state))
    episode = episode_key(state)
    try:
        existing = await self.repo.client.get(
            "live_trader_opinions",
            params={
                "select": "id",
                "setup_family": f"eq.{family}",
                "episode_key": f"eq.{episode}",
                "learning_version": f"eq.{LEARNING_VERSION}",
                "limit": "1",
            },
        )
        if existing:
            return
        now = utc_now()
        await self.repo.client.insert(
            "live_trader_opinions",
            {
                "observed_at": now.isoformat(),
                "symbol": self.symbol,
                "price": state.get("price"),
                "bias": (state.get("bias") or {}).get("overall"),
                "confidence": (state.get("bias") or {}).get("confidence"),
                "horizon_minutes": self.settings.live_trader_learning_horizon_minutes,
                "setup_signature": family,
                "setup_family": family,
                "episode_key": episode,
                "learning_version": LEARNING_VERSION,
                "independent_sample": True,
                "market_state": {
                    "market": state.get("market"),
                    "bias": state.get("bias"),
                    "liquidity": state.get("liquidity"),
                    "setup_family_descriptor": state.get("setup_family_descriptor"),
                },
                "zones": state.get("zones") or {},
                "trade_idea": state.get("trade") or {},
                "opinion_text": state.get("opinion") or "",
                "status": "open",
            },
            return_rows=False,
        )
        self._last_recorded_signature = family
        self._last_opinion_at = now
    except Exception as exc:
        # Unique index is the final race-safe deduplication guard.
        import logging
        logging.getLogger(__name__).warning("Live Trader v2 could not record independent opinion: %s", exc)


async def _maybe_resolve_opinions_v2(self: LiveTrader, price: float) -> None:
    now = utc_now()
    if self._last_resolution_at and now - self._last_resolution_at < timedelta(seconds=30):
        return
    self._last_resolution_at = now
    cutoff = now - timedelta(minutes=self.settings.live_trader_learning_horizon_minutes)
    try:
        rows = await self.repo.client.get(
            "live_trader_opinions",
            params={
                "select": "id,observed_at,price,bias,horizon_minutes,market_state,trade_idea",
                "status": "eq.open",
                "learning_version": f"eq.{LEARNING_VERSION}",
                "independent_sample": "eq.true",
                "observed_at": f"lte.{cutoff.isoformat()}",
                "order": "observed_at.asc",
                "limit": "100",
            },
        )
        for row in rows:
            observed = _parse_time(row.get("observed_at"))
            if observed is None or number(row.get("price")) <= 0:
                continue
            horizon = int(number(row.get("horizon_minutes"), self.settings.live_trader_learning_horizon_minutes))
            end = observed + timedelta(minutes=max(horizon, 1))
            bars = []
            for bar in self._rows:
                bar_time = _parse_time(bar.get("candle_time"))
                if bar_time is not None and observed <= bar_time <= end:
                    bars.append(bar)
            direction_correct, move_pct, threshold = _direction_result(row, price)
            trade_result = _trade_path_result(row.get("trade_idea") or {}, bars, price)
            learning_success = trade_result.get("learning_success")
            if learning_success is None and str((row.get("trade_idea") or {}).get("order_type") or "none") == "none":
                learning_success = direction_correct
            await self.repo.client.patch(
                "live_trader_opinions",
                {
                    "status": "resolved",
                    "resolved_at": now.isoformat(),
                    "resolved_price": price,
                    "realised_move_pct": round(move_pct, 5),
                    "direction_correct": direction_correct,
                    "score_threshold_pct": round(threshold, 5),
                    "entry_triggered": trade_result.get("entry_triggered"),
                    "trade_outcome": trade_result.get("trade_outcome"),
                    "realised_r": trade_result.get("realised_r"),
                    "learning_success": learning_success,
                },
                filters={"id": f"eq.{row.get('id')}"},
            )
    except Exception as exc:
        import logging
        logging.getLogger(__name__).warning("Live Trader v2 could not resolve independent outcomes: %s", exc)


async def _learning_summary_v2(self: LiveTrader) -> dict[str, Any]:
    try:
        rows = await self.repo.client.get(
            "live_trader_opinions",
            params={
                "select": "learning_success,direction_correct,trade_outcome,realised_r,observed_at,setup_family,episode_key",
                "status": "eq.resolved",
                "learning_version": f"eq.{LEARNING_VERSION}",
                "independent_sample": "eq.true",
                "order": "observed_at.desc",
                "limit": "2000",
            },
        )
    except Exception:
        rows = []
    decision_outcomes = [bool(row.get("learning_success")) for row in rows if row.get("learning_success") is not None]
    directional = [bool(row.get("direction_correct")) for row in rows if row.get("direction_correct") is not None]
    actionable = [row for row in rows if row.get("trade_outcome") not in {None, "not_triggered", "invalid"}]
    trade_successes = [bool(row.get("learning_success")) for row in actionable if row.get("learning_success") is not None]
    days = {str(row.get("observed_at"))[:10] for row in rows if row.get("observed_at")}
    families = {str(row.get("setup_family")) for row in rows if row.get("setup_family")}
    return {
        "resolved": len(decision_outcomes),
        "independent_episodes": len({str(row.get("episode_key")) for row in rows if row.get("episode_key")}),
        "independent_days": len(days),
        "families_seen": len(families),
        "correct": sum(1 for value in decision_outcomes if value),
        "accuracy": round(sum(1 for value in decision_outcomes if value) / len(decision_outcomes), 3) if decision_outcomes else None,
        "directional_accuracy": round(sum(1 for value in directional if value) / len(directional), 3) if directional else None,
        "actionable_trades": len(actionable),
        "trade_accuracy": round(sum(1 for value in trade_successes if value) / len(trade_successes), 3) if trade_successes else None,
        "horizon_minutes": self.settings.live_trader_learning_horizon_minutes,
        "version": LEARNING_VERSION,
        "policy": (
            f"Learning v2 counts one independent result per market episode and generalises across similar condition families. "
            f"Confidence cannot calibrate until a family has at least {MIN_INDEPENDENT_EPISODES} independent outcomes across "
            f"{MIN_INDEPENDENT_DAYS} different trading days; estimates are shrinkage-adjusted and capped at ±6 confidence points."
        ),
        "legacy_v1_history_preserved": True,
    }


_original_runtime_status = LiveTrader.runtime_status


def _runtime_status_v2(self: LiveTrader) -> dict[str, Any]:
    state = dict(_original_runtime_status(self))
    state.update(
        {
            "learning_version": LEARNING_VERSION,
            "learning_independence": "one outcome per setup family per market episode",
            "learning_min_independent_samples": MIN_INDEPENDENT_EPISODES,
            "learning_min_independent_days": MIN_INDEPENDENT_DAYS,
        }
    )
    return state


# Install the v2 learning policy without changing the live price, zone, bias, chat or execution engines.
LiveTrader._signature = _signature_v2  # type: ignore[method-assign]
LiveTrader._calibration = _calibration_v2  # type: ignore[method-assign]
LiveTrader._maybe_record_opinion = _maybe_record_opinion_v2  # type: ignore[method-assign]
LiveTrader._maybe_resolve_opinions = _maybe_resolve_opinions_v2  # type: ignore[method-assign]
LiveTrader.learning_summary = _learning_summary_v2  # type: ignore[method-assign]
LiveTrader.runtime_status = _runtime_status_v2  # type: ignore[method-assign]
