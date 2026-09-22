from __future__ import annotations

import asyncio
import json
from datetime import datetime, timedelta, timezone
from typing import Any

import websockets

from app.services import live_trader as core
from app.services import live_trader_execution_cost_model as cost_model
from app.services import live_trader_evidence_identity as evidence_id
from app.services import live_trader_learning_governor_v25 as governor
from app.services import live_trader_learning_v2 as v2
from app.services import live_trader_learning_v22 as v22
from app.services.repository import SourceRepository

ENGINE_VERSION = "eve-live-learning-engine-v2.6"
LEARNING_NAMESPACE = "eve-live-learning-family-v1"
OUTCOME_SCHEMA = "causal-m1-path-v4-fail-closed-activation-cost"
TIMING_CONTRACT_VERSION = "eve-live-execution-timing-v3-fail-closed"
OBSERVATION_POLICY = (
    "Market observation time identifies the data used by the decision, but executable outcome evidence starts only "
    "after the decision has been durably persisted. Receipt, decision, publication-request, publication-confirmation "
    "and activation timestamps are recorded separately. Causal M1 replay begins at the first full minute at or after "
    "activation, so no pre-publication or partial activation-minute price action can earn entry/target credit."
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


def _first_full_m1_at_or_after(value: datetime) -> datetime:
    value = value.astimezone(timezone.utc)
    minute = value.replace(second=0, microsecond=0)
    return minute if value == minute else minute + timedelta(minutes=1)


def _execution_timing_seed(
    self: core.LiveTrader,
    observed: datetime,
    *,
    decision_at: datetime | None = None,
) -> dict[str, Any]:
    decision = decision_at or core.utc_now()
    received = _parse_time(getattr(self, "last_tick_received_at", None))
    return {
        "version": TIMING_CONTRACT_VERSION,
        "market_observed_at": observed.isoformat(),
        "market_received_at": received.isoformat() if received is not None else None,
        "decision_at": decision.isoformat(),
        "publication_requested_at": None,
        "publication_confirmed_at": None,
        "activation_at": None,
        "execution_start_at": None,
        "pre_activation_price_events_eligible": False,
        "partial_activation_minute_eligible": False,
        "manual_delay_seconds": int(getattr(self.settings, "live_trader_manual_delay_seconds", 15)),
        "manual_execution_eligible_at": None,
    }


async def _insert_timed_forward_opinion(
    self: core.LiveTrader,
    payload: dict[str, Any],
    *,
    observed: datetime,
    market_state: dict[str, Any],
    decision_at: datetime | None = None,
) -> tuple[dict[str, Any] | None, dict[str, Any]]:
    """Persist a forward decision, then activate it only after durable publication.

    If the post-insert activation patch fails the row remains unactivated and
    therefore cannot be scored as executable evidence.
    """
    timing = _execution_timing_seed(self, observed, decision_at=decision_at)
    requested = core.utc_now()
    timing["publication_requested_at"] = requested.isoformat()
    seeded_state = dict(market_state)
    seeded_state["execution_timing"] = dict(timing)

    row_payload = dict(payload)
    trade_idea = dict(row_payload.get("trade_idea") or {})
    execution_cost_profile = cost_model.profile_from_settings(self.settings)
    if str(trade_idea.get("order_type") or "none").lower() != "none":
        trade_idea["execution_cost_model"] = execution_cost_profile
    row_payload["trade_idea"] = trade_idea
    seeded_state["execution_cost_model"] = execution_cost_profile
    row_payload.update(
        {
            "market_observed_at": observed.isoformat(),
            "market_received_at": timing.get("market_received_at"),
            "decision_at": timing.get("decision_at"),
            "publication_requested_at": timing.get("publication_requested_at"),
            "publication_confirmed_at": None,
            "activation_at": None,
            "execution_start_at": None,
            "timing_contract_version": TIMING_CONTRACT_VERSION,
            "market_state": seeded_state,
        }
    )
    inserted = await self.repo.client.insert("live_trader_opinions", row_payload, return_rows=True)
    if not inserted:
        return None, timing

    row = dict(inserted[0] or {})
    row_id = row.get("id")
    if row_id is None:
        return row, timing

    confirmed = core.utc_now()
    execution_cost_profile = cost_model.profile_from_settings(self.settings)
    activation, execution_start = cost_model.manual_execution_start(confirmed, execution_cost_profile)
    timing.update(
        {
            "publication_confirmed_at": confirmed.isoformat(),
            "activation_at": activation.isoformat(),
            "execution_start_at": execution_start.isoformat(),
            "manual_delay_seconds": int(execution_cost_profile.get("manual_delay_seconds") or 0),
            "manual_execution_eligible_at": activation.isoformat(),
        }
    )
    final_state = dict(seeded_state)
    final_state["execution_timing"] = dict(timing)
    await self.repo.client.patch(
        "live_trader_opinions",
        {
            "publication_confirmed_at": confirmed.isoformat(),
            "activation_at": activation.isoformat(),
            "execution_start_at": execution_start.isoformat(),
            "market_state": final_state,
        },
        filters={"id": f"eq.{row_id}"},
    )
    row.update(
        {
            "publication_confirmed_at": confirmed.isoformat(),
            "activation_at": activation.isoformat(),
            "execution_start_at": execution_start.isoformat(),
            "market_state": final_state,
        }
    )
    return row, timing


def _execution_window(
    row: dict[str, Any],
    *,
    fallback_observed: datetime,
    horizon_minutes: int,
    allow_legacy_fallback: bool = True,
) -> tuple[datetime, datetime, bool, dict[str, Any]]:
    contract = str(row.get("timing_contract_version") or "")
    market_received = _parse_time(row.get("market_received_at"))
    decision = _parse_time(row.get("decision_at"))
    publication_requested = _parse_time(row.get("publication_requested_at"))
    publication_confirmed = _parse_time(row.get("publication_confirmed_at"))
    activation = _parse_time(row.get("activation_at"))
    execution_start = _parse_time(row.get("execution_start_at"))

    required = {
        "market_received_at": market_received,
        "decision_at": decision,
        "publication_requested_at": publication_requested,
        "publication_confirmed_at": publication_confirmed,
        "activation_at": activation,
        "execution_start_at": execution_start,
    }
    missing = [name for name, value in required.items() if value is None]
    timing_failure_reason: str | None = None
    verified = contract == TIMING_CONTRACT_VERSION and not missing

    if verified:
        assert market_received is not None
        assert decision is not None
        assert publication_requested is not None
        assert publication_confirmed is not None
        assert activation is not None
        assert execution_start is not None
        if not (
            market_received <= decision
            <= publication_requested
            <= publication_confirmed
            <= activation
            <= execution_start
        ):
            verified = False
            timing_failure_reason = "non_causal_current_timing_order"
        elif execution_start != _first_full_m1_at_or_after(activation):
            verified = False
            timing_failure_reason = "execution_start_not_first_full_m1_after_activation"
    elif contract == TIMING_CONTRACT_VERSION:
        timing_failure_reason = "missing_current_timing_fields:" + ",".join(missing)
    else:
        timing_failure_reason = "legacy_or_unknown_timing_contract"

    legacy_fallback_used = bool(not verified and allow_legacy_fallback and contract != TIMING_CONTRACT_VERSION)
    if verified:
        assert activation is not None and execution_start is not None
        start = execution_start
        horizon = activation + timedelta(minutes=max(horizon_minutes, 1))
    else:
        # The timestamps are returned for diagnostics only. Current forward,
        # shadow and Policy Lab resolvers pass allow_legacy_fallback=False and
        # must not score this window when verified is false.
        start = fallback_observed
        horizon = fallback_observed + timedelta(minutes=max(horizon_minutes, 1))

    return start, horizon, verified, {
        "timing_contract_version": contract or None,
        "market_observed_at": row.get("market_observed_at") or fallback_observed.isoformat(),
        "market_received_at": row.get("market_received_at"),
        "decision_at": row.get("decision_at"),
        "publication_requested_at": row.get("publication_requested_at"),
        "publication_confirmed_at": row.get("publication_confirmed_at"),
        "activation_at": row.get("activation_at"),
        "execution_start_at": (execution_start.isoformat() if execution_start is not None else None),
        "executable_timing_verified": verified,
        "timing_failure_reason": timing_failure_reason,
        "legacy_timing_fallback_allowed": allow_legacy_fallback,
        "legacy_timing_fallback_used": legacy_fallback_used,
        "pre_activation_price_events_excluded": verified,
        "partial_activation_minute_excluded": verified,
    }


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
    identity = evidence_id.production_identity(
        self.settings,
        learning_version=LEARNING_NAMESPACE,
        evaluation_stage="production_forward_learning",
    )
    try:
        rows = await self.repo.client.get(
            "live_trader_opinions",
            params={
                "select": "learning_success,episode_key,observed_at,market_state",
                "setup_family": f"eq.{signature}",
                "learning_version": f"eq.{LEARNING_NAMESPACE}",
                "cohort_id": f"eq.{identity['cohort_id']}",
                "independent_sample": "eq.true",
                "status": "eq.resolved",
                "timing_contract_version": f"eq.{TIMING_CONTRACT_VERSION}",
                "publication_confirmed_at": "not.is.null",
                "activation_at": "not.is.null",
                "execution_start_at": "not.is.null",
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
    learning["evidence_identity"] = evidence_id.public_identity(identity)
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
    identity = evidence_id.production_identity(
        self.settings,
        learning_version=LEARNING_NAMESPACE,
        evaluation_stage="production_forward_learning",
    )
    try:
        await evidence_id.ensure_registered(self.repo, identity)
        existing = await self.repo.client.get(
            "live_trader_opinions",
            params={
                "select": "id,timing_contract_version,activation_at",
                "setup_family": f"eq.{family}",
                "episode_key": f"eq.{episode}",
                "learning_version": f"eq.{LEARNING_NAMESPACE}",
                "cohort_id": f"eq.{identity['cohort_id']}",
                "limit": "1",
            },
        )
        if existing:
            return

        decision_at = core.utc_now()
        market_state = {
            "market": record_state.get("market"),
            "bias": record_state.get("bias"),
            "liquidity": record_state.get("liquidity"),
            "setup_family_descriptor": record_state.get("setup_family_descriptor"),
            "learning_observation": {
                "policy": OBSERVATION_POLICY,
                "market_observed_at": observed.isoformat(),
                "engine_version": ENGINE_VERSION,
                "outcome_schema": OUTCOME_SCHEMA,
            },
            "evidence_identity": evidence_id.public_identity(identity),
        }
        row, timing = await _insert_timed_forward_opinion(
            self,
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
                "zones": record_state.get("zones") or {},
                "trade_idea": evidence_id.attach_trade(dict(record_state.get("trade") or {}), identity),
                "opinion_text": record_state.get("opinion") or "",
                "status": "open",
                **evidence_id.row_columns(identity),
            },
            observed=observed,
            market_state=market_state,
            decision_at=decision_at,
        )
        if row is not None and timing.get("activation_at"):
            self._last_recorded_signature = family
            self._last_opinion_at = _parse_time(timing.get("publication_confirmed_at")) or core.utc_now()
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
                "select": (
                    "id,observed_at,price,bias,horizon_minutes,market_state,trade_idea,"
                    "market_observed_at,market_received_at,decision_at,publication_requested_at,"
                    "publication_confirmed_at,activation_at,execution_start_at,timing_contract_version"
                ),
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
            path_start, horizon, timing_verified, timing = _execution_window(
                row,
                fallback_observed=observed,
                horizon_minutes=horizon_minutes,
                allow_legacy_fallback=False,
            )
            if not timing_verified:
                continue
            if now < horizon:
                continue

            source_rows = await _source_m1_rows(self, path_start, horizon)
            path = _causal_m1_path(source_rows, path_start, horizon)
            endpoint = path.get("endpoint_price")
            endpoint_time = path.get("endpoint_time")
            endpoint_lag = path.get("endpoint_lag_seconds")
            if endpoint is None or endpoint_time is None or endpoint_lag is None or endpoint_lag > MAX_ENDPOINT_LAG_SECONDS:
                continue

            direction_correct, move_pct, threshold = v2._direction_result(row, float(endpoint))
            trade = dict(row.get("trade_idea") or {})
            order_type = str(trade.get("order_type") or "none")
            path_complete = (
                path.get("initial_gap_seconds") is not None
                and float(path.get("initial_gap_seconds") or 0.0) <= 1.0
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
                "path_start_at": path_start.isoformat(),
                "horizon_at": horizon.isoformat(),
                "resolved_price_time": endpoint_time.isoformat(),
                "m1_path_bars": len(path.get("bars") or []),
                "initial_gap_seconds": path.get("initial_gap_seconds"),
                "gap_count": path.get("gap_count"),
                "endpoint_lag_seconds": endpoint_lag,
                "actionable_path_complete": path_complete,
                "execution_costs": trade_result.get("execution_costs"),
                **timing,
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
                    "gross_realised_r": trade_result.get("gross_realised_r"),
                    "estimated_cost_r": trade_result.get("estimated_cost_r"),
                    "net_realised_r": trade_result.get("net_realised_r"),
                    "net_learning_success": trade_result.get("net_learning_success"),
                    "cost_model_version": trade_result.get("cost_model_version"),
                    "execution_costs": trade_result.get("execution_costs"),
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
            "execution_timing_contract_version": TIMING_CONTRACT_VERSION,
            "pre_publication_price_credit_allowed": False,
            "partial_activation_minute_credit_allowed": False,
            "execution_timing_fail_closed": True,
            "legacy_timing_fallback_allowed_for_current_evidence": False,
            "manual_execution_delay_seconds": int(getattr(self.settings, "live_trader_manual_delay_seconds", 15)),
            "execution_cost_model_version": cost_model.COST_MODEL_VERSION,
            "gross_and_net_r_separated": True,
            "evidence_identity_version": evidence_id.IDENTITY_VERSION,
            "production_forward_cohort_id": evidence_id.production_identity(
                self.settings,
                learning_version=LEARNING_NAMESPACE,
                evaluation_stage="production_forward_learning",
            )["cohort_id"],
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
