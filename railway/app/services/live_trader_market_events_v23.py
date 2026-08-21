from __future__ import annotations

import math
from datetime import timedelta
from typing import Any

from app.services import live_trader as core
from app.services import live_trader_learning_v2 as v2
from app.services import live_trader_learning_v22 as v22

MARKET_EVENT_VERSION = "eve-live-market-events-v1"
LEARNING_VERSION = "eve-live-learning-v2.3"
EVENT_POLICY = (
    "Classify liquidity sweeps, sweep-reclaims, failed breakouts and accepted breakouts "
    "from completed M5 structure plus the fresh Twelve Data live-price window; event class "
    "and relation to bias are part of the transferable learning family."
)

_original_liquidity = v2.LiveTrader._liquidity
_original_trade_idea = v2.LiveTrader._trade_idea
_original_opinion_text = v2.LiveTrader._opinion_text
_original_trade_sentence = v2.LiveTrader._trade_sentence
_original_answer = v2.LiveTrader.answer
_original_runtime_status = v2.LiveTrader.runtime_status
_v22_descriptor = v22.setup_family_descriptor


def _num(value: Any, default: float = 0.0) -> float:
    return core.number(value, default)


def _clamp(value: float, low: float, high: float) -> float:
    return core.clamp(value, low, high)


def _direction(value: str) -> str:
    text = str(value or "neutral").lower()
    return text if text in {"bullish", "bearish", "neutral"} else "neutral"


def _event_class(event: dict[str, Any] | None) -> str:
    if not event:
        return "none"
    raw = str(event.get("event_class") or "none")
    if raw in {"buy_side_sweep_reclaim", "sell_side_sweep_reclaim"}:
        return "sweep_reclaim"
    if raw in {"failed_breakout_up", "failed_breakout_down"}:
        return "failed_break"
    if raw in {"accepted_breakout_up", "accepted_breakout_down"}:
        return "accepted_breakout"
    return "none"


def _event_relation(event: dict[str, Any] | None, bias: str) -> str:
    if not event:
        return "none"
    implication = _direction(str(event.get("implication") or "neutral"))
    bias = _direction(bias)
    if implication == "neutral" or bias == "neutral":
        return "neutral"
    return "aligned" if implication == bias else "opposed"


def _dedupe_levels(levels: list[dict[str, Any]], atr: float) -> list[dict[str, Any]]:
    kept: list[dict[str, Any]] = []
    tolerance = max(atr * 0.08, 0.01)
    priority = {
        "previous_day": 0,
        "london": 1,
        "new_york": 2,
        "h1": 3,
        "m15": 4,
        "swing": 5,
    }
    levels.sort(key=lambda item: priority.get(str(item.get("group")), 9))
    for item in levels:
        price = _num(item.get("price"), float("nan"))
        if not math.isfinite(price) or price <= 0:
            continue
        if any(abs(price - _num(other.get("price"))) <= tolerance for other in kept):
            continue
        kept.append(item)
    return kept


def _reference_levels(rows: list[dict[str, Any]], liquidity: dict[str, Any], atr: float) -> list[dict[str, Any]]:
    levels: list[dict[str, Any]] = []
    named = (
        ("previous_day_high", "Previous day high", "high", "previous_day"),
        ("previous_day_low", "Previous day low", "low", "previous_day"),
    )
    for key, label, side, group in named:
        value = _num(liquidity.get(key), float("nan"))
        if math.isfinite(value) and value > 0:
            levels.append({"key": key, "label": label, "side": side, "group": group, "price": value})

    # Session highs/lows are dynamic while the session is trading. Freeze the
    # reference three completed M5 bars behind the current edge so a sweep
    # candle cannot move the very level it is supposed to be sweeping.
    latest_day = str(rows[-1].get("candle_time") or "")[:10] if rows else ""
    frozen_rows = rows[:-3] if len(rows) > 3 else rows
    for session, label, group in (("london", "London", "london"), ("new_york", "New York", "new_york")):
        session_rows = [
            row for row in frozen_rows
            if str(row.get("candle_time") or "")[:10] == latest_day and str(row.get("session") or "") == session
        ]
        if session_rows:
            high = max(_num(row.get("high")) for row in session_rows)
            low = min(_num(row.get("low")) for row in session_rows)
        else:
            high = _num(liquidity.get(f"{session}_high"), float("nan"))
            low = _num(liquidity.get(f"{session}_low"), float("nan"))
        if math.isfinite(high) and high > 0:
            levels.append({"key": f"{session}_high", "label": f"{label} high", "side": "high", "group": group, "price": high})
        if math.isfinite(low) and low > 0:
            levels.append({"key": f"{session}_low", "label": f"{label} low", "side": "low", "group": group, "price": low})

    if rows:
        context = dict(rows[-1].get("mtf_context") or {})
        for tf_key, label, group in (("M15", "M15 completed range", "m15"), ("H1", "H1 completed range", "h1")):
            item = dict(context.get(tf_key) or {})
            high = _num(item.get("high"), float("nan"))
            low = _num(item.get("low"), float("nan"))
            if math.isfinite(high) and high > 0:
                levels.append({"key": f"{tf_key.lower()}_high", "label": f"{label} high", "side": "high", "group": group, "price": high})
            if math.isfinite(low) and low > 0:
                levels.append({"key": f"{tf_key.lower()}_low", "label": f"{label} low", "side": "low", "group": group, "price": low})

    prior = rows[-42:-3] if len(rows) >= 8 else []
    if prior:
        swing_high = max(_num(row.get("high")) for row in prior)
        swing_low = min(_num(row.get("low")) for row in prior)
        levels.extend(
            [
                {"key": "structural_swing_high", "label": "Prior M5 swing high", "side": "high", "group": "swing", "price": swing_high},
                {"key": "structural_swing_low", "label": "Prior M5 swing low", "side": "low", "group": "swing", "price": swing_low},
            ]
        )

    return _dedupe_levels(levels, atr)


def _live_window(self: v2.LiveTrader, rows: list[dict[str, Any]], atr: float) -> dict[str, float]:
    latest = rows[-1] if rows else {}
    latest_high = _num(latest.get("high"), float("-inf"))
    latest_low = _num(latest.get("low"), float("inf"))
    latest_close = _num(latest.get("close"))
    previous_close = _num(rows[-2].get("close")) if len(rows) >= 2 else latest_close

    now = core.utc_now()
    cutoff = now - timedelta(minutes=12)
    recent_ticks = [(stamp, price) for stamp, price in getattr(self, "_ticks", []) if stamp >= cutoff]
    if recent_ticks:
        tick_prices = [price for _, price in recent_ticks]
        live_high = max(tick_prices)
        live_low = min(tick_prices)
        current = tick_prices[-1]
    else:
        live_high = latest_high
        live_low = latest_low
        current = latest_close

    return {
        "high": max(latest_high, live_high),
        "low": min(latest_low, live_low),
        "current": current,
        "latest_close": latest_close,
        "previous_close": previous_close,
        "latest_open": _num(latest.get("open")),
        "atr": max(atr, 0.01),
    }


def _wick_fraction(row: dict[str, Any], side: str) -> float:
    high = _num(row.get("high"))
    low = _num(row.get("low"))
    open_ = _num(row.get("open"))
    close = _num(row.get("close"))
    span = max(high - low, 1e-9)
    if side == "high":
        wick = high - max(open_, close)
    else:
        wick = min(open_, close) - low
    return _clamp(wick / span, 0.0, 1.0)


def classify_market_events(
    self: v2.LiveTrader,
    rows: list[dict[str, Any]],
    liquidity: dict[str, Any],
) -> list[dict[str, Any]]:
    if len(rows) < 5:
        return []

    latest = rows[-1]
    atr = max(_num(latest.get("atr_14")), 0.01)
    window = _live_window(self, rows, atr)
    levels = _reference_levels(rows, liquidity, atr)
    events: list[dict[str, Any]] = []

    high = window["high"]
    low = window["low"]
    current = window["current"]
    latest_close = window["latest_close"]
    previous_close = window["previous_close"]

    sweep_buffer = atr * 0.03
    reclaim_buffer = atr * 0.01
    hold_buffer = atr * 0.10

    for ref in levels:
        level = _num(ref.get("price"))
        side = str(ref.get("side"))
        if side == "high":
            penetration = high - level
            swept = penetration >= sweep_buffer
            reclaimed = current <= level - reclaim_buffer or latest_close <= level - reclaim_buffer
            prior_accepted = previous_close >= level + atr * 0.05
            failed = prior_accepted and current <= level - atr * 0.04
            accepted = (
                latest_close >= level + hold_buffer
                and current >= level + atr * 0.06
                and previous_close >= level + atr * 0.02
            )

            if failed:
                strength = _clamp(88 + min(max(penetration / atr, 0.0), 1.0) * 8, 1, 99)
                events.append(
                    {
                        "event_class": "failed_breakout_up",
                        "label": "FAILED BREAKOUT / FAKE-OUT ABOVE",
                        "side": "buy_side",
                        "implication": "bearish",
                        "level_key": ref["key"],
                        "level_label": ref["label"],
                        "level": round(level, 3),
                        "extreme": round(high, 3),
                        "reclaimed": True,
                        "confirmation": "confirmed",
                        "strength": int(round(strength)),
                        "explanation": f"Price had accepted above {ref['label']} but has moved back below it.",
                    }
                )
            elif swept and reclaimed:
                wick = _wick_fraction(latest, "high")
                strength = _clamp(70 + min(penetration / atr, 0.8) * 20 + wick * 8, 1, 96)
                events.append(
                    {
                        "event_class": "buy_side_sweep_reclaim",
                        "label": "BUY-SIDE SWEEP → RECLAIM",
                        "side": "buy_side",
                        "implication": "bearish",
                        "level_key": ref["key"],
                        "level_label": ref["label"],
                        "level": round(level, 3),
                        "extreme": round(high, 3),
                        "reclaimed": True,
                        "confirmation": "possible_fakeout",
                        "strength": int(round(strength)),
                        "explanation": f"Price traded above {ref['label']} and then reclaimed back underneath.",
                    }
                )
            elif accepted:
                strength = _clamp(72 + min((current - level) / atr, 1.0) * 12, 1, 94)
                events.append(
                    {
                        "event_class": "accepted_breakout_up",
                        "label": "BREAKOUT HOLDING ABOVE",
                        "side": "buy_side",
                        "implication": "bullish",
                        "level_key": ref["key"],
                        "level_label": ref["label"],
                        "level": round(level, 3),
                        "extreme": round(high, 3),
                        "reclaimed": False,
                        "confirmation": "accepted",
                        "strength": int(round(strength)),
                        "explanation": f"Price has closed and remained above {ref['label']}; I am not treating it as a fake-out yet.",
                    }
                )

        elif side == "low":
            penetration = level - low
            swept = penetration >= sweep_buffer
            reclaimed = current >= level + reclaim_buffer or latest_close >= level + reclaim_buffer
            prior_accepted = previous_close <= level - atr * 0.05
            failed = prior_accepted and current >= level + atr * 0.04
            accepted = (
                latest_close <= level - hold_buffer
                and current <= level - atr * 0.06
                and previous_close <= level - atr * 0.02
            )

            if failed:
                strength = _clamp(88 + min(max(penetration / atr, 0.0), 1.0) * 8, 1, 99)
                events.append(
                    {
                        "event_class": "failed_breakout_down",
                        "label": "FAILED BREAKDOWN / FAKE-OUT BELOW",
                        "side": "sell_side",
                        "implication": "bullish",
                        "level_key": ref["key"],
                        "level_label": ref["label"],
                        "level": round(level, 3),
                        "extreme": round(low, 3),
                        "reclaimed": True,
                        "confirmation": "confirmed",
                        "strength": int(round(strength)),
                        "explanation": f"Price had accepted below {ref['label']} but has moved back above it.",
                    }
                )
            elif swept and reclaimed:
                wick = _wick_fraction(latest, "low")
                strength = _clamp(70 + min(penetration / atr, 0.8) * 20 + wick * 8, 1, 96)
                events.append(
                    {
                        "event_class": "sell_side_sweep_reclaim",
                        "label": "SELL-SIDE SWEEP → RECLAIM",
                        "side": "sell_side",
                        "implication": "bullish",
                        "level_key": ref["key"],
                        "level_label": ref["label"],
                        "level": round(level, 3),
                        "extreme": round(low, 3),
                        "reclaimed": True,
                        "confirmation": "possible_fakeout",
                        "strength": int(round(strength)),
                        "explanation": f"Price traded below {ref['label']} and then reclaimed back above.",
                    }
                )
            elif accepted:
                strength = _clamp(72 + min((level - current) / atr, 1.0) * 12, 1, 94)
                events.append(
                    {
                        "event_class": "accepted_breakout_down",
                        "label": "BREAKDOWN HOLDING BELOW",
                        "side": "sell_side",
                        "implication": "bearish",
                        "level_key": ref["key"],
                        "level_label": ref["label"],
                        "level": round(level, 3),
                        "extreme": round(low, 3),
                        "reclaimed": False,
                        "confirmation": "accepted",
                        "strength": int(round(strength)),
                        "explanation": f"Price has closed and remained below {ref['label']}; I am not treating it as a fake-out yet.",
                    }
                )

    ranked = sorted(
        events,
        key=lambda event: (
            0 if str(event.get("event_class", "")).startswith("failed_breakout") else
            1 if "sweep_reclaim" in str(event.get("event_class", "")) else 2,
            -int(event.get("strength") or 0),
        ),
    )
    kept: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for event in ranked:
        key = (_event_class(event), str(event.get("implication")))
        if key in seen:
            continue
        seen.add(key)
        kept.append(event)
        if len(kept) >= 4:
            break
    return kept


def _liquidity_v23(self: v2.LiveTrader, rows: list[dict[str, Any]]) -> dict[str, Any]:
    liquidity = dict(_original_liquidity(self, rows) or {})
    events = classify_market_events(self, rows, liquidity)
    liquidity["market_event_version"] = MARKET_EVENT_VERSION
    liquidity["market_events"] = events
    liquidity["primary_event"] = events[0] if events else {
        "event_class": "none",
        "label": "NO ACTIVE LIQUIDITY EVENT",
        "implication": "neutral",
        "strength": 0,
        "confirmation": "none",
    }
    return liquidity


def _target_for_event(
    bullish: bool,
    entry: float,
    stop: float,
    zones: dict[str, list[dict[str, Any]]],
    liquidity: dict[str, Any],
) -> tuple[float | None, float | None]:
    risk = abs(entry - stop)
    if risk <= 0:
        return None, None

    candidates: list[float] = []
    if bullish:
        candidates.extend(
            _num(zone.get("low"))
            for zone in zones.get("supply", [])
            if _num(zone.get("low")) > entry
        )
        candidates.extend(
            _num(liquidity.get(key))
            for key in ("previous_day_high", "london_high", "new_york_high", "recent_high")
            if _num(liquidity.get(key)) > entry
        )
        candidates = sorted({round(value, 5) for value in candidates if value > entry})
        for candidate in candidates:
            rr = (candidate - entry) / risk
            if rr >= 1.6:
                return candidate, rr
    else:
        candidates.extend(
            _num(zone.get("high"))
            for zone in zones.get("demand", [])
            if 0 < _num(zone.get("high")) < entry
        )
        candidates.extend(
            _num(liquidity.get(key))
            for key in ("previous_day_low", "london_low", "new_york_low", "recent_low")
            if 0 < _num(liquidity.get(key)) < entry
        )
        candidates = sorted({round(value, 5) for value in candidates if 0 < value < entry}, reverse=True)
        for candidate in candidates:
            rr = (entry - candidate) / risk
            if rr >= 1.6:
                return candidate, rr
    return None, None


def _trade_idea_v23(
    self: v2.LiveTrader,
    price: float,
    atr: float,
    bias: dict[str, Any],
    zones: dict[str, list[dict[str, Any]]],
    liquidity: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, Any]]:
    setup, trade = _original_trade_idea(self, price, atr, bias, zones, liquidity)
    setup = dict(setup or {})
    trade = dict(trade or {})
    event = dict(liquidity.get("primary_event") or {})
    event_class = str(event.get("event_class") or "none")
    if event_class == "none":
        return setup, trade

    overall = _direction(str(bias.get("overall") or "neutral"))
    implication = _direction(str(event.get("implication") or "neutral"))
    timeframes = bias.get("timeframes") or {}
    m5 = _direction(str((timeframes.get("M5") or {}).get("direction") or "neutral"))
    m15 = _direction(str((timeframes.get("M15") or {}).get("direction") or "neutral"))
    aligned = overall in {"bullish", "bearish"} and implication == overall
    opposed = overall in {"bullish", "bearish"} and implication not in {"neutral", overall}
    strength = int(event.get("strength") or 0)

    if opposed and event_class in {
        "buy_side_sweep_reclaim",
        "sell_side_sweep_reclaim",
        "failed_breakout_up",
        "failed_breakout_down",
    }:
        bias["confidence"] = int(round(_clamp(_num(bias.get("confidence")) - 5.0, 35, 95)))
        return (
            {
                "status": "WATCHING",
                "reason": f"{event.get('label')} at {event.get('level_label')} contradicts my current {overall} view. I want fresh confirmation before entering.",
            },
            {
                "action": "WAIT",
                "order_type": "none",
                "reason": f"I am not trading through a {str(event.get('label') or 'liquidity event').lower()} that currently points {implication}.",
                "manual_only": True,
                "market_event": event_class,
            },
        )

    if aligned and strength >= 72:
        bias["confidence"] = int(round(_clamp(_num(bias.get("confidence")) + 3.0, 35, 95)))
        if str(trade.get("action") or "") not in {"NO TRADE", "WAIT", ""}:
            trade["confidence"] = int(round(_clamp(_num(trade.get("confidence"), _num(bias.get("confidence"))) + 2.0, 35, 95)))
            trade["reason"] = (
                f"{trade.get('reason') or ''} {event.get('label')} at {event.get('level_label')} supports the same direction."
            ).strip()
            trade["market_event"] = event_class
            setup["reason"] = (
                f"{setup.get('reason') or ''} The liquidity event is aligned with the setup."
            ).strip()
            return setup, trade

        is_reversal_event = event_class in {
            "buy_side_sweep_reclaim",
            "sell_side_sweep_reclaim",
            "failed_breakout_up",
            "failed_breakout_down",
        }
        if not is_reversal_event or m5 != overall or m15 != overall or not self._feed_is_fresh():
            setup["status"] = "SETUP FORMING"
            setup["reason"] = (
                f"{event.get('label')} supports my {overall} view, but I still want M5/M15 execution alignment and a fresh feed before I arm an order."
            )
            trade.update(
                {
                    "action": "WAIT",
                    "order_type": "none",
                    "reason": "The liquidity event supports the bias, but execution is not complete.",
                    "manual_only": True,
                    "market_event": event_class,
                }
            )
            return setup, trade

        bullish = overall == "bullish"
        preferred = zones.get("demand" if bullish else "supply", [])
        near_zone = bool(preferred and _num(preferred[0].get("distance_atr"), 99) <= 2.2)
        correct_side_event = (
            (bullish and str(event.get("side")) == "sell_side")
            or ((not bullish) and str(event.get("side")) == "buy_side")
        )
        if not (near_zone or correct_side_event):
            setup["status"] = "SETUP FORMING"
            setup["reason"] = f"The {event.get('label')} is useful, but it happened in weak location. I am not chasing it."
            trade.update(
                {
                    "action": "WAIT",
                    "order_type": "none",
                    "reason": "Good liquidity information, poor entry location.",
                    "manual_only": True,
                    "market_event": event_class,
                }
            )
            return setup, trade

        latest = self._rows[-1] if getattr(self, "_rows", None) else {}
        candle_high = _num(latest.get("high"), price)
        candle_low = _num(latest.get("low"), price)
        extreme = _num(event.get("extreme"), candle_low if bullish else candle_high)
        if bullish:
            entry = max(price, candle_high) + atr * 0.08
            stop_anchor = min(extreme, _num(preferred[0].get("low"), extreme) if preferred else extreme)
            stop = stop_anchor - atr * 0.18
        else:
            entry = min(price, candle_low) - atr * 0.08
            stop_anchor = max(extreme, _num(preferred[0].get("high"), extreme) if preferred else extreme)
            stop = stop_anchor + atr * 0.18

        target, rr = _target_for_event(bullish, entry, stop, zones, liquidity)
        if target is None or rr is None:
            setup["status"] = "SETUP FORMING"
            setup["reason"] = f"{event.get('label')} is aligned, but the next clean target does not pay enough risk."
            trade.update(
                {
                    "action": "WAIT",
                    "order_type": "none",
                    "reason": "Confirmation is present, but risk/reward is not good enough.",
                    "manual_only": True,
                    "market_event": event_class,
                }
            )
            return setup, trade

        order_type = "buy_stop" if bullish else "sell_stop"
        action = "BUY STOP" if bullish else "SELL STOP"
        invalidation = (
            f"Cancel the idea if price trades below {extreme:.2f} before triggering."
            if bullish
            else f"Cancel the idea if price trades above {extreme:.2f} before triggering."
        )
        confidence = int(round(_clamp(_num(bias.get("confidence")) + 2.0, 45, 93)))
        return (
            {
                "status": "ARMED",
                "reason": f"{event.get('label')} at {event.get('level_label')} is aligned with bias and M5/M15 confirmation. I want price to prove continuation through the trigger.",
            },
            {
                "action": action,
                "order_type": order_type,
                "side": "BUY" if bullish else "SELL",
                "entry": round(entry, 3),
                "stop": round(stop, 3),
                "target": round(target, 3),
                "risk_reward": round(rr, 2),
                "confidence": confidence,
                "reason": f"{event.get('explanation')} I prefer a confirmation stop rather than a blind market entry.",
                "invalidation": invalidation,
                "manual_only": True,
                "market_event": event_class,
            },
        )

    if aligned and event_class in {"accepted_breakout_up", "accepted_breakout_down"}:
        trade["reason"] = (
            f"{trade.get('reason') or ''} {event.get('label')} {event.get('level_label')} is currently holding."
        ).strip()
        trade["market_event"] = event_class
    return setup, trade


def _event_sentence(state: dict[str, Any]) -> str:
    event = dict(((state.get("liquidity") or {}).get("primary_event") or {}))
    event_class = str(event.get("event_class") or "none")
    if event_class == "none":
        return "Micky, I do not have an active sweep, failed break or accepted breakout that is strong enough to call right now."
    level = _num(event.get("level"))
    if event_class == "buy_side_sweep_reclaim":
        return (
            f"Micky, yes — buy-side liquidity was swept above {event.get('level_label')} around {level:.2f}, "
            "and price reclaimed back below it. I treat that as a possible bearish fake-out until price proves acceptance above again."
        )
    if event_class == "sell_side_sweep_reclaim":
        return (
            f"Micky, yes — sell-side liquidity was swept below {event.get('level_label')} around {level:.2f}, "
            "and price reclaimed back above it. I treat that as a possible bullish fake-out until price proves acceptance below again."
        )
    if event_class == "failed_breakout_up":
        return (
            f"Micky, I read that as a confirmed failed breakout above {event.get('level_label')} around {level:.2f}. "
            "Price had accepted above it and then lost it again, so the move above is currently a bearish fake-out."
        )
    if event_class == "failed_breakout_down":
        return (
            f"Micky, I read that as a confirmed failed breakdown below {event.get('level_label')} around {level:.2f}. "
            "Price had accepted below it and then reclaimed it, so the move down is currently a bullish fake-out."
        )
    if event_class == "accepted_breakout_up":
        return (
            f"Micky, the break above {event.get('level_label')} around {level:.2f} is holding for now. "
            "I am treating it as accepted price, not a fake-out, unless price loses that level again."
        )
    if event_class == "accepted_breakout_down":
        return (
            f"Micky, the break below {event.get('level_label')} around {level:.2f} is holding for now. "
            "I am treating it as accepted price, not a fake-out, unless price reclaims that level again."
        )
    return f"Micky, the active market event is {event.get('label')} at {event.get('level_label')}."


def _opinion_text_v23(self: v2.LiveTrader, state: dict[str, Any]) -> str:
    base = _original_opinion_text(self, state)
    event = dict(((state.get("liquidity") or {}).get("primary_event") or {}))
    if str(event.get("event_class") or "none") == "none":
        return base
    return f"{base} {_event_sentence(state)}"


def _trade_sentence_v23(self: v2.LiveTrader, state: dict[str, Any]) -> str:
    base = _original_trade_sentence(self, state)
    event = dict(((state.get("liquidity") or {}).get("primary_event") or {}))
    if str(event.get("event_class") or "none") == "none":
        return base
    return f"{base} {_event_sentence(state)}"


def setup_family_descriptor(state: dict[str, Any]) -> dict[str, str]:
    base = dict(_v22_descriptor(state))
    event = dict(((state.get("liquidity") or {}).get("primary_event") or {}))
    base["market_event_class"] = _event_class(event)
    base["market_event_relation"] = _event_relation(event, str(base.get("bias") or "neutral"))
    base["market_event_confirmation"] = str(event.get("confirmation") or "none")
    return base


def _runtime_status_v23(self: v2.LiveTrader) -> dict[str, Any]:
    state = dict(_original_runtime_status(self))
    state.update(
        {
            "learning_version": LEARNING_VERSION,
            "market_event_version": MARKET_EVENT_VERSION,
            "market_event_policy": EVENT_POLICY,
            "understands_liquidity_sweeps": True,
            "understands_failed_breakouts": True,
            "understands_accepted_breakouts": True,
        }
    )
    return state


async def _answer_v23(self: v2.LiveTrader, question: str) -> dict[str, Any]:
    text = (question or "").strip()
    lower = text.lower()
    event_terms = (
        "sweep",
        "swept",
        "fakeout",
        "fake out",
        "fake-out",
        "failed break",
        "failed breakout",
        "failed breakdown",
        "breakout hold",
        "breakdown hold",
        "liquidity grab",
        "stop run",
    )
    if not any(term in lower for term in event_terms):
        return await _original_answer(self, question)

    state = await self.snapshot()
    reply = _event_sentence(state)
    context = {
        "price": state.get("price"),
        "bias": state.get("bias"),
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
        core.logger.warning("Live Trader could not persist market-event chat: %s", exc)
    return {"reply": reply, "state": state}


v22.LEARNING_VERSION = LEARNING_VERSION
v22.EVENT_POLICY = EVENT_POLICY
v22._FAMILY_KEYS = tuple(v22._FAMILY_KEYS) + ("market_event_class", "market_event_relation")
v22.setup_family_descriptor = setup_family_descriptor
v2.LEARNING_VERSION = LEARNING_VERSION
v2.setup_family_descriptor = setup_family_descriptor
v2.LiveTrader._liquidity = _liquidity_v23  # type: ignore[method-assign]
v2.LiveTrader._trade_idea = _trade_idea_v23  # type: ignore[method-assign]
v2.LiveTrader._opinion_text = _opinion_text_v23  # type: ignore[method-assign]
v2.LiveTrader._trade_sentence = _trade_sentence_v23  # type: ignore[method-assign]
v2.LiveTrader.answer = _answer_v23  # type: ignore[method-assign]
v2.LiveTrader.runtime_status = _runtime_status_v23  # type: ignore[method-assign]
