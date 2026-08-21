from __future__ import annotations

import asyncio
import json
from datetime import datetime, timedelta, timezone
from typing import Any

import websockets

from app.services import live_trader as core
from app.services import live_trader_learning_governor_v25 as governor
from app.services import live_trader_learning_v2 as v2
from app.services import live_trader_learning_v22 as v22
from app.services.repository import SourceRepository

ENGINE_VERSION = "eve-live-learning-engine-v2.6"
LEARNING_NAMESPACE = "eve-live-learning-family-v1"
OUTCOME_SCHEMA = "causal-m1-path-v1"
OBSERVATION_POLICY = (
    "Learning observations are clocked to the market-data timestamp used by the decision, not the later wall-clock "
    "database insert time. Actionable outcomes are reconstructed from the read-only source M1 path; incomplete M1 "
    "paths are never scored as wins or losses."
)
SOCKET_WARMUP_SECONDS = 30.0
MAX_ENDPOINT_LAG_SECONDS = 75.0

_current_signature = core.LiveTrader._signature
_current_runtime_status = core.LiveTrader.runtime_status


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


def _signature_v26(self: core.LiveTrader, state: dict[str, Any]) -> str:
    signature = _current_signature(self, state)
    state["learning_version"] = LEARNING_NAMESPACE
    state["learning_engine_version"] = ENGINE_VERSION
    state["learning_outcome_schema"] = OUTCOME_SCHEMA
    return signature


def _market_observation_time(state: dict[str, Any]) -> datetime | None:
    feed = dict(state.get("feed") or {})
    if not bool(feed.get("connected")):
        return None
    observed = _parse_time(state.get("as_of") or feed.get("last_tick_at"))
    if observed is None:
        return None
    now = core.utc_now()
    if observed > now + timedelta(seconds=5):
        return None
    # The feed guard already defines the production freshness contract. Do not
    # manufacture learning samples from a market timestamp outside that window.
    tick_age = (now - observed).total_seconds()
    if tick_age < 0 or tick_age > 90.0:
        return None
    return observed


async def _calibration_v26(self: core.LiveTrader, signature: str) -> dict[str, Any]:
    try:
        rows = await self.repo.client.get(
            "live_trader_opinions",
            params={
                "select": "learning_success,episode_key,observed_at,market_state",
                "setup_family": f"eq.{signature}",
                "learning_version": f"eq.{LEARNING_NAMESPACE}",
                "independent_sample": "eq.true",
                "status": "eq.resolved",
                "order": "observed_at.desc",
                "limit": "500",
            },
        )
    except Exception:
        rows = []
    current = getattr(self, "_learning_descriptor_v22", {}) or {}
    learning = v22.weighted_calibration_from_rows(rows, current)
    learning["learning_version"] = LEARNING_NAMESPACE
    learning["engine_version"] = ENGINE_VERSION
    learning["outcome_schema"] = OUTCOME_SCHEMA
    state = getattr(self, "_learning_governor_pending_state", None)
    if isinstance(state, dict):
        governor.apply_learning_governor(state, learning)
    return learning


def _record_state_for_governor(state: dict[str, Any]) -> dict[str, Any] | None:
    info = dict(state.get("learning_governor") or {})
    if info.get("decision") != "veto":
        return state
    candidate = info.get("candidate_trade")
    if not isinstance(candidate, dict) or str(candidate.get("order_type") or "none") == "none":
        return None
    shadow = dict(state)
    shadow["trade"] = dict(candidate)
    shadow["opinion"] = (
        f"Shadow candidate rejected by {governor.GOVERNOR_VERSION}: "
        f"{candidate.get('action') or candidate.get('order_type')} retained for causal outcome learning only."
    )
    return shadow


async def _record_v26(self: core.LiveTrader, state: dict[str, Any]) -> None:
    record_state = _record_state_for_governor(state)
    if record_state is None:
        return
    observed = _market_observation_time(record_state)
    if observed is None:
        return
    family = str(record_state.get("setup_family") or record_state.get("setup_signature") or "")
    if not family:
        return
    episode = v22.episode_key(record_state)
    try:
        existing = await self.repo.client.get(
            "live_trader_opinions",
            params={
                "select": "id",
                "setup_family": f"eq.{family}",
                "episode_key": f"eq.{episode}",
                "learning_version": f"eq.{LEARNING_NAMESPACE}",
                "limit": "1",
            },
        )
        if existing:
            return
        recorded_at = core.utc_now()
        await self.repo.client.insert(
            "live_trader_opinions",
            {
                "observed_at": observed.isoformat(),
                "symbol": self.symbol,
                "price": record_state.get("price"),
                "bias": (record_state.get("bias") or {}).get("overall"),
                "confidence": (record_state.get("bias") or {}).get("confidence"),
                "horizon_minutes": self.settings.live_trader_learning_horizon_minutes,
                "setup_signature": family,
                "setup_family": family,
                "episode_key": episode,
                "learning_version": LEARNING_NAMESPACE,
                "independent_sample": True,
                "market_state": {
                    "market": record_state.get("market"),
                    "bias": record_state.get("bias"),
                    "liquidity": record_state.get("liquidity"),
                    "setup_family_descriptor": record_state.get("setup_family_descriptor"),
                    "learning_observation": {
                        "policy": OBSERVATION_POLICY,
                        "market_observed_at": observed.isoformat(),
                        "recorded_at": recorded_at.isoformat(),
                        "engine_version": ENGINE_VERSION,
                        "outcome_schema": OUTCOME_SCHEMA,
                    },
                },
                "zones": record_state.get("zones") or {},
                "trade_idea": record_state.get("trade") or {},
                "opinion_text": record_state.get("opinion") or "",
                "status": "open",
            },
            return_rows=False,
        )
        self._last_recorded_signature = family
        self._last_opinion_at = recorded_at
    except Exception as exc:
        core.logger.warning("Live Trader v2.6 could not record causal learning observation: %s", exc)


async def _source_m1_rows(self: core.LiveTrader, observed: datetime, horizon: datetime) -> list[dict[str, Any]]:
    source = getattr(self, "_learning_source_repo_v26", None)
    if source is None:
        source = SourceRepository(self.settings)
        self._learning_source_repo_v26 = source
    rows: list[dict[str, Any]] = []
    cursor: str | None = None
    while len(rows) < 2000:
        page = await source.fetch_candles_page(
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
    return rows


def _causal_m1_path(rows: list[dict[str, Any]], observed: datetime, horizon: datetime) -> dict[str, Any]:
    completed: list[dict[str, Any]] = []
    starts: list[datetime] = []
    for row in rows:
        start = _parse_time(row.get("candle_time"))
        if start is None:
            continue
        close_time = start + timedelta(minutes=1)
        if start >= observed and close_time <= horizon:
            completed.append(row)
            starts.append(start)
    paired = sorted(zip(starts, completed), key=lambda item: item[0])
    starts = [item[0] for item in paired]
    completed = [item[1] for item in paired]
    initial_gap = max(0.0, (starts[0] - observed).total_seconds()) if starts else None
    gap_count = 0
    for left, right in zip(starts, starts[1:]):
        if right - left != timedelta(minutes=1):
            gap_count += 1
    endpoint_price = None
    endpoint_time = None
    if paired:
        endpoint_time = starts[-1] + timedelta(minutes=1)
        endpoint_price = core.number(completed[-1].get("close"))
    endpoint_lag = (horizon - endpoint_time).total_seconds() if endpoint_time is not None else None
    return {
        "bars": completed,
        "initial_gap_seconds": initial_gap,
        "gap_count": gap_count,
        "endpoint_price": endpoint_price,
        "endpoint_time": endpoint_time,
        "endpoint_lag_seconds": endpoint_lag,
    }


async def _resolve_v26(self: core.LiveTrader, _live_price: float) -> None:
    now = core.utc_now()
    if self._last_resolution_at and now - self._last_resolution_at < timedelta(seconds=30):
        return
    self._last_resolution_at = now
    cutoff = now - timedelta(minutes=self.settings.live_trader_learning_horizon_minutes)
    try:
        opinions = await self.repo.client.get(
            "live_trader_opinions",
            params={
                "select": "id,observed_at,price,bias,horizon_minutes,market_state,trade_idea",
                "status": "eq.open",
                "learning_version": f"eq.{LEARNING_NAMESPACE}",
                "independent_sample": "eq.true",
                "observed_at": f"lte.{cutoff.isoformat()}",
                "order": "observed_at.asc",
                "limit": "100",
            },
        )
        for row in opinions:
            observed = _parse_time(row.get("observed_at"))
            if observed is None or core.number(row.get("price")) <= 0:
                continue
            horizon_minutes = int(core.number(row.get("horizon_minutes"), self.settings.live_trader_learning_horizon_minutes))
            horizon = observed + timedelta(minutes=max(horizon_minutes, 1))
            source_rows = await _source_m1_rows(self, observed, horizon)
            path = _causal_m1_path(source_rows, observed, horizon)
            endpoint = path.get("endpoint_price")
            endpoint_time = path.get("endpoint_time")
            endpoint_lag = path.get("endpoint_lag_seconds")
            if endpoint is None or endpoint_time is None or endpoint_lag is None or endpoint_lag > MAX_ENDPOINT_LAG_SECONDS:
                # Source ingestion may be a little behind the horizon. Leave the
                # opinion open and retry rather than resolving it from stale/current price.
                continue

            direction_correct, move_pct, threshold = v2._direction_result(row, float(endpoint))
            trade = dict(row.get("trade_idea") or {})
            order_type = str(trade.get("order_type") or "none")
            path_complete = (
                (path.get("initial_gap_seconds") is not None and float(path.get("initial_gap_seconds") or 0.0) <= 1.0)
                and int(path.get("gap_count") or 0) == 0
            )
            if order_type != "none" and not path_complete:
                trade_result = {
                    "entry_triggered": None,
                    "trade_outcome": "insufficient_m1_path",
                    "realised_r": None,
                    "learning_success": None,
                }
            else:
                trade_result = v2._trade_path_result(trade, list(path.get("bars") or []), float(endpoint))

            learning_success = trade_result.get("learning_success")
            if learning_success is None and order_type == "none":
                learning_success = direction_correct

            market_state = dict(row.get("market_state") or {})
            market_state["learning_resolution"] = {
                "policy": OBSERVATION_POLICY,
                "outcome_schema": OUTCOME_SCHEMA,
                "observed_at": observed.isoformat(),
                "horizon_at": horizon.isoformat(),
                "resolved_price_time": endpoint_time.isoformat(),
                "m1_path_bars": len(path.get("bars") or []),
                "initial_gap_seconds": path.get("initial_gap_seconds"),
                "gap_count": path.get("gap_count"),
                "endpoint_lag_seconds": endpoint_lag,
                "actionable_path_complete": path_complete,
            }
            await self.repo.client.patch(
                "live_trader_opinions",
                {
                    "status": "resolved",
                    "resolved_at": now.isoformat(),
                    "resolved_price": float(endpoint),
                    "realised_move_pct": round(move_pct, 5),
                    "direction_correct": direction_correct,
                    "score_threshold_pct": round(threshold, 5),
                    "entry_triggered": trade_result.get("entry_triggered"),
                    "trade_outcome": trade_result.get("trade_outcome"),
                    "realised_r": trade_result.get("realised_r"),
                    "learning_success": learning_success,
                    "market_state": market_state,
                },
                filters={"id": f"eq.{row.get('id')}"},
            )
    except Exception as exc:
        core.logger.warning("Live Trader v2.6 could not resolve causal M1 outcomes: %s", exc)


async def _learning_summary_v26(self: core.LiveTrader) -> dict[str, Any]:
    try:
        rows = await self.repo.client.get(
            "live_trader_opinions",
            params={
                "select": "learning_success,direction_correct,trade_outcome,realised_r,observed_at,setup_family,episode_key",
                "status": "eq.resolved",
                "learning_version": f"eq.{LEARNING_NAMESPACE}",
                "independent_sample": "eq.true",
                "order": "observed_at.desc",
                "limit": "5000",
            },
        )
    except Exception:
        rows = []
    scored = [bool(row.get("learning_success")) for row in rows if row.get("learning_success") is not None]
    directional = [bool(row.get("direction_correct")) for row in rows if row.get("direction_correct") is not None]
    actionable = [row for row in rows if row.get("trade_outcome") not in {None, "not_triggered", "invalid", "insufficient_m1_path"}]
    trade_scored = [bool(row.get("learning_success")) for row in actionable if row.get("learning_success") is not None]
    return {
        "resolved": len(rows),
        "scored": len(scored),
        "correct": sum(scored),
        "accuracy": round(sum(scored) / len(scored), 3) if scored else None,
        "directional_accuracy": round(sum(directional) / len(directional), 3) if directional else None,
        "actionable_trades": len(actionable),
        "trade_accuracy": round(sum(trade_scored) / len(trade_scored), 3) if trade_scored else None,
        "independent_episodes": len({str(row.get('episode_key')) for row in rows if row.get('episode_key')}),
        "families_seen": len({str(row.get('setup_family')) for row in rows if row.get('setup_family')}),
        "independent_days": len({str(row.get('observed_at'))[:10] for row in rows if row.get('observed_at')}),
        "horizon_minutes": self.settings.live_trader_learning_horizon_minutes,
        "version": LEARNING_NAMESPACE,
        "engine_version": ENGINE_VERSION,
        "outcome_schema": OUTCOME_SCHEMA,
        "policy": OBSERVATION_POLICY,
    }


def _socket_should_reconnect(self: core.LiveTrader, connected_at: datetime, *, now: datetime | None = None) -> bool:
    current = now or core.utc_now()
    if current - connected_at < timedelta(seconds=SOCKET_WARMUP_SECONDS):
        return False
    return not self._feed_is_fresh()


async def _run_forever_v26(self: core.LiveTrader) -> None:
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
                connected_at = core.utc_now()
                try:
                    while not self._stop.is_set():
                        try:
                            message = await asyncio.wait_for(websocket.recv(), timeout=15)
                        except asyncio.TimeoutError:
                            if _socket_should_reconnect(self, connected_at):
                                age = self._tick_age_seconds()
                                raise RuntimeError(
                                    f"stale Twelve Data price feed under configured freshness policy: "
                                    f"last tick age {age if age is not None else 'unknown'} seconds"
                                )
                            continue
                        try:
                            payload = json.loads(message)
                        except (TypeError, json.JSONDecodeError):
                            continue
                        if isinstance(payload, dict):
                            await self._handle_price(payload)
                        if _socket_should_reconnect(self, connected_at):
                            age = self._tick_age_seconds()
                            raise RuntimeError(
                                f"stale Twelve Data price feed under configured freshness policy: "
                                f"last tick age {age if age is not None else 'unknown'} seconds"
                            )
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
            core.logger.warning("Live Trader WebSocket disconnected: %s", exc)
            try:
                await self.refresh_state(force_rows=True)
            except Exception:
                pass
            try:
                await asyncio.wait_for(self._stop.wait(), timeout=backoff)
                return
            except asyncio.TimeoutError:
                backoff = min(backoff * 2, 60)


def _runtime_status_v26(self: core.LiveTrader) -> dict[str, Any]:
    state = dict(_current_runtime_status(self))
    state.update(
        {
            "learning_version": LEARNING_NAMESPACE,
            "learning_engine_version": ENGINE_VERSION,
            "learning_outcome_schema": OUTCOME_SCHEMA,
            "learning_observation_policy": OBSERVATION_POLICY,
            "learning_namespace_stable": True,
            "learning_uses_source_m1_path": True,
            "socket_staleness_uses_feed_policy": True,
        }
    )
    return state


# Install after the v2.5 governor. The governor still operates, but calibration
# and recording now use a stable learning namespace and causal source-M1 outcomes.
core.LiveTrader._signature = _signature_v26  # type: ignore[method-assign]
core.LiveTrader._calibration = _calibration_v26  # type: ignore[method-assign]
core.LiveTrader._maybe_record_opinion = _record_v26  # type: ignore[method-assign]
core.LiveTrader._maybe_resolve_opinions = _resolve_v26  # type: ignore[method-assign]
core.LiveTrader.learning_summary = _learning_summary_v26  # type: ignore[method-assign]
core.LiveTrader.run_forever = _run_forever_v26  # type: ignore[method-assign]
core.LiveTrader.runtime_status = _runtime_status_v26  # type: ignore[method-assign]
