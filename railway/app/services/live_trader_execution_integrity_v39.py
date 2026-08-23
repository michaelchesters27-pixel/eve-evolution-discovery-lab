from __future__ import annotations

import asyncio
import re
from datetime import datetime, timedelta, timezone
from typing import Any

from app.services import live_trader as core
from app.services import live_trader_audit_hardening_v26 as hardening
from app.services import live_trader_historical_learning_v29 as academy
from app.services import live_trader_historical_runtime_v30 as runtime
from app.services import live_trader_learning_v2 as v2
from app.services import live_trader_learning_v22 as v22
from app.services import live_trader_trade_lock_v28 as lock
from app.services.repository import SourceRepository

EXECUTION_SCHEMA = "causal-m1-invalidation-aware-v2"
REGRADER_VERSION = "eve-live-historical-execution-regrade-v1"
PUBLICATION_WINDOW_SECONDS = 120.0
REGRADER_BATCH_ROWS = 120
REGRADER_IDLE_SECONDS = 0.5
OPEN_CAMPAIGN_STATUSES = {"pending", "active"}
TERMINAL_CAMPAIGN_STATUSES = {"won", "lost", "invalidated", "expired"}

_current_record = core.LiveTrader._maybe_record_opinion
_current_trade_idea = core.LiveTrader._trade_idea
_current_run_forever = core.LiveTrader.run_forever
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


def _num(value: Any, default: float = 0.0) -> float:
    return core.number(value, default)


def _invalidation_level(trade: dict[str, Any], stop: float) -> float:
    explicit = _num(trade.get("invalidation_price"), 0.0)
    if explicit > 0:
        return explicit
    text = str(trade.get("invalidation") or "")
    directional = re.findall(r"(?:below|above)\s+(\d+(?:\.\d+)?)", text, flags=re.IGNORECASE)
    if directional:
        return _num(directional[-1], stop)
    return stop


def _invalidated_result() -> dict[str, Any]:
    return {
        "entry_triggered": False,
        "trade_outcome": "invalidated_before_entry",
        "realised_r": 0.0,
        "learning_success": None,
    }


def _stop_result(*, ambiguous: bool = False) -> dict[str, Any]:
    return {
        "entry_triggered": True,
        "trade_outcome": "stop_same_bar_ambiguous" if ambiguous else "stop",
        "realised_r": -1.0,
        "learning_success": False,
    }


def _trade_path_result_v39(
    trade: dict[str, Any],
    bars: list[dict[str, Any]],
    resolved_price: float,
) -> dict[str, Any]:
    """Score one causal trade path including the published pre-entry invalidation.

    Pending orders are cancelled if their invalidation boundary trades before entry.
    When an M1 bar spans both the entry and invalidation boundary and ordering cannot
    be proven, the adverse entry-then-stop sequence is assumed rather than awarding
    an optimistic cancellation/win. Market orders retain the established stop-first
    same-bar rule.
    """

    order_type = str(trade.get("order_type") or "none").lower()
    side = str(trade.get("side") or "").upper()
    if order_type == "none" or side not in {"BUY", "SELL"}:
        return {"entry_triggered": None, "trade_outcome": None, "realised_r": None, "learning_success": None}

    entry = _num(trade.get("entry"))
    stop = _num(trade.get("stop"))
    target = _num(trade.get("target"))
    risk = abs(entry - stop)
    if entry <= 0 or risk <= 0 or target <= 0:
        return {"entry_triggered": False, "trade_outcome": "invalid", "realised_r": None, "learning_success": None}

    invalidation = _invalidation_level(trade, stop)
    triggered = order_type == "market"

    for bar in bars:
        open_price = _num(bar.get("open"))
        low = _num(bar.get("low"))
        high = _num(bar.get("high"))
        ambiguous_entry_stop = False

        if not triggered:
            if order_type == "buy_stop":
                entry_hit = high >= entry
                invalid_hit = invalidation > 0 and low <= invalidation
                if open_price > 0 and open_price <= invalidation:
                    return _invalidated_result()
                if open_price >= entry > 0:
                    triggered = True
                elif entry_hit and invalid_hit:
                    triggered = True
                    ambiguous_entry_stop = True
                elif invalid_hit:
                    return _invalidated_result()
                elif entry_hit:
                    triggered = True
            elif order_type == "sell_stop":
                entry_hit = low <= entry
                invalid_hit = invalidation > 0 and high >= invalidation
                if open_price >= invalidation > 0:
                    return _invalidated_result()
                if 0 < open_price <= entry:
                    triggered = True
                elif entry_hit and invalid_hit:
                    triggered = True
                    ambiguous_entry_stop = True
                elif invalid_hit:
                    return _invalidated_result()
                elif entry_hit:
                    triggered = True
            elif order_type == "buy_limit":
                # A normal descent from above crosses the limit before the stop.
                # Only a bar opening beyond the invalidation is a proven pre-entry gap.
                if open_price > 0 and open_price <= invalidation:
                    return _invalidated_result()
                if (0 < open_price <= entry) or low <= entry:
                    triggered = True
            elif order_type == "sell_limit":
                if open_price >= invalidation > 0:
                    return _invalidated_result()
                if open_price >= entry > 0 or high >= entry:
                    triggered = True
            elif order_type == "market":
                triggered = True

        if not triggered:
            continue

        if side == "BUY":
            stop_hit = low <= stop
            target_hit = high >= target
        else:
            stop_hit = high >= stop
            target_hit = low <= target
        if stop_hit:
            return _stop_result(ambiguous=ambiguous_entry_stop)
        if target_hit:
            rr = abs(target - entry) / risk
            return {
                "entry_triggered": True,
                "trade_outcome": "target",
                "realised_r": round(rr, 3),
                "learning_success": True,
            }

    if not triggered:
        return {"entry_triggered": False, "trade_outcome": "not_triggered", "realised_r": 0.0, "learning_success": None}

    mtm_r = (resolved_price - entry) / risk if side == "BUY" else (entry - resolved_price) / risk
    mtm_r = round(core.clamp(mtm_r, -1.0, max(_num(trade.get("risk_reward")), 3.0)), 3)
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


def _campaign_publication_is_current(campaign: dict[str, Any], state: dict[str, Any]) -> bool:
    created = _parse_time(campaign.get("created_at"))
    observed = hardening._market_observation_time(state)
    if created is None or observed is None:
        return False
    return abs((observed - created).total_seconds()) <= PUBLICATION_WINDOW_SECONDS


async def _record_v39(self: core.LiveTrader, state: dict[str, Any]) -> None:
    # Do not mix live evidence with a partially regraded historical calibration.
    if getattr(self, "_execution_regrade_ready_v39", False) is not True:
        return

    campaign = state.get("trade_campaign")
    if not isinstance(campaign, dict):
        campaign = getattr(self, "_live_campaign", None)
    if not isinstance(campaign, dict):
        await _current_record(self, state)
        return

    status = str(campaign.get("status") or "").lower()
    if status not in OPEN_CAMPAIGN_STATUSES:
        # Terminal display/follow-through states are outcomes, not new decisions.
        return
    if not _campaign_publication_is_current(campaign, state):
        # An old pending/active locked trade is still the same decision.
        return

    marker = dict(campaign.get("forward_learning_v39") or {})
    if marker.get("publication_recorded") is True:
        return

    record_state = dict(state)
    trade = dict(record_state.get("trade") or {})
    trade["invalidation_price"] = campaign.get("invalidation_price")
    trade["campaign_publication"] = True
    record_state["trade"] = trade
    await _current_record(self, record_state)

    # Persist a campaign-level marker only after the stable-namespace row can be
    # observed in the ledger. This survives restarts and prevents a second family
    # from being manufactured during the same publication window.
    try:
        rows = await self.repo.client.get(
            "live_trader_opinions",
            params={
                "select": "id",
                "learning_version": f"eq.{hardening.LEARNING_NAMESPACE}",
                "trade_idea->>campaign_id": f"eq.{campaign.get('id')}",
                "limit": "1",
            },
        )
    except Exception:
        rows = []
    if rows:
        campaign["forward_learning_v39"] = {
            "version": EXECUTION_SCHEMA,
            "publication_recorded": True,
            "recorded_at": core.utc_now().isoformat(),
        }
        self._live_campaign = campaign
        self._live_campaign_dirty = True
        try:
            await lock._persist_campaign(self, campaign)
        except Exception as exc:
            core.logger.warning("Live Trader v3.9 could not persist publication-learning marker: %s", exc)


def _trade_idea_v39(
    self: core.LiveTrader,
    price: float,
    atr: float,
    bias: dict[str, Any],
    zones: dict[str, list[dict[str, Any]]],
    liquidity: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, Any]]:
    # Broker closure remains the stronger, user-facing safety state.
    if not academy.broker_market_open(core.utc_now()):
        return _current_trade_idea(self, price, atr, bias, zones, liquidity)

    campaign = getattr(self, "_live_campaign", None)
    status = str((campaign or {}).get("status") or "").lower() if isinstance(campaign, dict) else ""
    ready = getattr(self, "_execution_regrade_ready_v39", False) is True

    if ready or status in OPEN_CAMPAIGN_STATUSES:
        return _current_trade_idea(self, price, atr, bias, zones, liquidity)

    if isinstance(campaign, dict) and status in TERMINAL_CAMPAIGN_STATUSES:
        trade = lock._campaign_trade(campaign)
        trade["execution_revalidation_block"] = True
        return (
            {
                "status": "EXECUTION EVIDENCE REVALIDATION — NO REPLACEMENT TRADE",
                "reason": "The finished campaign remains visible while EVE revalidates historical execution outcomes. No replacement campaign can be published until that audit is complete.",
            },
            trade,
        )

    reason = (
        "EVE is revalidating every Historical Academy execution with the corrected pre-entry invalidation rule. "
        "She will not publish a new XAU/USD campaign until the evidence ledger is internally consistent."
    )
    return (
        {"status": "EXECUTION EVIDENCE REVALIDATION — NO NEW TRADE", "reason": reason},
        {
            "action": "WAIT",
            "order_type": "none",
            "reason": reason,
            "manual_only": True,
            "automatic_order_placement": False,
            "execution_revalidation_block": True,
        },
    )


def _score_challengers_v39(challengers: dict[str, Any], bars: list[dict[str, Any]], endpoint: float) -> tuple[dict[str, Any], str]:
    scored: dict[str, Any] = {}
    best_name: str | None = None
    best_r = float("-inf")
    for name, payload in challengers.items():
        item = dict(payload or {})
        trade = dict(item.get("trade") or {})
        if not trade:
            scored[name] = item
            continue
        result = _trade_path_result_v39(trade, bars, endpoint)
        scored[name] = {"trade": trade, **result}
        realised = result.get("realised_r")
        if realised is not None and bool(result.get("entry_triggered")) and _num(realised, -999.0) > best_r:
            best_r = _num(realised)
            best_name = str(name)
    return scored, best_name or "no_trade"


class HistoricalExecutionRegrader:
    def __init__(self, owner: core.LiveTrader) -> None:
        self.owner = owner
        self.settings = owner.settings
        self.repo = owner.repo
        self.source = SourceRepository(owner.settings)
        self.symbol = owner.symbol
        self._stop = asyncio.Event()
        self.last_state: dict[str, Any] = {
            "version": REGRADER_VERSION,
            "running": False,
            "completed": False,
        }

    async def stop(self) -> None:
        self._stop.set()

    async def _state(self) -> dict[str, Any]:
        rows = await self.repo.client.get(
            "live_trader_execution_regrade_state",
            params={"select": "*", "symbol": f"eq.{self.symbol}", "limit": "1"},
        )
        return dict(rows[0]) if rows else {}

    async def _persist(self, state: dict[str, Any]) -> None:
        payload = {
            "symbol": self.symbol,
            "version": REGRADER_VERSION,
            "cursor_time": state.get("cursor_time"),
            "rows_checked": int(_num(state.get("rows_checked"))),
            "rows_regraded": int(_num(state.get("rows_regraded"))),
            "outcome_changes": int(_num(state.get("outcome_changes"))),
            "challenger_changes": int(_num(state.get("challenger_changes"))),
            "completed": bool(state.get("completed")),
            "completed_at": state.get("completed_at"),
            "last_cycle_at": core.utc_now().isoformat(),
            "last_error": state.get("last_error"),
            "updated_at": core.utc_now().isoformat(),
        }
        await self.repo.client.upsert(
            "live_trader_execution_regrade_state",
            payload,
            on_conflict="symbol",
            return_rows=False,
        )
        self.last_state = dict(payload)

    async def _source_window(self, start: datetime, end: datetime) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        cursor: str | None = None
        while len(rows) < 100000:
            page = await self.source.fetch_candles_page(
                self.symbol,
                "1min",
                after=cursor,
                date_from=start.isoformat() if cursor is None else None,
                date_to=end.isoformat(),
                limit=1000,
            )
            if not page:
                break
            rows.extend(page)
            cursor = str(page[-1].get("candle_time"))
            if len(page) < 1000:
                break
        return rows

    async def _resync_historical_counters(self) -> None:
        try:
            metrics = await self.repo.client.rpc("get_live_trader_intelligence_metrics", {"p_symbol": self.symbol})
            if isinstance(metrics, list) and metrics:
                metrics = metrics[0]
            if not isinstance(metrics, dict):
                return
            await self.repo.client.patch(
                "live_trader_historical_state",
                {
                    "episodes_recorded": int(_num(metrics.get("historical_episodes"))),
                    "scored_episodes": int(_num(metrics.get("historical_scored"))),
                    "challenger_runs": int(_num(metrics.get("challenger_runs"))),
                    "updated_at": core.utc_now().isoformat(),
                },
                filters={"symbol": f"eq.{self.symbol}"},
            )
        except Exception as exc:
            core.logger.warning("Live Trader v3.9 could not resync Historical Academy counters: %s", exc)

    async def learn_cycle(self) -> bool:
        state = await self._state()
        if bool(state.get("completed")) and str(state.get("version") or "") == REGRADER_VERSION:
            self.owner._execution_regrade_ready_v39 = True
            self.last_state = state
            return False

        cursor = _parse_time(state.get("cursor_time"))
        params = {
            "select": (
                "historical_episode_key,observed_at,path_complete,direction_correct,resolved_price,trade_idea,"
                "trade_outcome,realised_r,learning_success,challenger_results,best_challenger,market_state"
            ),
            "symbol": f"eq.{self.symbol}",
            "order": "observed_at.asc",
            "limit": str(REGRADER_BATCH_ROWS),
        }
        if cursor is not None:
            params["observed_at"] = f"gt.{cursor.isoformat()}"
        rows = await self.repo.client.get("live_trader_historical_learning", params=params)
        if not rows:
            state["completed"] = True
            state["completed_at"] = core.utc_now().isoformat()
            state["last_error"] = None
            await self._persist(state)
            await self._resync_historical_counters()
            self.owner._execution_regrade_ready_v39 = True
            return False

        complete_rows = [row for row in rows if bool(row.get("path_complete"))]
        source_rows: list[dict[str, Any]] = []
        if complete_rows:
            starts = [_parse_time(row.get("observed_at")) for row in complete_rows]
            starts = [stamp for stamp in starts if stamp is not None]
            if starts:
                horizon = timedelta(minutes=max(1, int(self.settings.live_trader_learning_horizon_minutes)))
                source_rows = await self._source_window(min(starts), max(starts) + horizon)

        rows_regraded = 0
        outcome_changes = 0
        challenger_changes = 0
        horizon_delta = timedelta(minutes=max(1, int(self.settings.live_trader_learning_horizon_minutes)))

        for row in complete_rows:
            observed = _parse_time(row.get("observed_at"))
            if observed is None:
                continue
            path = hardening._causal_m1_path(source_rows, observed, observed + horizon_delta)
            endpoint = path.get("endpoint_price")
            endpoint_time = path.get("endpoint_time")
            endpoint_lag = path.get("endpoint_lag_seconds")
            path_ok = (
                endpoint is not None
                and endpoint_time is not None
                and endpoint_lag is not None
                and float(endpoint_lag) <= hardening.MAX_ENDPOINT_LAG_SECONDS
                and path.get("initial_gap_seconds") is not None
                and float(path.get("initial_gap_seconds") or 0.0) <= 1.0
                and int(path.get("gap_count") or 0) == 0
            )
            if not path_ok:
                continue

            bars = list(path.get("bars") or [])
            trade = dict(row.get("trade_idea") or {})
            result = _trade_path_result_v39(trade, bars, float(endpoint))
            success = result.get("learning_success")
            if success is None and str(trade.get("order_type") or "none") == "none":
                success = row.get("direction_correct")

            challengers = dict(row.get("challenger_results") or {})
            rescored_challengers, best_challenger = _score_challengers_v39(challengers, bars, float(endpoint))
            old_tuple = (row.get("trade_outcome"), row.get("realised_r"), row.get("learning_success"))
            new_tuple = (result.get("trade_outcome"), result.get("realised_r"), success)
            if old_tuple != new_tuple:
                outcome_changes += 1
            if challengers and (rescored_challengers != challengers or best_challenger != row.get("best_challenger")):
                challenger_changes += 1

            market_state = dict(row.get("market_state") or {})
            market_state["execution_regrade"] = {
                "version": REGRADER_VERSION,
                "execution_schema": EXECUTION_SCHEMA,
                "regraded_at": core.utc_now().isoformat(),
                "pre_entry_invalidation_enforced": True,
                "same_bar_ambiguity_policy": "adverse_entry_then_stop",
            }
            await self.repo.client.patch(
                "live_trader_historical_learning",
                {
                    "trade_outcome": result.get("trade_outcome"),
                    "realised_r": result.get("realised_r"),
                    "learning_success": success,
                    "challenger_results": rescored_challengers,
                    "best_challenger": best_challenger,
                    "market_state": market_state,
                },
                filters={"historical_episode_key": f"eq.{row.get('historical_episode_key')}"},
            )
            rows_regraded += 1

        state["cursor_time"] = rows[-1].get("observed_at")
        state["rows_checked"] = int(_num(state.get("rows_checked"))) + len(rows)
        state["rows_regraded"] = int(_num(state.get("rows_regraded"))) + rows_regraded
        state["outcome_changes"] = int(_num(state.get("outcome_changes"))) + outcome_changes
        state["challenger_changes"] = int(_num(state.get("challenger_changes"))) + challenger_changes
        state["completed"] = False
        state["completed_at"] = None
        state["last_error"] = None
        await self._persist(state)
        return True

    async def run_forever(self) -> None:
        self.owner._execution_regrade_ready_v39 = False
        while not self._stop.is_set():
            try:
                progressed = await self.learn_cycle()
                if not progressed and getattr(self.owner, "_execution_regrade_ready_v39", False):
                    try:
                        await asyncio.wait_for(self._stop.wait(), timeout=60.0)
                    except asyncio.TimeoutError:
                        pass
                    continue
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                core.logger.exception("Live Trader historical execution regrade failed")
                state = await self._state()
                state["last_error"] = str(exc)[:500]
                try:
                    await self._persist(state)
                except Exception:
                    pass
                self.owner._execution_regrade_ready_v39 = False
            try:
                await asyncio.wait_for(self._stop.wait(), timeout=REGRADER_IDLE_SECONDS)
            except asyncio.TimeoutError:
                pass


async def _run_forever_v39(self: core.LiveTrader) -> None:
    regrader = getattr(self, "_execution_regrader_v39", None)
    if regrader is None:
        regrader = HistoricalExecutionRegrader(self)
        self._execution_regrader_v39 = regrader
    task = asyncio.create_task(regrader.run_forever(), name="eve-live-trader-execution-regrader")
    try:
        await _current_run_forever(self)
    finally:
        await regrader.stop()
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass


def _regrade_status(self: core.LiveTrader) -> dict[str, Any]:
    regrader = getattr(self, "_execution_regrader_v39", None)
    state = dict(getattr(regrader, "last_state", {}) or {}) if regrader is not None else {}
    return {
        "version": REGRADER_VERSION,
        "execution_schema": EXECUTION_SCHEMA,
        "running": regrader is not None and not regrader._stop.is_set(),
        "ready": getattr(self, "_execution_regrade_ready_v39", False) is True,
        **state,
    }


def _runtime_status_v39(self: core.LiveTrader) -> dict[str, Any]:
    status = dict(_current_runtime_status(self))
    status["execution_integrity"] = _regrade_status(self)
    status["causal_execution_schema"] = EXECUTION_SCHEMA
    status["locked_campaign_followthrough_is_not_new_learning"] = True
    return status


async def _learning_summary_v39(self: core.LiveTrader) -> dict[str, Any]:
    summary = dict(await _current_learning_summary(self))
    summary["execution_integrity"] = _regrade_status(self)
    summary["execution_learning_policy"] = (
        "Only the publication of a locked campaign may create a forward decision sample. Pending/active follow-through and terminal display states are not new decisions. "
        "Causal M1 scoring now enforces the published pre-entry invalidation before entry, and Historical Academy evidence is being regraded under the same rule."
    )
    return summary


# Install the corrected shared path semantics first so both future forward outcomes
# and every new Historical Academy/challenger score use the same causal rule.
v2._trade_path_result = _trade_path_result_v39

core.LiveTrader._maybe_record_opinion = _record_v39  # type: ignore[method-assign]
core.LiveTrader._trade_idea = _trade_idea_v39  # type: ignore[method-assign]
core.LiveTrader.run_forever = _run_forever_v39  # type: ignore[method-assign]
core.LiveTrader.runtime_status = _runtime_status_v39  # type: ignore[method-assign]
core.LiveTrader.learning_summary = _learning_summary_v39  # type: ignore[method-assign]

# Preserve established compatibility identity contracts while pointing them at the
# newest audited runtime wrappers.
hardening._record_v26 = _record_v39
academy._record_v29 = _record_v39
lock._trade_idea_v28 = _trade_idea_v39
hardening._run_forever_v26 = _run_forever_v39
runtime._run_forever_v30 = _run_forever_v39
