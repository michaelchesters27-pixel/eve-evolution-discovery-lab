from __future__ import annotations

import math
from typing import Any

from app.services import live_trader as core
from app.services import live_trader_market_events_v23 as market_events

SESSION_OUTLOOK_VERSION = "eve-live-session-outlook-v1"

_current_opinion_text = core.LiveTrader._opinion_text
_current_answer = core.LiveTrader.answer
_current_runtime_status = core.LiveTrader.runtime_status


def _num(value: Any, default: float = 0.0) -> float:
    return core.number(value, default)


def _clamp(value: float, low: float, high: float) -> float:
    return core.clamp(value, low, high)


def _sign(direction: Any) -> int:
    text = str(direction or "neutral").lower()
    return 1 if text == "bullish" else -1 if text == "bearish" else 0


def _tf_value(item: dict[str, Any]) -> float | None:
    method = str(item.get("method") or "")
    if method in {"missing", "stale", "insufficient_history"} or bool(item.get("stale")):
        return None
    raw_structure = item.get("structure_score")
    try:
        structure = float(raw_structure)
    except (TypeError, ValueError):
        structure = float("nan")
    if math.isfinite(structure):
        # Use the continuous structural score even when the panel label itself is
        # neutral. This is deliberately an opinion signal, not a trading vote.
        return _clamp(structure, -1.0, 1.0)
    direction = _sign(item.get("direction"))
    return direction * 0.7 if direction else 0.0


def _weighted_tf_component(
    timeframes: dict[str, Any],
    weights: dict[str, float],
) -> tuple[float | None, str]:
    total = 0.0
    weighted = 0.0
    labels: list[str] = []
    for timeframe, weight in weights.items():
        item = dict(timeframes.get(timeframe) or {})
        value = _tf_value(item)
        if value is None:
            continue
        total += weight
        weighted += value * weight
        labels.append(f"{timeframe} {str(item.get('direction') or 'neutral')}" )
    if total <= 0:
        return None, ""
    return weighted / total, ", ".join(labels)


def _session_range(state: dict[str, Any]) -> tuple[float | None, float | None, str]:
    market = dict(state.get("market") or {})
    liquidity = dict(state.get("liquidity") or {})
    session = str(market.get("session") or "unknown").lower()
    if "new" in session or "york" in session:
        low = _num(liquidity.get("new_york_low"), float("nan"))
        high = _num(liquidity.get("new_york_high"), float("nan"))
        label = "New York"
    elif "london" in session:
        low = _num(liquidity.get("london_low"), float("nan"))
        high = _num(liquidity.get("london_high"), float("nan"))
        label = "London"
    else:
        low = _num(liquidity.get("recent_low"), float("nan"))
        high = _num(liquidity.get("recent_high"), float("nan"))
        label = str(market.get("session") or "current").replace("_", " ").title()
    if not math.isfinite(low) or not math.isfinite(high) or high <= low:
        return None, None, label
    return low, high, label


def _zone_component(state: dict[str, Any]) -> tuple[float | None, str]:
    price = _num(state.get("price"), float("nan"))
    zones = dict(state.get("zones") or {})
    demand = (zones.get("demand") or [None])[0]
    supply = (zones.get("supply") or [None])[0]
    if not math.isfinite(price):
        return None, ""

    if demand and _num(demand.get("low")) <= price <= _num(demand.get("high")):
        quality = _clamp(_num(demand.get("quality"), 60.0) / 100.0, 0.4, 1.0)
        return 0.8 * quality, "Price is inside current demand."
    if supply and _num(supply.get("low")) <= price <= _num(supply.get("high")):
        quality = _clamp(_num(supply.get("quality"), 60.0) / 100.0, 0.4, 1.0)
        return -0.8 * quality, "Price is inside current supply."

    if demand and supply:
        demand_distance = _num(demand.get("distance_atr"), 99.0)
        supply_distance = _num(supply.get("distance_atr"), 99.0)
        if math.isfinite(demand_distance) and math.isfinite(supply_distance):
            value = _clamp((supply_distance - demand_distance) / 2.5, -1.0, 1.0) * 0.55
            if value > 0.05:
                return value, "Price is closer to current demand than current supply."
            if value < -0.05:
                return value, "Price is closer to current supply than current demand."
            return value, "Price is roughly balanced between current demand and supply."
    return None, ""


def _flip_level(state: dict[str, Any], direction: str) -> float | None:
    price = _num(state.get("price"), float("nan"))
    if not math.isfinite(price) or price <= 0:
        return None
    zones = dict(state.get("zones") or {})
    liquidity = dict(state.get("liquidity") or {})
    candidates: list[float] = []
    if direction == "bullish":
        demand = (zones.get("demand") or [None])[0]
        if demand:
            candidates.append(_num(demand.get("low")))
        for key in ("recent_low", "london_low", "new_york_low", "previous_day_low"):
            candidates.append(_num(liquidity.get(key)))
        valid = [value for value in candidates if 0 < value < price]
        return max(valid) if valid else None

    supply = (zones.get("supply") or [None])[0]
    if supply:
        candidates.append(_num(supply.get("high")))
    for key in ("recent_high", "london_high", "new_york_high", "previous_day_high"):
        candidates.append(_num(liquidity.get(key)))
    valid = [value for value in candidates if value > price]
    return min(valid) if valid else None


def build_session_outlook(self: core.LiveTrader, state: dict[str, Any]) -> dict[str, Any]:
    bias = dict(state.get("bias") or {})
    timeframes = dict(bias.get("timeframes") or {})
    market = dict(state.get("market") or {})
    liquidity = dict(state.get("liquidity") or {})
    price = _num(state.get("price"), float("nan"))

    components: list[dict[str, Any]] = []

    def add(name: str, value: float | None, weight: float, detail: str) -> None:
        if value is None or not math.isfinite(value) or weight <= 0:
            return
        components.append(
            {
                "name": name,
                "value": round(_clamp(value, -1.0, 1.0), 4),
                "weight": weight,
                "detail": detail,
            }
        )

    intraday, intraday_detail = _weighted_tf_component(
        timeframes,
        {"H1": 1.4, "M30": 1.0, "M15": 1.5, "M5": 1.2},
    )
    add("intraday_structure", intraday, 0.39, f"Intraday structure: {intraday_detail}." if intraday_detail else "")

    higher, higher_detail = _weighted_tf_component(timeframes, {"D1": 0.55, "H4": 1.0})
    add("higher_timeframe", higher, 0.12, f"Higher-timeframe structure: {higher_detail}." if higher_detail else "")

    return_12 = _num(market.get("return_12_pct"))
    return_48 = _num(market.get("return_48_pct"))
    momentum_12 = math.tanh(return_12 / 0.12) if math.isfinite(return_12) else 0.0
    momentum_48 = math.tanh(return_48 / 0.30) if math.isfinite(return_48) else 0.0
    momentum = momentum_12 * 0.68 + momentum_48 * 0.32
    add(
        "momentum",
        momentum,
        0.18,
        f"Momentum: 12-bar {return_12:+.3f}%, 48-bar {return_48:+.3f}%.",
    )

    event = dict(liquidity.get("primary_event") or {})
    event_implication = _sign(event.get("implication"))
    if event_implication:
        strength = _clamp(_num(event.get("strength"), 50.0) / 100.0, 0.35, 1.0)
        event_value = event_implication * strength
        level = _num(event.get("level"), float("nan"))
        level_text = f" around {level:.2f}" if math.isfinite(level) and level > 0 else ""
        add(
            "liquidity_event",
            event_value,
            0.14,
            f"{str(event.get('label') or 'Liquidity event').title()}{level_text} points {str(event.get('implication') or 'neutral')}.",
        )

    zone_value, zone_detail = _zone_component(state)
    add("zone_location", zone_value, 0.07, zone_detail)

    session_low, session_high, session_label = _session_range(state)
    if session_low is not None and session_high is not None and math.isfinite(price):
        midpoint = (session_low + session_high) / 2.0
        half_range = max((session_high - session_low) / 2.0, 0.01)
        session_position = _clamp((price - midpoint) / half_range, -1.0, 1.0)
        relation = "above" if session_position > 0.05 else "below" if session_position < -0.05 else "near"
        add(
            "session_position",
            session_position,
            0.06,
            f"Price is {relation} the {session_label} range midpoint.",
        )

    raw_bias_score = _clamp(_num(bias.get("raw_score")), -1.0, 1.0)
    add("weighted_bias", raw_bias_score, 0.04, f"Underlying weighted bias score is {raw_bias_score:+.2f}.")

    active_weight = sum(float(component["weight"]) for component in components)
    if active_weight > 0:
        raw_score = sum(float(component["value"]) * float(component["weight"]) for component in components) / active_weight
    else:
        previous = dict((getattr(self, "_latest_state", {}) or {}).get("session_outlook") or {})
        raw_score = _num(previous.get("score"), 0.001)

    session_key = f"{str(state.get('as_of') or '')[:10]}|{str(market.get('session') or 'unknown')}"
    previous = dict((getattr(self, "_latest_state", {}) or {}).get("session_outlook") or {})
    smoothed_score = raw_score
    if previous and str(previous.get("session_key") or "") == session_key:
        previous_score = _num(previous.get("score"))
        smoothed_score = previous_score * 0.55 + raw_score * 0.45
        previous_direction = str(previous.get("direction") or "")
        candidate_direction = "bullish" if smoothed_score >= 0 else "bearish"
        if previous_direction in {"bullish", "bearish"} and candidate_direction != previous_direction and abs(smoothed_score) < 0.11:
            smoothed_score = (0.025 if previous_direction == "bullish" else -0.025)

    direction = "bullish" if smoothed_score >= 0 else "bearish"
    direction_sign = 1 if direction == "bullish" else -1
    evidence_strength = (
        sum(abs(float(component["value"])) * float(component["weight"]) for component in components) / active_weight
        if active_weight > 0
        else 0.0
    )
    aligned_weight = sum(
        float(component["weight"])
        for component in components
        if float(component["value"]) * direction_sign > 0
    )
    agreement = aligned_weight / active_weight if active_weight > 0 else 0.5
    confidence = 50.0 + abs(smoothed_score) * 27.0 + evidence_strength * 10.0 + max(0.0, agreement - 0.5) * 8.0

    data_quality = dict(bias.get("data_quality") or {})
    critical_stale = list(data_quality.get("critical_stale") or [])
    if critical_stale:
        confidence = min(confidence, 58.0)
    confidence_int = int(round(_clamp(confidence, 51.0, 86.0)))

    if confidence_int <= 57:
        conviction = "slight"
    elif confidence_int <= 66:
        conviction = "moderate"
    elif confidence_int <= 76:
        conviction = "clear"
    else:
        conviction = "strong"

    aligned_components = sorted(
        [component for component in components if float(component["value"]) * direction_sign > 0],
        key=lambda component: abs(float(component["value"]) * float(component["weight"])),
        reverse=True,
    )
    opposing_components = sorted(
        [component for component in components if float(component["value"]) * direction_sign < 0],
        key=lambda component: abs(float(component["value"]) * float(component["weight"])),
        reverse=True,
    )
    reasons = [str(component.get("detail") or "") for component in aligned_components[:3] if component.get("detail")]
    headwinds = [str(component.get("detail") or "") for component in opposing_components[:2] if component.get("detail")]

    flip_level = _flip_level(state, direction)
    opposite = "bearish" if direction == "bullish" else "bullish"
    if flip_level is not None:
        verb = "loses" if direction == "bullish" else "reclaims"
        flip_text = (
            f"I would seriously consider flipping {opposite} if price {verb} {flip_level:.2f} "
            f"and M15/M5 structure stays {opposite}."
        )
    else:
        flip_text = f"I would flip {opposite} if M15/M5 structure and momentum both turn {opposite}."

    if critical_stale:
        reasons.append(f"Data-quality warning: stale critical timeframe(s): {', '.join(critical_stale)}; confidence is capped.")

    return {
        "version": SESSION_OUTLOOK_VERSION,
        "direction": direction,
        "confidence": confidence_int,
        "conviction": conviction,
        "score": round(smoothed_score, 4),
        "raw_score": round(raw_score, 4),
        "agreement": round(agreement, 3),
        "session": str(market.get("session") or "unknown"),
        "session_label": session_label,
        "session_key": session_key,
        "reasons": reasons,
        "headwinds": headwinds,
        "flip_level": round(flip_level, 3) if flip_level is not None else None,
        "flip_text": flip_text,
        "trade_gate_independent": True,
        "affects_trade_gate": False,
        "components": components,
    }


def _outlook_sentence(state: dict[str, Any]) -> str:
    outlook = dict(state.get("session_outlook") or {})
    direction = str(outlook.get("direction") or "bullish").upper()
    confidence = int(_num(outlook.get("confidence"), 51))
    session = str(outlook.get("session_label") or outlook.get("session") or "current")
    reasons = [str(value) for value in (outlook.get("reasons") or []) if value]
    reason_text = " ".join(reasons[:2])
    flip_text = str(outlook.get("flip_text") or "")
    return (
        f"My session outlook is {direction} at {confidence}/100 confidence for the {session} session. "
        f"{reason_text} {flip_text}"
    ).strip()


def _opinion_text_v55(self: core.LiveTrader, state: dict[str, Any]) -> str:
    outlook = build_session_outlook(self, state)
    state["session_outlook"] = outlook
    market = dict(state.get("market") or {})
    market["session_outlook"] = {
        "version": outlook["version"],
        "direction": outlook["direction"],
        "confidence": outlook["confidence"],
        "score": outlook["score"],
        "session": outlook["session"],
        "reasons": outlook["reasons"],
        "headwinds": outlook["headwinds"],
        "flip_level": outlook["flip_level"],
    }
    state["market"] = market

    bias = dict(state.get("bias") or {})
    trade = dict(state.get("trade") or {})
    trade_bias = str(bias.get("overall") or "neutral").upper()
    outlook_direction = str(outlook.get("direction") or "bullish").upper()
    confidence = int(_num(outlook.get("confidence"), 51))
    session = str(outlook.get("session_label") or "current")
    reasons = [str(value) for value in (outlook.get("reasons") or []) if value]
    reason_text = " ".join(reasons[:2])

    if trade_bias == "NEUTRAL":
        lead = (
            f"Micky, my TRADE BIAS is neutral, but my SESSION OUTLOOK is {outlook_direction} "
            f"at {confidence}/100 for the {session} session."
        )
    elif trade_bias == outlook_direction:
        lead = (
            f"Micky, my TRADE BIAS is {trade_bias} and my SESSION OUTLOOK is also {outlook_direction} "
            f"at {confidence}/100 for the {session} session."
        )
    else:
        lead = (
            f"Micky, my TRADE BIAS is {trade_bias}, but my shorter SESSION OUTLOOK currently leans "
            f"{outlook_direction} at {confidence}/100 for the {session} session. I treat that disagreement cautiously."
        )

    action = str(trade.get("action") or "NO TRADE").upper()
    if action in {"NO TRADE", "WAIT"}:
        execution = "That does not create a trade by itself; the hardened trade gate still says WAIT."
    else:
        execution = f"The hardened trade gate currently has {action}."

    event = dict(((state.get("liquidity") or {}).get("primary_event") or {}))
    event_text = ""
    if str(event.get("event_class") or "none") != "none":
        try:
            event_text = market_events._event_sentence(state)
        except Exception:
            event_text = ""

    return " ".join(part for part in (lead, reason_text, execution, str(outlook.get("flip_text") or ""), event_text) if part).strip()


async def _answer_v55(self: core.LiveTrader, question: str) -> dict[str, Any]:
    text = (question or "").strip()
    lower = text.lower()
    event_terms = (
        "sweep", "swept", "fakeout", "fake out", "fake-out", "failed break",
        "failed breakout", "failed breakdown", "breakout hold", "breakdown hold",
        "liquidity grab", "stop run",
    )
    if any(term in lower for term in event_terms):
        return await _current_answer(self, question)

    outlook_query = (
        "session outlook" in lower
        or "session bias" in lower
        or "up or down" in lower
        or "where is price going" in lower
        or "where do you think price" in lower
        or "direction for this session" in lower
        or "direction today" in lower
        or ("bullish" in lower and "bearish" in lower)
    )
    if not outlook_query:
        return await _current_answer(self, question)

    state = await self.snapshot()
    if not state.get("session_outlook"):
        outlook = build_session_outlook(self, state)
        state["session_outlook"] = outlook
    reply = f"Micky, {_outlook_sentence(state)} Trade bias is {str((state.get('bias') or {}).get('overall') or 'neutral').upper()}, and that remains a separate decision from the session outlook."
    context = {
        "price": state.get("price"),
        "bias": state.get("bias"),
        "session_outlook": state.get("session_outlook"),
        "zones": state.get("zones"),
        "trade": state.get("trade"),
        "market": state.get("market"),
        "liquidity": state.get("liquidity"),
    }
    try:
        await self.repo.client.insert(
            "live_trader_messages",
            [
                {"role": "user", "message": text[:4000], "symbol": self.symbol, "market_context": context},
                {"role": "assistant", "message": reply[:8000], "symbol": self.symbol, "market_context": context},
            ],
            return_rows=False,
        )
    except Exception as exc:
        core.logger.warning("Live Trader could not persist session-outlook chat: %s", exc)
    return {"reply": reply, "state": state}


def _runtime_status_v55(self: core.LiveTrader) -> dict[str, Any]:
    state = dict(_current_runtime_status(self))
    state.update(
        {
            "session_outlook_version": SESSION_OUTLOOK_VERSION,
            "session_outlook_always_directional": True,
            "session_outlook_uses_continuous_structure": True,
            "session_outlook_affects_trade_gate": False,
            "session_outlook_trade_gate_independent": True,
        }
    )
    return state


core.LiveTrader._opinion_text = _opinion_text_v55  # type: ignore[method-assign]
core.LiveTrader.answer = _answer_v55  # type: ignore[method-assign]
core.LiveTrader.runtime_status = _runtime_status_v55  # type: ignore[method-assign]
