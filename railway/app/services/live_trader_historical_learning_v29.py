from __future__ import annotations

import asyncio
import hashlib
from datetime import datetime, timedelta, timezone
from typing import Any
from zoneinfo import ZoneInfo

from app.services import live_trader as core
from app.services import live_trader_audit_hardening_v26 as hardening
from app.services import live_trader_learning_v2 as v2
from app.services import live_trader_learning_v22 as v22
from app.services import live_trader_trade_lock_v28 as lock
from app.services.repository import DiscoveryRepository, SourceRepository
from app.settings import Settings

ACADEMY_VERSION = "eve-live-historical-academy-v1"
MARKET_HOURS_VERSION = "ic-markets-weekend-guard-v1"
EVIDENCE_POLICY = (
    "Historical evidence is causal replay education, not forward-live experience. "
    "Historical samples carry 0.25 base weight, are deduplicated to one family sample per "
    "trading day/session, and are capped at 12 effective samples in live calibration. "
    "Historical evidence may seed confidence by at most +/-3 points; only mature forward-live "
    "evidence can activate the hard learning veto and the full +/-6 point calibration."
)
REPLAY_POLICY = (
    "Replay decisions use only completed every-M5 fabric rows available at the historical decision time. "
    "The future is revealed only after the decision, from the read-only source M1 path. "
    "The same causal M1 path scores EVE's original decision and execution challengers."
)
BROKER_HOURS_POLICY = (
    "IC Markets standard weekend boundary: 17:00 Sunday to 17:00 Friday America/New_York. "
    "Live observations and campaign price events are frozen outside that window."
)

HISTORICAL_BASE_WEIGHT = 0.25
HISTORICAL_EFFECTIVE_CAP = 12.0
HISTORICAL_MIN_EPISODES = 24
HISTORICAL_MIN_DAYS = 12
HISTORICAL_MIN_EFFECTIVE = 6.0
HISTORICAL_CONFIDENCE_CAP = 3.0
WARMUP_ROWS = 360
BATCH_ROWS = 180
CYCLE_SECONDS = 12.0
MAX_ENDPOINT_LAG_SECONDS = 75.0
NY = ZoneInfo("America/New_York")

_current_trade_idea = core.LiveTrader._trade_idea
_current_record = core.LiveTrader._maybe_record_opinion
_current_resolve = core.LiveTrader._maybe_resolve_opinions
_current_calibration = core.LiveTrader._calibration
_current_refresh = core.LiveTrader.refresh_state
_current_runtime_status = core.LiveTrader.runtime_status
_current_learning_summary = core.LiveTrader.learning_summary


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


def broker_market_open(at: datetime) -> bool:
    """Conservative weekend gate based on IC Markets' standard 17:00 ET boundary."""
    local = at.astimezone(NY)
    weekday = local.weekday()  # Monday=0 ... Sunday=6
    clock = (local.hour, local.minute, local.second)
    if weekday == 4 and clock >= (17, 0, 0):
        return False
    if weekday == 5:
        return False
    if weekday == 6 and clock < (17, 0, 0):
        return False
    return True


def broker_market_open_through(observed: datetime, horizon_minutes: int) -> bool:
    horizon = observed + timedelta(minutes=max(1, int(horizon_minutes)))
    if not broker_market_open(observed) or not broker_market_open(horizon):
        return False
    start_local = observed.astimezone(NY)
    end_local = horizon.astimezone(NY)
    if start_local.weekday() == 4 and end_local.date() != start_local.date():
        return False
    if start_local.weekday() == 4 and (end_local.hour, end_local.minute) >= (17, 0):
        return False
    return True


def _market_hours_payload(at: datetime) -> dict[str, Any]:
    local = at.astimezone(NY)
    return {
        "version": MARKET_HOURS_VERSION,
        "tradable": broker_market_open(at),
        "broker_reference": "IC Markets",
        "timezone": "America/New_York",
        "local_time": local.isoformat(),
        "weekly_open": "Sunday 17:00 ET",
        "weekly_close": "Friday 17:00 ET",
        "policy": BROKER_HOURS_POLICY,
    }


def _trade_idea_v29(
    self: core.LiveTrader,
    price: float,
    atr: float,
    bias: dict[str, Any],
    zones: dict[str, list[dict[str, Any]]],
    liquidity: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, Any]]:
    if broker_market_open(core.utc_now()):
        return _current_trade_idea(self, price, atr, bias, zones, liquidity)

    campaign = getattr(self, "_live_campaign", None)
    if isinstance(campaign, dict):
        trade = lock._campaign_trade(campaign)
        trade["campaign_frozen"] = True
        return (
            {
                "status": "MARKET CLOSED — CAMPAIGN FROZEN",
                "reason": (
                    "The broker market is closed. EVE is preserving the exact locked entry, stop and target "
                    "without allowing weekend quotes to trigger, win, lose, invalidate or expire the campaign."
                ),
            },
            trade,
        )
    return (
        {
            "status": "MARKET CLOSED",
            "reason": "Live trading is paused until the broker market reopens; Historical Academy continues learning.",
        },
        {
            "action": "WAIT",
            "order_type": "none",
            "reason": "No new live trade can be published while the broker market is closed.",
            "manual_only": True,
            "automatic_order_placement": False,
            "market_closed": True,
        },
    )


async def _record_v29(self: core.LiveTrader, state: dict[str, Any]) -> None:
    observed = hardening._market_observation_time(state)
    if observed is None:
        return
    horizon = int(self.settings.live_trader_learning_horizon_minutes)
    if not broker_market_open_through(observed, horizon):
        return
    await _current_record(self, state)


async def _resolve_v29(self: core.LiveTrader, price: float) -> None:
    if not broker_market_open(core.utc_now()):
        return
    await _current_resolve(self, price)


def _historical_context_weight(current: dict[str, Any], row: dict[str, Any]) -> float:
    market_state = dict(row.get("market_state") or {})
    historical = dict(market_state.get("setup_family_descriptor") or {})
    context_weight = v22._context_weight(current, historical)
    return context_weight * max(0.0, core.number(row.get("evidence_weight"), HISTORICAL_BASE_WEIGHT))


async def _calibration_v29(self: core.LiveTrader, signature: str) -> dict[str, Any]:
    learning = dict(await _current_calibration(self, signature))
    try:
        rows = await self.repo.client.get(
            "live_trader_historical_learning",
            params={
                "select": "learning_success,independence_key,observed_at,market_state,evidence_weight,path_complete",
                "setup_family": f"eq.{signature}",
                "path_complete": "eq.true",
                "order": "observed_at.desc",
                "limit": "1500",
            },
        )
    except Exception:
        rows = []

    independent: dict[str, dict[str, Any]] = {}
    for row in rows:
        key = str(row.get("independence_key") or "")
        if not key or key in independent or row.get("learning_success") is None:
            continue
        independent[key] = row
    historical = list(independent.values())
    current = getattr(self, "_learning_descriptor_v22", {}) or {}

    hist_effective_raw = 0.0
    hist_wins_raw = 0.0
    hist_days: set[str] = set()
    hist_correct = 0
    for row in historical:
        weight = _historical_context_weight(current, row)
        hist_effective_raw += weight
        if bool(row.get("learning_success")):
            hist_wins_raw += weight
            hist_correct += 1
        if row.get("observed_at"):
            hist_days.add(str(row.get("observed_at"))[:10])

    scale = 1.0
    if hist_effective_raw > HISTORICAL_EFFECTIVE_CAP > 0:
        scale = HISTORICAL_EFFECTIVE_CAP / hist_effective_raw
    hist_effective = hist_effective_raw * scale
    hist_wins = hist_wins_raw * scale
    hist_accuracy = hist_correct / len(historical) if historical else None
    historical_mature = (
        len(historical) >= HISTORICAL_MIN_EPISODES
        and len(hist_days) >= HISTORICAL_MIN_DAYS
        and hist_effective >= HISTORICAL_MIN_EFFECTIVE
    )

    live_effective = core.number(learning.get("effective_samples"), core.number(learning.get("samples")))
    live_accuracy = learning.get("accuracy")
    live_wins = live_effective * core.number(live_accuracy) if live_accuracy is not None else 0.0
    denominator = live_effective + hist_effective + v2.PRIOR_WINS + v2.PRIOR_LOSSES
    blended = (
        (live_wins + hist_wins + v2.PRIOR_WINS) / denominator
        if denominator > 0
        else 0.5
    )

    if bool(learning.get("active")):
        adjustment = core.clamp((blended - 0.5) * 20.0, -6.0, 6.0)
        source = "live_mature_plus_history"
    elif historical_mature:
        adjustment = core.clamp(
            (blended - 0.5) * 12.0,
            -HISTORICAL_CONFIDENCE_CAP,
            HISTORICAL_CONFIDENCE_CAP,
        )
        source = "historical_seed"
    else:
        adjustment = 0.0
        source = "insufficient_evidence"

    learning.update(
        {
            "confidence_adjustment": round(adjustment, 1),
            "confidence_adjustment_source": source,
            "historical_samples": len(historical),
            "historical_days": len(hist_days),
            "historical_accuracy": round(hist_accuracy, 3) if hist_accuracy is not None else None,
            "historical_effective_samples": round(hist_effective, 2),
            "historical_effective_samples_raw": round(hist_effective_raw, 2),
            "historical_seed_active": historical_mature,
            "historical_evidence_cap": HISTORICAL_EFFECTIVE_CAP,
            "historical_confidence_cap_points": HISTORICAL_CONFIDENCE_CAP,
            "blended_posterior_accuracy": round(blended, 3),
            "historical_academy_version": ACADEMY_VERSION,
            "evidence_policy": EVIDENCE_POLICY,
        }
    )
    return learning


async def _refresh_v29(self: core.LiveTrader, *, force_rows: bool = False) -> dict[str, Any]:
    state = await _current_refresh(self, force_rows=force_rows)
    now = core.utc_now()
    hours = _market_hours_payload(now)
    state["market_hours"] = hours
    feed = dict(state.get("feed") or {})
    feed["tradable"] = bool(hours["tradable"])
    feed["provider_connected"] = bool(feed.get("socket_connected") or feed.get("connected"))
    if not hours["tradable"]:
        feed["status"] = "market_closed"
        feed["connected"] = False
        campaign = state.get("trade_campaign")
        if isinstance(campaign, dict):
            state["setup"] = {
                "status": "MARKET CLOSED — CAMPAIGN FROZEN",
                "reason": (
                    "The broker market is closed. EVE is holding the locked campaign unchanged and ignoring weekend "
                    "indicative quotes for trigger/TP/SL/invalidation decisions."
                ),
            }
            trade = dict(state.get("trade") or {})
            trade["campaign_frozen"] = True
            state["trade"] = trade
            state["opinion"] = (
                "Micky, the broker market is closed. The locked campaign is frozen exactly as published. "
                "I am not using weekend quotes to manage it. My Historical Academy is still learning from the six-year archive."
            )
        else:
            state["setup"] = {
                "status": "MARKET CLOSED",
                "reason": "Live trading is paused; Historical Academy continues causal replay.",
            }
            state["trade"] = {
                "action": "WAIT",
                "order_type": "none",
                "manual_only": True,
                "market_closed": True,
                "reason": "No new live trade while the broker market is closed.",
            }
            state["opinion"] = (
                "Micky, the broker market is closed, so live trading and forward learning are paused. "
                "Historical Academy is still working through the six-year archive."
            )
    state["feed"] = feed
    self._latest_state = state
    return state


async def _learning_summary_v29(self: core.LiveTrader) -> dict[str, Any]:
    summary = dict(await _current_learning_summary(self))
    try:
        states = await self.repo.client.get(
            "live_trader_historical_state",
            params={"select": "*", "symbol": f"eq.{self.symbol}", "limit": "1"},
        )
        historical_state = dict(states[0]) if states else {}
        latest_rows = await self.repo.client.get(
            "live_trader_historical_learning",
            params={
                "select": "observed_at,setup_family,best_challenger,learning_success",
                "symbol": f"eq.{self.symbol}",
                "order": "observed_at.desc",
                "limit": "1",
            },
        )
        latest = dict(latest_rows[0]) if latest_rows else {}
    except Exception:
        historical_state = {}
        latest = {}
    summary["historical_learning"] = {
        "version": ACADEMY_VERSION,
        "rows_scanned": int(core.number(historical_state.get("historical_rows_scanned"))),
        "episodes_recorded": int(core.number(historical_state.get("episodes_recorded"))),
        "scored_episodes": int(core.number(historical_state.get("scored_episodes"))),
        "challenger_runs": int(core.number(historical_state.get("challenger_runs"))),
        "cursor_time": historical_state.get("cursor_time"),
        "last_cycle_at": historical_state.get("last_cycle_at"),
        "last_error": historical_state.get("last_error"),
        "latest_historical_observation": latest.get("observed_at"),
        "latest_family": latest.get("setup_family"),
        "latest_best_challenger": latest.get("best_challenger"),
        "policy": REPLAY_POLICY,
        "evidence_policy": EVIDENCE_POLICY,
    }
    summary["market_hours"] = _market_hours_payload(core.utc_now())
    return summary


def _runtime_status_v29(self: core.LiveTrader) -> dict[str, Any]:
    status = dict(_current_runtime_status(self))
    status.update(
        {
            "historical_academy_version": ACADEMY_VERSION,
            "historical_academy_enabled": True,
            "historical_evidence_weight": HISTORICAL_BASE_WEIGHT,
            "historical_evidence_effective_cap": HISTORICAL_EFFECTIVE_CAP,
            "market_hours_version": MARKET_HOURS_VERSION,
            "broker_market_open": broker_market_open(core.utc_now()),
            "broker_hours_policy": BROKER_HOURS_POLICY,
        }
    )
    return status


class LiveTraderHistoricalLearner:
    """Always-on causal replay academy for the six-year every-M5 fabric."""

    SNAPSHOT_SELECT = (
        "candle_time,open,high,low,close,atr_14,session,regime,direction,"
        "return_12_pct,return_48_pct,trend_12_atr,trend_48_atr,mtf_context,outcome_complete"
    )

    def __init__(self, settings: Settings, source: SourceRepository, repo: DiscoveryRepository) -> None:
        self.settings = settings
        self.source = source
        self.repo = repo
        self.symbol = settings.live_trader_symbol
        self._stop = asyncio.Event()
        self._engine = core.LiveTrader(settings, repo)
        self._engine._feed_is_fresh = lambda *_args, **_kwargs: True  # type: ignore[method-assign]
        self.last_cycle_at: str | None = None
        self.last_error: str | None = None
        self.last_batch_rows = 0
        self.last_batch_episodes = 0
        self.runtime_episodes = 0
        self.runtime_challengers = 0
        self.caught_up = False

    async def stop(self) -> None:
        self._stop.set()

    def runtime_status(self) -> dict[str, Any]:
        return {
            "version": ACADEMY_VERSION,
            "enabled": True,
            "running": not self._stop.is_set(),
            "caught_up": self.caught_up,
            "last_cycle_at": self.last_cycle_at,
            "last_error": self.last_error,
            "last_batch_rows": self.last_batch_rows,
            "last_batch_episodes": self.last_batch_episodes,
            "runtime_episodes": self.runtime_episodes,
            "runtime_challengers": self.runtime_challengers,
            "replay_policy": REPLAY_POLICY,
            "evidence_policy": EVIDENCE_POLICY,
        }

    async def _state(self) -> dict[str, Any]:
        rows = await self.repo.client.get(
            "live_trader_historical_state",
            params={"select": "*", "symbol": f"eq.{self.symbol}", "limit": "1"},
        )
        return dict(rows[0]) if rows else {}

    async def _persist_state(
        self,
        previous: dict[str, Any],
        *,
        cursor_time: str | None,
        rows_scanned_add: int,
        episodes_add: int,
        scored_add: int,
        challenger_add: int,
        error: str | None = None,
    ) -> None:
        now = core.utc_now().isoformat()
        payload = {
            "symbol": self.symbol,
            "cursor_time": cursor_time,
            "historical_rows_scanned": int(core.number(previous.get("historical_rows_scanned"))) + rows_scanned_add,
            "episodes_recorded": int(core.number(previous.get("episodes_recorded"))) + episodes_add,
            "scored_episodes": int(core.number(previous.get("scored_episodes"))) + scored_add,
            "challenger_runs": int(core.number(previous.get("challenger_runs"))) + challenger_add,
            "last_cycle_at": now,
            "last_error": error,
            "engine_version": ACADEMY_VERSION,
            "updated_at": now,
        }
        await self.repo.client.upsert(
            "live_trader_historical_state",
            payload,
            on_conflict="symbol",
            return_rows=False,
        )

    async def _fetch_window(self, cursor: str | None) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        common = {
            "select": self.SNAPSHOT_SELECT,
            "symbol": f"eq.{self.symbol}",
            "outcome_complete": "eq.true",
        }
        if cursor:
            warm = await self.repo.client.get(
                "m5_research_snapshots",
                params={
                    **common,
                    "candle_time": f"lte.{cursor}",
                    "order": "candle_time.desc",
                    "limit": str(WARMUP_ROWS),
                },
            )
            warm.reverse()
            batch = await self.repo.client.get(
                "m5_research_snapshots",
                params={
                    **common,
                    "candle_time": f"gt.{cursor}",
                    "order": "candle_time.asc",
                    "limit": str(BATCH_ROWS),
                },
            )
            return warm, batch

        initial = await self.repo.client.get(
            "m5_research_snapshots",
            params={
                **common,
                "order": "candle_time.asc",
                "limit": str(WARMUP_ROWS + BATCH_ROWS),
            },
        )
        if len(initial) <= WARMUP_ROWS:
            return initial, []
        return initial[:WARMUP_ROWS], initial[WARMUP_ROWS:]

    @staticmethod
    def _decision_time(row: dict[str, Any]) -> datetime | None:
        context = dict(row.get("mtf_context") or {})
        decision = _parse_time(context.get("decision_time"))
        if decision is not None:
            return decision
        candle = _parse_time(row.get("candle_time"))
        return candle + timedelta(minutes=5) if candle is not None else None

    @staticmethod
    def _hourly_anchor(decision: datetime) -> bool:
        return decision.minute == 0 and decision.second == 0

    def _build_state(self, history: list[dict[str, Any]], row: dict[str, Any], decision: datetime) -> dict[str, Any]:
        price = core.number(row.get("close"))
        bias, _ = self._engine._bias(row)
        zones = self._engine._zone_candidates(history, price, bias)
        self._engine._rows = list(history[-720:])
        liquidity = self._engine._liquidity(history)
        atr = max(core.number(row.get("atr_14")), 0.01)
        magnet = self._engine._magnet(str(bias.get("overall") or "neutral"), price, zones, liquidity)
        setup, trade = lock._original_trade_idea(self._engine, price, atr, bias, zones, liquidity)
        state: dict[str, Any] = {
            "symbol": self.symbol,
            "price": round(price, 3),
            "as_of": decision.isoformat(),
            "feed": {"connected": True, "historical_replay": True},
            "bias": bias,
            "market": {
                "session": row.get("session") or "unknown",
                "regime": row.get("regime") or "unknown",
                "atr": round(atr, 3),
                "return_12_pct": core.rounded(row.get("return_12_pct"), 3),
                "return_48_pct": core.rounded(row.get("return_48_pct"), 3),
                "magnet": magnet,
                "fabric_time": row.get("candle_time"),
            },
            "zones": zones,
            "liquidity": liquidity,
            "setup": setup,
            "trade": trade,
        }
        state["setup_family_descriptor"] = v22.setup_family_descriptor(state)
        state["setup_family"] = v22.family_signature(state)
        return state

    async def _m1_path(self, observed: datetime, horizon: datetime) -> dict[str, Any]:
        rows: list[dict[str, Any]] = []
        cursor: str | None = None
        while len(rows) < 1000:
            page = await self.source.fetch_candles_page(
                self.symbol,
                "1min",
                after=cursor,
                date_from=observed.isoformat() if cursor is None else None,
                date_to=horizon.isoformat(),
                limit=1000,
            )
            if not page:
                break
            rows.extend(page)
            cursor = str(page[-1].get("candle_time"))
            if len(page) < 1000:
                break
        return hardening._causal_m1_path(rows, observed, horizon)

    @staticmethod
    def _trade(side: str, order_type: str, entry: float, stop: float, target: float) -> dict[str, Any]:
        risk = abs(entry - stop)
        rr = abs(target - entry) / risk if risk > 0 else 0.0
        action = (
            "BUY NOW" if side == "BUY" and order_type == "market"
            else "SELL NOW" if side == "SELL" and order_type == "market"
            else order_type.replace("_", " ").upper()
        )
        return {
            "action": action,
            "side": side,
            "order_type": order_type,
            "entry": round(entry, 3),
            "stop": round(stop, 3),
            "target": round(target, 3),
            "risk_reward": round(rr, 2),
        }

    def _challengers(self, state: dict[str, Any]) -> dict[str, dict[str, Any]]:
        bias = str((state.get("bias") or {}).get("overall") or "neutral")
        if bias not in {"bullish", "bearish"}:
            return {}
        bullish = bias == "bullish"
        side = "BUY" if bullish else "SELL"
        price = core.number(state.get("price"))
        market = dict(state.get("market") or {})
        atr = max(core.number(market.get("atr")), 0.01)
        liquidity = dict(state.get("liquidity") or {})
        zones = dict(state.get("zones") or {})
        result: dict[str, dict[str, Any]] = {}

        market_stop = price - atr * 1.25 if bullish else price + atr * 1.25
        market_target = price + atr * 2.75 if bullish else price - atr * 2.75
        result["market"] = self._trade(side, "market", price, market_stop, market_target)

        recent_break = core.number(liquidity.get("recent_high" if bullish else "recent_low"))
        if recent_break > 0:
            entry = recent_break + atr * 0.08 if bullish else recent_break - atr * 0.08
            stop = entry - atr * 1.25 if bullish else entry + atr * 1.25
            target = entry + atr * 2.75 if bullish else entry - atr * 2.75
            result["confirmation_stop"] = self._trade(
                side,
                "buy_stop" if bullish else "sell_stop",
                entry,
                stop,
                target,
            )

        preferred = zones.get("demand" if bullish else "supply") or []
        if preferred:
            zone = dict(preferred[0] or {})
            if core.number(zone.get("quality")) >= 58:
                entry = core.number(zone.get("high" if bullish else "low"))
                if entry > 0:
                    stop = (
                        core.number(zone.get("low")) - atr * 0.30
                        if bullish
                        else core.number(zone.get("high")) + atr * 0.30
                    )
                    risk = abs(entry - stop)
                    target = entry + risk * 2.2 if bullish else entry - risk * 2.2
                    result["pullback_limit"] = self._trade(
                        side,
                        "buy_limit" if bullish else "sell_limit",
                        entry,
                        stop,
                        target,
                    )
        return result

    @staticmethod
    def _score_challengers(
        challengers: dict[str, dict[str, Any]],
        bars: list[dict[str, Any]],
        endpoint: float,
    ) -> tuple[dict[str, Any], str | None]:
        scored: dict[str, Any] = {}
        best_name: str | None = None
        best_r = float("-inf")
        for name, trade in challengers.items():
            outcome = v2._trade_path_result(trade, bars, endpoint)
            scored[name] = {"trade": trade, **outcome}
            realised = outcome.get("realised_r")
            if realised is not None and bool(outcome.get("entry_triggered")) and core.number(realised, -999.0) > best_r:
                best_r = core.number(realised)
                best_name = name
        if best_name is None:
            best_name = "no_trade"
        return scored, best_name

    async def _evaluate(
        self,
        history: list[dict[str, Any]],
        row: dict[str, Any],
        decision: datetime,
    ) -> tuple[bool, bool, int]:
        horizon_minutes = int(self.settings.live_trader_learning_horizon_minutes)
        horizon = decision + timedelta(minutes=horizon_minutes)
        state = self._build_state(history, row, decision)
        family = str(state.get("setup_family") or "")
        if not family:
            return False, False, 0

        session = str((state.get("market") or {}).get("session") or "unknown")
        independence_raw = "|".join([self.symbol, decision.date().isoformat(), session, family])
        independence_key = hashlib.sha1(independence_raw.encode()).hexdigest()[:28]
        episode_raw = "|".join([self.symbol, decision.isoformat(), family, ACADEMY_VERSION])
        episode_key = hashlib.sha1(episode_raw.encode()).hexdigest()[:32]

        path = await self._m1_path(decision, horizon)
        endpoint = path.get("endpoint_price")
        endpoint_time = path.get("endpoint_time")
        endpoint_lag = path.get("endpoint_lag_seconds")
        path_complete = (
            endpoint is not None
            and endpoint_time is not None
            and endpoint_lag is not None
            and float(endpoint_lag) <= MAX_ENDPOINT_LAG_SECONDS
            and path.get("initial_gap_seconds") is not None
            and float(path.get("initial_gap_seconds") or 0.0) <= 1.0
            and int(path.get("gap_count") or 0) == 0
        )

        direction_correct = None
        trade_outcome = None
        realised_r = None
        learning_success = None
        challengers_scored: dict[str, Any] = {}
        best_challenger = None
        challenger_runs = 0
        if path_complete:
            endpoint_value = float(endpoint)
            row_for_direction = {
                "price": state.get("price"),
                "bias": (state.get("bias") or {}).get("overall"),
                "market_state": {"market": state.get("market")},
            }
            direction_correct, _move_pct, _threshold = v2._direction_result(row_for_direction, endpoint_value)
            trade = dict(state.get("trade") or {})
            trade_result = v2._trade_path_result(trade, list(path.get("bars") or []), endpoint_value)
            trade_outcome = trade_result.get("trade_outcome")
            realised_r = trade_result.get("realised_r")
            learning_success = trade_result.get("learning_success")
            if learning_success is None and str(trade.get("order_type") or "none") == "none":
                learning_success = direction_correct
            challenger_trades = self._challengers(state)
            challengers_scored, best_challenger = self._score_challengers(
                challenger_trades,
                list(path.get("bars") or []),
                endpoint_value,
            )
            challenger_runs = len(challenger_trades)

        payload = {
            "historical_episode_key": episode_key,
            "symbol": self.symbol,
            "candle_time": row.get("candle_time"),
            "observed_at": decision.isoformat(),
            "setup_family": family,
            "independence_key": independence_key,
            "bias": (state.get("bias") or {}).get("overall") or "neutral",
            "confidence": (state.get("bias") or {}).get("confidence"),
            "price": state.get("price"),
            "session": session,
            "regime": (state.get("market") or {}).get("regime"),
            "market_state": {
                "market": state.get("market"),
                "bias": state.get("bias"),
                "liquidity": state.get("liquidity"),
                "setup": state.get("setup"),
                "setup_family_descriptor": state.get("setup_family_descriptor"),
                "historical_replay": {
                    "version": ACADEMY_VERSION,
                    "policy": REPLAY_POLICY,
                    "decision_time": decision.isoformat(),
                    "horizon_at": horizon.isoformat(),
                    "path_complete": path_complete,
                    "m1_path_bars": len(path.get("bars") or []),
                    "initial_gap_seconds": path.get("initial_gap_seconds"),
                    "gap_count": path.get("gap_count"),
                    "endpoint_lag_seconds": endpoint_lag,
                },
            },
            "zones": state.get("zones") or {},
            "trade_idea": state.get("trade") or {},
            "challenger_results": challengers_scored,
            "best_challenger": best_challenger,
            "path_complete": path_complete,
            "m1_path_bars": len(path.get("bars") or []),
            "endpoint_lag_seconds": endpoint_lag,
            "resolved_price": float(endpoint) if endpoint is not None else None,
            "direction_correct": direction_correct,
            "trade_outcome": trade_outcome,
            "realised_r": realised_r,
            "learning_success": learning_success,
            "evidence_weight": HISTORICAL_BASE_WEIGHT,
            "engine_version": ACADEMY_VERSION,
        }
        try:
            await self.repo.client.insert("live_trader_historical_learning", payload, return_rows=False)
        except Exception as exc:
            if "duplicate" in str(exc).lower() or "23505" in str(exc):
                return False, False, 0
            raise
        return True, learning_success is not None, challenger_runs

    async def learn_cycle(self) -> dict[str, Any]:
        state = await self._state()
        if state and str(state.get("engine_version") or "") != ACADEMY_VERSION:
            state = {}
        cursor = str(state.get("cursor_time")) if state.get("cursor_time") else None
        warm, batch = await self._fetch_window(cursor)
        self.last_batch_rows = len(batch)
        self.last_batch_episodes = 0
        if not batch:
            self.caught_up = True
            self.last_cycle_at = core.utc_now().isoformat()
            await self._persist_state(
                state,
                cursor_time=cursor,
                rows_scanned_add=0,
                episodes_add=0,
                scored_add=0,
                challenger_add=0,
                error=None,
            )
            return {"rows": 0, "episodes": 0, "caught_up": True}

        self.caught_up = False
        history = list(warm)
        episodes = 0
        scored = 0
        challengers = 0
        cursor_time = cursor
        for row in batch:
            if self._stop.is_set():
                break
            history.append(row)
            if len(history) > 720:
                history = history[-720:]
            cursor_time = str(row.get("candle_time") or cursor_time or "")
            decision = self._decision_time(row)
            if decision is None or not self._hourly_anchor(decision):
                continue
            if not broker_market_open_through(decision, self.settings.live_trader_learning_horizon_minutes):
                continue
            recorded, was_scored, challenger_count = await self._evaluate(history, row, decision)
            if recorded:
                episodes += 1
                scored += int(was_scored)
                challengers += challenger_count

        self.last_batch_episodes = episodes
        self.runtime_episodes += episodes
        self.runtime_challengers += challengers
        self.last_cycle_at = core.utc_now().isoformat()
        self.last_error = None
        await self._persist_state(
            state,
            cursor_time=cursor_time or cursor,
            rows_scanned_add=len(batch),
            episodes_add=episodes,
            scored_add=scored,
            challenger_add=challengers,
            error=None,
        )
        return {
            "rows": len(batch),
            "episodes": episodes,
            "scored": scored,
            "challengers": challengers,
            "cursor_time": cursor_time,
            "caught_up": False,
        }

    async def run_forever(self) -> None:
        while not self._stop.is_set():
            try:
                await self.learn_cycle()
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                self.last_error = str(exc)[:500]
                core.logger.warning("Historical Academy cycle failed: %s", exc)
                try:
                    previous = await self._state()
                    await self._persist_state(
                        previous,
                        cursor_time=str(previous.get("cursor_time")) if previous.get("cursor_time") else None,
                        rows_scanned_add=0,
                        episodes_add=0,
                        scored_add=0,
                        challenger_add=0,
                        error=self.last_error,
                    )
                except Exception:
                    pass
            try:
                await asyncio.wait_for(self._stop.wait(), timeout=CYCLE_SECONDS)
            except asyncio.TimeoutError:
                pass


core.LiveTrader._trade_idea = _trade_idea_v29  # type: ignore[method-assign]
core.LiveTrader._maybe_record_opinion = _record_v29  # type: ignore[method-assign]
core.LiveTrader._maybe_resolve_opinions = _resolve_v29  # type: ignore[method-assign]
core.LiveTrader._calibration = _calibration_v29  # type: ignore[method-assign]
core.LiveTrader.refresh_state = _refresh_v29  # type: ignore[method-assign]
core.LiveTrader.runtime_status = _runtime_status_v29  # type: ignore[method-assign]
core.LiveTrader.learning_summary = _learning_summary_v29  # type: ignore[method-assign]
