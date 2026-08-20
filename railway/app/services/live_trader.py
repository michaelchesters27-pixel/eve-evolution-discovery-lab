from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import math
import re
from collections import deque
from datetime import datetime, timedelta, timezone
from typing import Any

import websockets

from app.settings import Settings
from app.services.repository import DiscoveryRepository

logger = logging.getLogger(__name__)

LIVE_TRADER_VERSION = "eve-live-trader-v1"


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def iso_now() -> str:
    return utc_now().isoformat()


def number(value: Any, default: float = 0.0) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return default
    return result if math.isfinite(result) else default


def clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def direction_label(value: Any) -> str:
    score = number(value)
    return "bullish" if score > 0 else "bearish" if score < 0 else "neutral"


def rounded(value: Any, digits: int = 2) -> float:
    return round(number(value), digits)


class LiveTrader:
    """Real-time manual trading assistant.

    Twelve Data supplies live price only. EVE's audited every-M5 fabric supplies
    causal structure and multi-timeframe context. The assistant can recommend
    market/stop/limit execution, but it has no broker write surface and cannot
    place orders.
    """

    def __init__(self, settings: Settings, repo: DiscoveryRepository) -> None:
        self.settings = settings
        self.repo = repo
        self.symbol = settings.live_trader_symbol
        self._stop = asyncio.Event()
        self._ticks: deque[tuple[datetime, float]] = deque(maxlen=12000)
        self._rows: list[dict[str, Any]] = []
        self._rows_loaded_at: datetime | None = None
        self._last_analysis_at: datetime | None = None
        self._last_persist_at: datetime | None = None
        self._last_resolution_at: datetime | None = None
        self._last_recorded_signature: str | None = None
        self._last_opinion_at: datetime | None = None
        self._latest_state: dict[str, Any] = self._empty_state()
        self.connected = False
        self.last_tick_at: str | None = None
        self.last_error: str | None = None
        self.reconnects = 0
        self.messages_received = 0

    def _empty_state(self) -> dict[str, Any]:
        return {
            "version": LIVE_TRADER_VERSION,
            "symbol": self.symbol,
            "price": None,
            "as_of": None,
            "feed": {
                "status": "starting" if self.settings.live_trader_enabled else "disabled",
                "provider": "Twelve Data WebSocket",
                "connected": False,
                "last_tick_at": None,
                "api_key_configured": bool(self.settings.twelve_data_api_key),
            },
            "bias": {"overall": "neutral", "confidence": 0, "timeframes": {}},
            "market": {"session": "unknown", "regime": "unknown", "atr": None, "magnet": None},
            "zones": {"demand": [], "supply": []},
            "liquidity": {},
            "setup": {"status": "WATCHING", "reason": "Waiting for enough live context."},
            "trade": {"action": "NO TRADE", "order_type": "none", "manual_only": True},
            "opinion": "Micky, I am loading the live market picture.",
            "learning": {"samples": 0, "accuracy": None, "confidence_adjustment": 0},
            "safety": {
                "broker_execution": "disabled",
                "automatic_trading": False,
                "mode": "manual/paper trading assistant",
            },
        }

    async def stop(self) -> None:
        self._stop.set()

    def runtime_status(self) -> dict[str, Any]:
        return {
            "version": LIVE_TRADER_VERSION,
            "enabled": self.settings.live_trader_enabled,
            "symbol": self.symbol,
            "connected": self.connected,
            "last_tick_at": self.last_tick_at,
            "last_error": self.last_error,
            "reconnects": self.reconnects,
            "messages_received": self.messages_received,
            "api_key_configured": bool(self.settings.twelve_data_api_key),
            "execution_mode": "manual_only",
            "automatic_order_placement": False,
        }

    async def _load_rows(self, force: bool = False) -> list[dict[str, Any]]:
        now = utc_now()
        if (
            not force
            and self._rows
            and self._rows_loaded_at is not None
            and now - self._rows_loaded_at < timedelta(seconds=45)
        ):
            return self._rows
        rows = await self.repo.client.get(
            "m5_research_snapshots",
            params={
                "select": "candle_time,open,high,low,close,atr_14,session,regime,direction,return_12_pct,return_48_pct,mtf_context,outcome_complete",
                "symbol": f"eq.{self.symbol}",
                "order": "candle_time.desc",
                "limit": "720",
            },
        )
        rows.reverse()
        self._rows = rows
        self._rows_loaded_at = now
        return rows

    def _latest_price(self, rows: list[dict[str, Any]]) -> float | None:
        if self._ticks:
            return self._ticks[-1][1]
        if rows:
            value = number(rows[-1].get("close"), float("nan"))
            return value if math.isfinite(value) else None
        return None

    def _bias(self, latest: dict[str, Any]) -> tuple[dict[str, Any], float]:
        context = dict(latest.get("mtf_context") or {})
        weights = {"D1": 4.0, "H4": 3.5, "H1": 3.0, "M30": 2.0, "M15": 2.0, "M5": 1.0, "M1": 0.5}
        weighted = 0.0
        total = 0.0
        timeframes: dict[str, Any] = {}
        agreement_values: list[int] = []
        for timeframe, weight in weights.items():
            item = dict(context.get(timeframe) or {})
            direction = int(clamp(number(item.get("direction")), -1, 1))
            timeframes[timeframe] = {
                "direction": direction_label(direction),
                "return_pct": rounded(item.get("return_pct"), 3) if timeframe != "M1" else None,
            }
            if direction:
                weighted += direction * weight
                total += weight
                agreement_values.append(direction)
        score = weighted / total if total else 0.0
        if score >= 0.24:
            overall = "bullish"
        elif score <= -0.24:
            overall = "bearish"
        else:
            overall = "neutral"
        agreement = abs(sum(agreement_values)) / len(agreement_values) if agreement_values else 0.0
        raw_confidence = 48.0 + abs(score) * 36.0 + agreement * 12.0
        return {
            "overall": overall,
            "raw_score": round(score, 3),
            "confidence": int(round(clamp(raw_confidence, 40, 94))),
            "timeframes": timeframes,
            "htf_alignment": int(number(context.get("higher_timeframe_alignment_score"))),
            "all_alignment": int(number(context.get("direction_alignment_score"))),
        }, score

    def _zone_candidates(
        self,
        rows: list[dict[str, Any]],
        price: float,
        bias: dict[str, Any],
    ) -> dict[str, list[dict[str, Any]]]:
        if len(rows) < 20:
            return {"demand": [], "supply": []}
        source = rows[-360:]
        latest_atr = max(number(source[-1].get("atr_14")), 0.01)
        htf = bias.get("timeframes") or {}
        demand: list[dict[str, Any]] = []
        supply: list[dict[str, Any]] = []
        window = 2
        for index in range(window, len(source) - 8):
            row = source[index]
            low = number(row.get("low"))
            high = number(row.get("high"))
            open_ = number(row.get("open"))
            close = number(row.get("close"))
            atr = max(number(row.get("atr_14")), latest_atr * 0.5, 0.01)
            nearby = source[index - window : index + window + 1]
            future = source[index + 1 : index + 9]
            prior = source[max(0, index - 12) : index]
            later = source[index + 9 :]

            is_low = low <= min(number(item.get("low")) for item in nearby)
            is_high = high >= max(number(item.get("high")) for item in nearby)

            if is_low and future:
                future_high = max(number(item.get("high")) for item in future)
                departure = (future_high - low) / atr
                if departure >= 1.15:
                    zone_low = low
                    zone_high = min(max(open_, close), low + atr * 0.55)
                    invalid = any(number(item.get("close")) < zone_low - atr * 0.2 for item in later)
                    if not invalid and zone_high >= zone_low:
                        retests = sum(
                            1
                            for item in later
                            if number(item.get("low")) <= zone_high and number(item.get("high")) >= zone_low
                        )
                        broke_structure = bool(prior) and future_high > max(number(item.get("high")) for item in prior)
                        alignment = sum(
                            1 for tf in ("D1", "H4", "H1") if (htf.get(tf) or {}).get("direction") == "bullish"
                        )
                        quality = clamp(38 + min(departure, 3.5) * 11 + (18 if broke_structure else 0) + alignment * 4 - min(retests, 4) * 7, 1, 99)
                        demand.append(self._zone("demand", row, zone_low, zone_high, quality, retests, departure, price, latest_atr))

            if is_high and future:
                future_low = min(number(item.get("low")) for item in future)
                departure = (high - future_low) / atr
                if departure >= 1.15:
                    zone_high = high
                    zone_low = max(min(open_, close), high - atr * 0.55)
                    invalid = any(number(item.get("close")) > zone_high + atr * 0.2 for item in later)
                    if not invalid and zone_high >= zone_low:
                        retests = sum(
                            1
                            for item in later
                            if number(item.get("low")) <= zone_high and number(item.get("high")) >= zone_low
                        )
                        broke_structure = bool(prior) and future_low < min(number(item.get("low")) for item in prior)
                        alignment = sum(
                            1 for tf in ("D1", "H4", "H1") if (htf.get(tf) or {}).get("direction") == "bearish"
                        )
                        quality = clamp(38 + min(departure, 3.5) * 11 + (18 if broke_structure else 0) + alignment * 4 - min(retests, 4) * 7, 1, 99)
                        supply.append(self._zone("supply", row, zone_low, zone_high, quality, retests, departure, price, latest_atr))

        return {
            "demand": self._dedupe_zones(demand, price, latest_atr, kind="demand"),
            "supply": self._dedupe_zones(supply, price, latest_atr, kind="supply"),
        }

    def _zone(
        self,
        kind: str,
        row: dict[str, Any],
        low: float,
        high: float,
        quality: float,
        retests: int,
        departure: float,
        price: float,
        atr: float,
    ) -> dict[str, Any]:
        inside = low <= price <= high
        distance = 0.0 if inside else min(abs(price - low), abs(price - high))
        distance_atr = distance / max(atr, 0.01)
        status = "IN ZONE" if inside else "NEAR" if distance_atr <= 1.0 else "ACTIVE"
        quality_label = "HIGH" if quality >= 72 else "GOOD" if quality >= 58 else "MEDIUM"
        key = hashlib.sha1(f"{kind}|{row.get('candle_time')}|{low:.4f}|{high:.4f}".encode()).hexdigest()[:12]
        return {
            "id": key,
            "kind": kind,
            "low": round(low, 3),
            "high": round(high, 3),
            "mid": round((low + high) / 2.0, 3),
            "quality": int(round(quality)),
            "quality_label": quality_label,
            "status": status,
            "retests": int(retests),
            "fresh": retests == 0,
            "departure_atr": round(departure, 2),
            "distance_atr": round(distance_atr, 2),
            "origin_time": row.get("candle_time"),
            "origin_session": row.get("session"),
        }

    def _dedupe_zones(
        self,
        zones: list[dict[str, Any]],
        price: float,
        atr: float,
        *,
        kind: str,
    ) -> list[dict[str, Any]]:
        eligible = []
        for zone in zones:
            if kind == "demand" and number(zone.get("high")) > price + atr * 0.5:
                continue
            if kind == "supply" and number(zone.get("low")) < price - atr * 0.5:
                continue
            eligible.append(zone)
        eligible.sort(key=lambda z: (-number(z.get("quality")), number(z.get("distance_atr"))))
        kept: list[dict[str, Any]] = []
        for zone in eligible:
            midpoint = number(zone.get("mid"))
            if any(abs(midpoint - number(other.get("mid"))) <= atr * 0.65 for other in kept):
                continue
            kept.append(zone)
            if len(kept) >= 4:
                break
        kept.sort(key=lambda z: number(z.get("distance_atr")))
        return kept

    def _liquidity(self, rows: list[dict[str, Any]]) -> dict[str, Any]:
        if not rows:
            return {}
        recent = rows[-36:]
        latest_day = str(rows[-1].get("candle_time") or "")[:10]
        dates = sorted({str(row.get("candle_time") or "")[:10] for row in rows if row.get("candle_time")})
        prior_day = dates[-2] if len(dates) >= 2 else None
        prior_rows = [row for row in rows if str(row.get("candle_time") or "")[:10] == prior_day] if prior_day else []
        today_rows = [row for row in rows if str(row.get("candle_time") or "")[:10] == latest_day]
        london = [row for row in today_rows if row.get("session") == "london"]
        new_york = [row for row in today_rows if row.get("session") == "new_york"]

        def hi(items: list[dict[str, Any]]) -> float | None:
            return round(max(number(item.get("high")) for item in items), 3) if items else None

        def lo(items: list[dict[str, Any]]) -> float | None:
            return round(min(number(item.get("low")) for item in items), 3) if items else None

        return {
            "recent_high": hi(recent),
            "recent_low": lo(recent),
            "previous_day_high": hi(prior_rows),
            "previous_day_low": lo(prior_rows),
            "london_high": hi(london),
            "london_low": lo(london),
            "new_york_high": hi(new_york),
            "new_york_low": lo(new_york),
        }

    def _magnet(self, bias: str, price: float, zones: dict[str, list[dict[str, Any]]], liquidity: dict[str, Any]) -> float | None:
        if bias == "bullish":
            overhead = [number(zone.get("low")) for zone in zones.get("supply", []) if number(zone.get("low")) > price]
            levels = [number(liquidity.get(key)) for key in ("recent_high", "previous_day_high", "london_high", "new_york_high") if number(liquidity.get(key)) > price]
            values = overhead + levels
            return round(min(values), 3) if values else None
        if bias == "bearish":
            below = [number(zone.get("high")) for zone in zones.get("demand", []) if 0 < number(zone.get("high")) < price]
            levels = [number(liquidity.get(key)) for key in ("recent_low", "previous_day_low", "london_low", "new_york_low") if 0 < number(liquidity.get(key)) < price]
            values = below + levels
            return round(max(values), 3) if values else None
        return None

    def _trade_idea(
        self,
        price: float,
        atr: float,
        bias: dict[str, Any],
        zones: dict[str, list[dict[str, Any]]],
        liquidity: dict[str, Any],
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        overall = str(bias.get("overall") or "neutral")
        confidence = number(bias.get("confidence"))
        timeframes = bias.get("timeframes") or {}
        m5 = (timeframes.get("M5") or {}).get("direction")
        m15 = (timeframes.get("M15") or {}).get("direction")
        if overall == "neutral" or confidence < 58:
            return (
                {"status": "WATCHING", "reason": "The timeframes are not aligned strongly enough for me to force a trade."},
                {"action": "NO TRADE", "order_type": "none", "reason": "No clean directional edge right now.", "manual_only": True},
            )

        bullish = overall == "bullish"
        side = "BUY" if bullish else "SELL"
        preferred = zones.get("demand" if bullish else "supply", [])
        opposing = zones.get("supply" if bullish else "demand", [])
        nearest = preferred[0] if preferred else None
        opposing_target = None
        if opposing:
            candidate = number(opposing[0].get("low" if bullish else "high"))
            if (bullish and candidate > price) or ((not bullish) and candidate < price):
                opposing_target = candidate

        recent_break = number(liquidity.get("recent_high" if bullish else "recent_low"))
        order_type = "none"
        entry: float | None = None
        stop: float | None = None
        reason = ""
        setup_status = "WATCHING"

        if nearest:
            low = number(nearest.get("low"))
            high = number(nearest.get("high"))
            in_zone = low <= price <= high
            short_term_aligned = m5 == overall and m15 == overall
            if in_zone and short_term_aligned and number(nearest.get("quality")) >= 58:
                order_type = "market"
                entry = price
                stop = low - atr * 0.3 if bullish else high + atr * 0.3
                reason = f"Price is in a {nearest.get('quality_label','good').lower()} {'demand' if bullish else 'supply'} zone and M5/M15 have turned with the higher-timeframe bias."
                setup_status = "TRADE IDEA"
            elif number(nearest.get("distance_atr")) <= 1.8 and number(nearest.get("quality")) >= 58:
                order_type = "buy_limit" if bullish else "sell_limit"
                entry = high if bullish else low
                stop = low - atr * 0.3 if bullish else high + atr * 0.3
                reason = f"I prefer the retracement into the {'demand' if bullish else 'supply'} zone rather than chasing current price."
                setup_status = "ARMED"

        if order_type == "none" and recent_break > 0:
            if bullish and recent_break > price and recent_break - price <= atr * 1.8:
                order_type = "buy_stop"
                entry = recent_break + atr * 0.08
                stop = entry - atr * 1.25
                reason = "I want price to prove the breakout before getting long."
                setup_status = "ARMED"
            elif (not bullish) and recent_break < price and price - recent_break <= atr * 1.8:
                order_type = "sell_stop"
                entry = recent_break - atr * 0.08
                stop = entry + atr * 1.25
                reason = "I want price to prove the breakdown before getting short."
                setup_status = "ARMED"

        if entry is None or stop is None:
            return (
                {"status": "SETUP FORMING", "reason": f"My {overall} bias is clear, but the entry location is not good enough yet."},
                {"action": "WAIT", "order_type": "none", "side": side, "reason": "Bias is present; execution is not.", "manual_only": True},
            )

        risk = abs(entry - stop)
        if risk <= 0:
            return ({"status": "WATCHING", "reason": "Invalid risk geometry."}, {"action": "NO TRADE", "order_type": "none", "manual_only": True})
        fallback_target = entry + risk * 2.2 if bullish else entry - risk * 2.2
        target = opposing_target if opposing_target is not None else fallback_target
        reward = (target - entry) if bullish else (entry - target)
        if reward < risk * 1.35:
            target = fallback_target
            reward = risk * 2.2
        rr = reward / risk
        invalidation = (
            f"Cancel the idea if price trades below {stop:.2f} before entry." if bullish and order_type != "market"
            else f"Cancel the idea if price trades above {stop:.2f} before entry." if (not bullish and order_type != "market")
            else f"The trade thesis is invalid beyond the stop at {stop:.2f}."
        )
        action = "BUY NOW" if order_type == "market" and bullish else "SELL NOW" if order_type == "market" else order_type.replace("_", " ").upper()
        trade_confidence = int(round(clamp(confidence + ((number(nearest.get("quality")) - 60) * 0.12 if nearest else 0), 45, 93)))
        return (
            {"status": setup_status, "reason": reason},
            {
                "action": action,
                "side": side,
                "order_type": order_type,
                "entry": round(entry, 3),
                "stop": round(stop, 3),
                "target": round(target, 3),
                "risk_reward": round(rr, 2),
                "confidence": trade_confidence,
                "reason": reason,
                "invalidation": invalidation,
                "manual_only": True,
                "automatic_order_placement": False,
            },
        )

    def _signature(self, state: dict[str, Any]) -> str:
        trade = state.get("trade") or {}
        zones = state.get("zones") or {}
        nearest_demand = (zones.get("demand") or [{}])[0].get("id") if zones.get("demand") else "none"
        nearest_supply = (zones.get("supply") or [{}])[0].get("id") if zones.get("supply") else "none"
        raw = "|".join(
            [
                str((state.get("bias") or {}).get("overall")),
                str((state.get("market") or {}).get("session")),
                str((state.get("market") or {}).get("regime")),
                str(trade.get("order_type")),
                str(nearest_demand),
                str(nearest_supply),
            ]
        )
        return hashlib.sha1(raw.encode()).hexdigest()[:20]

    async def _calibration(self, signature: str) -> dict[str, Any]:
        try:
            rows = await self.repo.client.get(
                "live_trader_opinions",
                params={
                    "select": "direction_correct",
                    "setup_signature": f"eq.{signature}",
                    "status": "eq.resolved",
                    "order": "observed_at.desc",
                    "limit": "200",
                },
            )
        except Exception:
            return {"samples": 0, "accuracy": None, "confidence_adjustment": 0}
        outcomes = [bool(row.get("direction_correct")) for row in rows if row.get("direction_correct") is not None]
        if not outcomes:
            return {"samples": 0, "accuracy": None, "confidence_adjustment": 0}
        accuracy = sum(1 for value in outcomes if value) / len(outcomes)
        adjustment = clamp((accuracy - 0.5) * 24.0, -10, 10) if len(outcomes) >= 8 else 0.0
        return {"samples": len(outcomes), "accuracy": round(accuracy, 3), "confidence_adjustment": round(adjustment, 1)}

    def _opinion_text(self, state: dict[str, Any]) -> str:
        price = number(state.get("price"))
        bias = state.get("bias") or {}
        market = state.get("market") or {}
        trade = state.get("trade") or {}
        overall = str(bias.get("overall") or "neutral")
        confidence = int(number(bias.get("confidence")))
        magnet = market.get("magnet")
        if overall == "neutral":
            lead = "Micky, I do not have a strong directional opinion here. The market is too mixed, so I would leave it alone for now."
        elif magnet:
            lead = f"Micky, my current view is {overall}. I think price is trying to work toward {number(magnet):.2f}, but I would change that view if structure fails."
        else:
            lead = f"Micky, my current view is {overall} with about {confidence}/100 confidence."
        action = str(trade.get("action") or "NO TRADE")
        if action in {"NO TRADE", "WAIT"}:
            return f"{lead} No trade yet — {trade.get('reason') or (state.get('setup') or {}).get('reason') or 'I want a cleaner entry.'}"
        return (
            f"{lead} My preferred execution is {action}: entry {number(trade.get('entry')):.2f}, "
            f"stop {number(trade.get('stop')):.2f}, target {number(trade.get('target')):.2f}, "
            f"about {number(trade.get('risk_reward')):.1f}R. {trade.get('reason')} {trade.get('invalidation')}"
        )

    async def refresh_state(self, *, force_rows: bool = False) -> dict[str, Any]:
        rows = await self._load_rows(force=force_rows)
        price = self._latest_price(rows)
        if not rows or price is None:
            return self._latest_state
        latest = rows[-1]
        bias, _ = self._bias(latest)
        zones = self._zone_candidates(rows, price, bias)
        liquidity = self._liquidity(rows)
        atr = max(number(latest.get("atr_14")), 0.01)
        magnet = self._magnet(str(bias.get("overall")), price, zones, liquidity)
        setup, trade = self._trade_idea(price, atr, bias, zones, liquidity)
        state: dict[str, Any] = {
            "version": LIVE_TRADER_VERSION,
            "symbol": self.symbol,
            "price": round(price, 3),
            "as_of": self.last_tick_at or latest.get("candle_time") or iso_now(),
            "feed": {
                "status": "live" if self.connected else "waiting_for_api_key" if not self.settings.twelve_data_api_key else "reconnecting",
                "provider": "Twelve Data WebSocket",
                "connected": self.connected,
                "last_tick_at": self.last_tick_at,
                "api_key_configured": bool(self.settings.twelve_data_api_key),
                "messages_received": self.messages_received,
            },
            "bias": bias,
            "market": {
                "session": latest.get("session") or "unknown",
                "regime": latest.get("regime") or "unknown",
                "atr": round(atr, 3),
                "return_12_pct": rounded(latest.get("return_12_pct"), 3),
                "return_48_pct": rounded(latest.get("return_48_pct"), 3),
                "magnet": magnet,
                "fabric_time": latest.get("candle_time"),
            },
            "zones": zones,
            "liquidity": liquidity,
            "setup": setup,
            "trade": trade,
            "safety": {
                "broker_execution": "disabled",
                "automatic_trading": False,
                "mode": "manual/paper trading assistant",
            },
        }
        signature = self._signature(state)
        learning = await self._calibration(signature)
        state["learning"] = learning
        adjustment = number(learning.get("confidence_adjustment"))
        state["bias"]["confidence"] = int(round(clamp(number(state["bias"].get("confidence")) + adjustment, 35, 95)))
        if state["trade"].get("confidence") is not None:
            state["trade"]["confidence"] = int(round(clamp(number(state["trade"].get("confidence")) + adjustment, 35, 95)))
        state["setup_signature"] = signature
        state["opinion"] = self._opinion_text(state)
        self._latest_state = state
        self._last_analysis_at = utc_now()
        await self._maybe_persist_state(state)
        await self._maybe_record_opinion(state)
        await self._maybe_resolve_opinions(price)
        return state

    async def _maybe_persist_state(self, state: dict[str, Any]) -> None:
        now = utc_now()
        if self._last_persist_at and now - self._last_persist_at < timedelta(seconds=10):
            return
        try:
            await self.repo.client.upsert(
                "live_trader_state",
                {"symbol": self.symbol, "state": state, "updated_at": now.isoformat()},
                on_conflict="symbol",
            )
            self._last_persist_at = now
        except Exception as exc:
            logger.warning("Live Trader could not persist state: %s", exc)

    async def _maybe_record_opinion(self, state: dict[str, Any]) -> None:
        signature = str(state.get("setup_signature") or "")
        now = utc_now()
        if signature == self._last_recorded_signature and self._last_opinion_at and now - self._last_opinion_at < timedelta(minutes=10):
            return
        if self._last_opinion_at and now - self._last_opinion_at < timedelta(seconds=45):
            return
        try:
            await self.repo.client.insert(
                "live_trader_opinions",
                {
                    "observed_at": now.isoformat(),
                    "symbol": self.symbol,
                    "price": state.get("price"),
                    "bias": (state.get("bias") or {}).get("overall"),
                    "confidence": (state.get("bias") or {}).get("confidence"),
                    "horizon_minutes": self.settings.live_trader_learning_horizon_minutes,
                    "setup_signature": signature,
                    "market_state": {"market": state.get("market"), "bias": state.get("bias"), "liquidity": state.get("liquidity")},
                    "zones": state.get("zones") or {},
                    "trade_idea": state.get("trade") or {},
                    "opinion_text": state.get("opinion") or "",
                    "status": "open",
                },
                return_rows=False,
            )
            self._last_recorded_signature = signature
            self._last_opinion_at = now
        except Exception as exc:
            logger.warning("Live Trader could not record opinion: %s", exc)

    async def _maybe_resolve_opinions(self, price: float) -> None:
        now = utc_now()
        if self._last_resolution_at and now - self._last_resolution_at < timedelta(seconds=30):
            return
        self._last_resolution_at = now
        cutoff = now - timedelta(minutes=self.settings.live_trader_learning_horizon_minutes)
        try:
            rows = await self.repo.client.get(
                "live_trader_opinions",
                params={
                    "select": "id,observed_at,price,bias,horizon_minutes",
                    "status": "eq.open",
                    "observed_at": f"lte.{cutoff.isoformat()}",
                    "order": "observed_at.asc",
                    "limit": "100",
                },
            )
            for row in rows:
                start_price = number(row.get("price"))
                if start_price <= 0:
                    continue
                move_pct = (price / start_price - 1.0) * 100.0
                bias = str(row.get("bias") or "neutral")
                threshold = 0.025
                correct = move_pct > threshold if bias == "bullish" else move_pct < -threshold if bias == "bearish" else abs(move_pct) <= threshold
                await self.repo.client.patch(
                    "live_trader_opinions",
                    {
                        "status": "resolved",
                        "resolved_at": now.isoformat(),
                        "resolved_price": price,
                        "realised_move_pct": round(move_pct, 5),
                        "direction_correct": correct,
                    },
                    filters={"id": f"eq.{row.get('id')}"},
                )
        except Exception as exc:
            logger.warning("Live Trader could not resolve learning outcomes: %s", exc)

    async def snapshot(self) -> dict[str, Any]:
        now = utc_now()
        if self._last_analysis_at is None or now - self._last_analysis_at > timedelta(seconds=8):
            try:
                await self.refresh_state()
            except Exception as exc:
                self.last_error = str(exc)[:500]
        return {**self._latest_state, "runtime": self.runtime_status()}

    def _zone_sentence(self, kind: str, state: dict[str, Any]) -> str:
        zones = ((state.get("zones") or {}).get(kind) or [])
        if not zones:
            return f"Micky, I do not have a {kind} zone close enough and clean enough to call important right now."
        zone = zones[0]
        return (
            f"Micky, the {kind} I care about most is {number(zone.get('low')):.2f} to {number(zone.get('high')):.2f}. "
            f"I rate it {zone.get('quality_label','medium')} ({int(number(zone.get('quality')))}/100), "
            f"it has {int(number(zone.get('retests')))} retest{'s' if int(number(zone.get('retests'))) != 1 else ''}, "
            f"and price is about {number(zone.get('distance_atr')):.1f} ATR away."
        )

    def _bias_sentence(self, state: dict[str, Any]) -> str:
        bias = state.get("bias") or {}
        tf = bias.get("timeframes") or {}
        return (
            f"Micky, my bias is {bias.get('overall','neutral')} at about {int(number(bias.get('confidence')))}/100 confidence. "
            f"Daily is {(tf.get('D1') or {}).get('direction','neutral')}, H4 {(tf.get('H4') or {}).get('direction','neutral')}, "
            f"H1 {(tf.get('H1') or {}).get('direction','neutral')}, M15 {(tf.get('M15') or {}).get('direction','neutral')} "
            f"and M5 {(tf.get('M5') or {}).get('direction','neutral')}."
        )

    def _trade_sentence(self, state: dict[str, Any]) -> str:
        trade = state.get("trade") or {}
        action = str(trade.get("action") or "NO TRADE")
        if action in {"NO TRADE", "WAIT"}:
            return f"Micky, I would not take a trade yet. {trade.get('reason') or (state.get('setup') or {}).get('reason') or 'I want better conditions.'}"
        return (
            f"Micky, the trade I prefer is {action}. Entry {number(trade.get('entry')):.2f}, stop {number(trade.get('stop')):.2f}, "
            f"target {number(trade.get('target')):.2f}, roughly {number(trade.get('risk_reward')):.1f}R, "
            f"confidence {int(number(trade.get('confidence')))}/100. {trade.get('reason')} {trade.get('invalidation')}"
        )

    def _target_sentence(self, question: str, state: dict[str, Any]) -> str | None:
        values = [number(match) for match in re.findall(r"(?<!\d)(\d{3,5}(?:\.\d+)?)(?!\d)", question)]
        if not values:
            return None
        target = values[-1]
        price = number(state.get("price"))
        if price <= 0 or target <= 0:
            return None
        bias = str((state.get("bias") or {}).get("overall") or "neutral")
        higher = target > price
        aligned = (higher and bias == "bullish") or ((not higher) and bias == "bearish")
        zones = state.get("zones") or {}
        barriers = zones.get("supply" if higher else "demand") or []
        between = [
            zone for zone in barriers
            if min(price, target) <= number(zone.get("mid")) <= max(price, target)
        ]
        if aligned and not between:
            return f"Micky, yes — {target:.2f} is a realistic destination in my current {bias} view. I would not call it guaranteed, but I do not see a major ranked zone blocking it right now."
        if aligned and between:
            zone = between[0]
            return f"Micky, {target:.2f} is possible and it agrees with my {bias} bias, but price first has to deal with the {zone.get('kind')} zone at {number(zone.get('low')):.2f}–{number(zone.get('high')):.2f}. That is the level that could change my mind."
        return f"Micky, I would not make {target:.2f} my main call right now. My current bias is {bias}, so I would need the market structure to change before I backed that destination."

    async def answer(self, question: str) -> dict[str, Any]:
        text = (question or "").strip()
        if not text:
            text = "What are we doing?"
        state = await self.snapshot()
        lower = text.lower()
        target_answer = self._target_sentence(text, state)
        if target_answer:
            reply = target_answer
        elif "supply" in lower:
            reply = self._zone_sentence("supply", state)
        elif "demand" in lower:
            reply = self._zone_sentence("demand", state)
        elif "bias" in lower or "bullish" in lower or "bearish" in lower:
            reply = self._bias_sentence(state)
        elif any(term in lower for term in ("trade", "entry", "buy stop", "sell stop", "buy limit", "sell limit", "what are we doing", "what should")):
            reply = self._trade_sentence(state)
        elif "why" in lower or "think" in lower or "opinion" in lower or "see" in lower:
            reply = f"{state.get('opinion')} {self._bias_sentence(state)}"
        elif "zone" in lower:
            reply = f"{self._zone_sentence('demand', state)} {self._zone_sentence('supply', state)}"
        else:
            reply = str(state.get("opinion") or "Micky, I am watching the market but I do not have a clean trade yet.")
        context = {
            "price": state.get("price"),
            "bias": state.get("bias"),
            "setup": state.get("setup"),
            "trade": state.get("trade"),
            "market": state.get("market"),
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
            logger.warning("Live Trader could not persist chat: %s", exc)
        return {"reply": reply, "state": state}

    async def conversation(self, limit: int = 40) -> list[dict[str, Any]]:
        try:
            rows = await self.repo.client.get(
                "live_trader_messages",
                params={"select": "id,created_at,role,message,symbol", "order": "created_at.desc", "limit": str(max(1, min(limit, 100)))},
            )
            rows.reverse()
            return rows
        except Exception:
            return []

    async def learning_summary(self) -> dict[str, Any]:
        try:
            rows = await self.repo.client.get(
                "live_trader_opinions",
                params={"select": "direction_correct,status", "status": "eq.resolved", "order": "observed_at.desc", "limit": "1000"},
            )
        except Exception:
            return {"resolved": 0, "correct": 0, "accuracy": None, "version": LIVE_TRADER_VERSION}
        outcomes = [bool(row.get("direction_correct")) for row in rows if row.get("direction_correct") is not None]
        correct = sum(1 for value in outcomes if value)
        return {
            "resolved": len(outcomes),
            "correct": correct,
            "accuracy": round(correct / len(outcomes), 3) if outcomes else None,
            "horizon_minutes": self.settings.live_trader_learning_horizon_minutes,
            "version": LIVE_TRADER_VERSION,
            "policy": "Measured live opinions calibrate confidence; research rules are not self-modified from a few recent trades.",
        }

    async def _heartbeat(self, websocket: Any) -> None:
        while not self._stop.is_set() and self.connected:
            await asyncio.sleep(10)
            try:
                await websocket.send(json.dumps({"action": "heartbeat"}))
            except Exception:
                return

    async def _handle_price(self, payload: dict[str, Any]) -> None:
        if str(payload.get("event") or "").lower() != "price":
            return
        if str(payload.get("symbol") or "") != self.symbol:
            return
        price = number(payload.get("price"), float("nan"))
        if not math.isfinite(price) or price <= 0:
            return
        timestamp = number(payload.get("timestamp"))
        stamp = datetime.fromtimestamp(timestamp, tz=timezone.utc) if timestamp > 0 else utc_now()
        self._ticks.append((stamp, price))
        self.last_tick_at = stamp.isoformat()
        self.messages_received += 1
        now = utc_now()
        if self._last_analysis_at is None or now - self._last_analysis_at >= timedelta(seconds=2):
            await self.refresh_state()

    async def run_forever(self) -> None:
        if not self.settings.live_trader_enabled:
            self._latest_state["feed"]["status"] = "disabled"
            return
        if not self.settings.twelve_data_api_key:
            self._latest_state["feed"]["status"] = "waiting_for_api_key"
            while not self._stop.is_set():
                try:
                    await self.refresh_state(force_rows=True)
                except Exception as exc:
                    self.last_error = str(exc)[:500]
                try:
                    await asyncio.wait_for(self._stop.wait(), timeout=60)
                except asyncio.TimeoutError:
                    pass
            return

        backoff = 2
        while not self._stop.is_set():
            url = f"{self.settings.twelve_data_ws_url}?apikey={self.settings.twelve_data_api_key}"
            try:
                async with websockets.connect(url, ping_interval=20, ping_timeout=20, close_timeout=5, max_queue=2048) as websocket:
                    self.connected = True
                    self.last_error = None
                    backoff = 2
                    await websocket.send(json.dumps({"action": "subscribe", "params": {"symbols": self.symbol}}))
                    heartbeat = asyncio.create_task(self._heartbeat(websocket), name="eve-live-trader-heartbeat")
                    try:
                        async for message in websocket:
                            if self._stop.is_set():
                                break
                            try:
                                payload = json.loads(message)
                            except (TypeError, json.JSONDecodeError):
                                continue
                            if isinstance(payload, dict):
                                await self._handle_price(payload)
                    finally:
                        self.connected = False
                        heartbeat.cancel()
                        try:
                            await heartbeat
                        except asyncio.CancelledError:
                            pass
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                self.connected = False
                self.last_error = str(exc)[:500]
                self.reconnects += 1
                logger.warning("Live Trader WebSocket disconnected: %s", exc)
                try:
                    await self.refresh_state(force_rows=True)
                except Exception:
                    pass
                try:
                    await asyncio.wait_for(self._stop.wait(), timeout=backoff)
                    return
                except asyncio.TimeoutError:
                    backoff = min(backoff * 2, 60)
