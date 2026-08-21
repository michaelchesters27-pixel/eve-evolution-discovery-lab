from __future__ import annotations

import math
from datetime import datetime, timedelta, timezone
from typing import Any

from app.services import live_trader as core
from app.services import live_trader_learning_v2 as v2
from app.services import live_trader_learning_v22 as v22
from app.services import live_trader_market_events_v23 as v23

BIAS_VERSION = "eve-live-bias-v2"
LEARNING_VERSION = "eve-live-learning-v2.4"
OUTCOME_POLICY = (
    "Resolve every learning observation from completed M5 data at or before its exact horizon. "
    "Trade-path bars must start after the observation and must be fully completed by the horizon; "
    "no candle that extends beyond the learning window may contribute to the score."
)

_original_runtime_status = v2.LiveTrader.runtime_status


def _num(value: Any, default: float = 0.0) -> float:
    return core.number(value, default)


def _clamp(value: float, low: float, high: float) -> float:
    return core.clamp(value, low, high)


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


def _sign(value: float, tolerance: float = 1e-9) -> int:
    if value > tolerance:
        return 1
    if value < -tolerance:
        return -1
    return 0


def _candle_conviction(item: dict[str, Any]) -> float:
    direction = _sign(_num(item.get("direction")))
    if direction == 0:
        return 0.0
    range_price = max(_num(item.get("range_price")), 0.0)
    body_abs = abs(_num(item.get("body_abs"), abs(_num(item.get("body_price")))))
    body_ratio = _clamp(body_abs / range_price, 0.0, 1.0) if range_price > 0 else 0.0
    close_location = _clamp(_num(item.get("close_location"), 0.5), 0.0, 1.0)
    close_edge = abs(close_location - 0.5) * 2.0
    conviction = 0.45 + body_ratio * 0.35 + close_edge * 0.20
    return direction * _clamp(conviction, 0.45, 1.0)


def _normalised_move(value_pct: Any, atr_pct: float, scale: float) -> float:
    if atr_pct <= 0:
        return 0.0
    return math.tanh((_num(value_pct) / atr_pct) / max(scale, 0.1))


def _bias_v24(self: v2.LiveTrader, latest: dict[str, Any]) -> tuple[dict[str, Any], float]:
    context = dict(latest.get("mtf_context") or {})
    weights = {"D1": 4.0, "H4": 3.5, "H1": 3.0, "M30": 2.25, "M15": 2.0, "M5": 1.25}

    structural_numerator = 0.0
    structural_denominator = 0.0
    timeframes: dict[str, Any] = {}
    directional_votes: list[int] = []

    for timeframe, weight in weights.items():
        item = dict(context.get(timeframe) or {})
        conviction = _candle_conviction(item)
        direction = _sign(conviction)
        timeframes[timeframe] = {
            "direction": core.direction_label(direction),
            "return_pct": core.rounded(item.get("return_pct"), 3),
            "conviction": round(abs(conviction), 3) if direction else 0.0,
        }
        if direction:
            structural_numerator += conviction * weight
            structural_denominator += weight
            directional_votes.append(direction)

    structural_score = structural_numerator / structural_denominator if structural_denominator else 0.0

    close = max(_num(latest.get("close")), 0.0)
    atr = max(_num(latest.get("atr_14")), 0.0)
    atr_pct = (atr / close) * 100.0 if close > 0 and atr > 0 else 0.0
    trend_12 = math.tanh(_num(latest.get("trend_12_atr")) * 4.0)
    trend_48 = math.tanh(_num(latest.get("trend_48_atr")) * 5.0)
    return_12 = _normalised_move(latest.get("return_12_pct"), atr_pct, 1.5)
    return_48 = _normalised_move(latest.get("return_48_pct"), atr_pct, 3.0)
    momentum_score = (trend_12 * 1.5 + trend_48 * 2.0 + return_12 + return_48) / 5.5

    regime = str(latest.get("regime") or "unknown")
    regime_bias = 0.0
    if regime == "trend_up":
        regime_bias = 0.08
    elif regime == "trend_down":
        regime_bias = -0.08

    score = _clamp(structural_score * 0.74 + momentum_score * 0.26 + regime_bias, -1.0, 1.0)
    if score >= 0.22:
        overall = "bullish"
    elif score <= -0.22:
        overall = "bearish"
    else:
        overall = "neutral"

    momentum_vote = _sign(momentum_score, 0.08)
    votes = directional_votes + ([momentum_vote] if momentum_vote else [])
    agreement = abs(sum(votes)) / len(votes) if votes else 0.0
    breadth = len(directional_votes) / len(weights)
    disagreement_penalty = 4.0 if structural_score * momentum_score < -0.04 else 0.0
    compression_penalty = 3.0 if regime == "compression" else 0.0
    raw_confidence = 46.0 + abs(score) * 34.0 + agreement * 8.0 + breadth * 4.0
    raw_confidence -= disagreement_penalty + compression_penalty

    # Preserve M1 as diagnostics only; it never contributes to the v2 bias score.
    m1 = dict(context.get("M1") or {})
    timeframes["M1"] = {
        "direction": core.direction_label(_num(m1.get("direction"))),
        "return_pct": None,
        "conviction": None,
        "weight": 0,
    }

    return {
        "overall": overall,
        "raw_score": round(score, 3),
        "confidence": int(round(_clamp(raw_confidence, 40, 92))),
        "timeframes": timeframes,
        "htf_alignment": int(_num(context.get("higher_timeframe_alignment_score"))),
        "all_alignment": int(_num(context.get("direction_alignment_score"))),
        "engine_version": BIAS_VERSION,
        "components": {
            "structural_score": round(structural_score, 3),
            "momentum_score": round(momentum_score, 3),
            "regime_bias": round(regime_bias, 3),
            "agreement": round(agreement, 3),
            "breadth": round(breadth, 3),
        },
    }, score


def _fully_completed_bars(
    rows: list[dict[str, Any]],
    observed: datetime,
    horizon: datetime,
) -> list[dict[str, Any]]:
    completed: list[dict[str, Any]] = []
    for bar in rows:
        start = _parse_time(bar.get("candle_time"))
        if start is None:
            continue
        close_time = start + timedelta(minutes=5)
        # Exclude the candle already in progress when the live opinion was recorded,
        # and exclude any candle whose close occurs after the outcome horizon.
        if start >= observed and close_time <= horizon:
            completed.append(bar)
    return completed


def _horizon_endpoint(
    rows: list[dict[str, Any]],
    observed: datetime,
    horizon: datetime,
) -> tuple[float, datetime] | None:
    candidates: list[tuple[datetime, float]] = []
    for bar in rows:
        start = _parse_time(bar.get("candle_time"))
        if start is None:
            continue
        close_time = start + timedelta(minutes=5)
        if close_time <= observed or close_time > horizon:
            continue
        price = _num(bar.get("close"))
        if price > 0:
            candidates.append((close_time, price))
    if not candidates:
        return None
    close_time, price = max(candidates, key=lambda item: item[0])
    return price, close_time


async def _maybe_resolve_opinions_v24(self: v2.LiveTrader, _live_price: float) -> None:
    now = core.utc_now()
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
            start_price = _num(row.get("price"))
            if observed is None or start_price <= 0:
                continue
            horizon_minutes = int(_num(row.get("horizon_minutes"), self.settings.live_trader_learning_horizon_minutes))
            horizon = observed + timedelta(minutes=max(horizon_minutes, 1))
            endpoint = _horizon_endpoint(self._rows, observed, horizon)
            if endpoint is None:
                continue
            resolved_price, resolved_price_time = endpoint
            bars = _fully_completed_bars(self._rows, observed, horizon)
            direction_correct, move_pct, threshold = v2._direction_result(row, resolved_price)
            trade_result = v2._trade_path_result(row.get("trade_idea") or {}, bars, resolved_price)
            learning_success = trade_result.get("learning_success")
            if learning_success is None and str((row.get("trade_idea") or {}).get("order_type") or "none") == "none":
                learning_success = direction_correct
            await self.repo.client.patch(
                "live_trader_opinions",
                {
                    "status": "resolved",
                    "resolved_at": now.isoformat(),
                    "resolved_price": resolved_price,
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
            # Keep exact horizon diagnostics in the immutable market-state audit payload
            # without requiring a schema change for dedicated columns.
            market_state = dict(row.get("market_state") or {})
            market_state["learning_resolution"] = {
                "policy": OUTCOME_POLICY,
                "observed_at": observed.isoformat(),
                "horizon_at": horizon.isoformat(),
                "resolved_price_time": resolved_price_time.isoformat(),
                "fully_completed_path_bars": len(bars),
            }
            await self.repo.client.patch(
                "live_trader_opinions",
                {"market_state": market_state},
                filters={"id": f"eq.{row.get('id')}"},
            )
    except Exception as exc:
        core.logger.warning("Live Trader v2.4 could not resolve exact-horizon outcomes: %s", exc)


def _runtime_status_v24(self: v2.LiveTrader) -> dict[str, Any]:
    state = dict(_original_runtime_status(self))
    state.update(
        {
            "learning_version": LEARNING_VERSION,
            "bias_version": BIAS_VERSION,
            "bias_uses_m1": False,
            "learning_outcome_policy": OUTCOME_POLICY,
            "learning_horizon_is_causal": True,
        }
    )
    return state


# Start a fresh learning namespace because v2.4 changes outcome semantics. Historical
# v1-v2.3 rows remain untouched for audit; only v2.4 rows calibrate v2.4 confidence.
v23.LEARNING_VERSION = LEARNING_VERSION
v22.LEARNING_VERSION = LEARNING_VERSION
v2.LEARNING_VERSION = LEARNING_VERSION
v2.LiveTrader._bias = _bias_v24  # type: ignore[method-assign]
v2.LiveTrader._maybe_resolve_opinions = _maybe_resolve_opinions_v24  # type: ignore[method-assign]
v2.LiveTrader.runtime_status = _runtime_status_v24  # type: ignore[method-assign]
