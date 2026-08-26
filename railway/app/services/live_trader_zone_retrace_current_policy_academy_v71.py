from __future__ import annotations

import asyncio
import hashlib
from datetime import datetime, timedelta, timezone
from typing import Any

from app.services import live_trader as core
from app.services import live_trader_audit_hardening_v26 as hardening
from app.services import live_trader_clear_bias_gate_v45 as clear_gate
from app.services import live_trader_execution_integrity_v39 as integrity
from app.services import live_trader_historical_learning_v29 as academy
from app.services import live_trader_london_session_gate_v46 as session_gate
from app.services import live_trader_zone_retrace_integrity_v64 as v64
from app.services import live_trader_zone_retrace_live_policy_replay_v68 as v68
from app.services import live_trader_zone_retrace_replay_diagnostics_v70 as v70  # noqa: F401 -- patches v68 replay funnel
from app.services import live_trader_zone_retrace_specialist_v58 as v58
from app.services import live_trader_zone_target_guard_v49 as v49
from app.services.repository import SourceRepository

ACADEMY_VERSION = "eve-live-zone-retrace-current-policy-academy-v71"
ENTRY_POLICY = "current_v43_v45_bias_then_ranked_zone_retrace_then_m5_m15_confirmation_market"
SCAN_BATCH_ROWS = 180
IDLE_SECONDS = 0.75
CAUGHT_UP_SECONDS = 300.0
MIN_SCORABLE_COVERAGE = 0.95
MIN_PROMOTION_OPPORTUNITIES = 50
MIN_PROMOTION_TRIGGERED = 30
MIN_PROMOTION_EXPECTANCY_R = 0.10
MAX_ZONE_DISTANCE_ATR = 1.8
MIN_ZONE_QUALITY = 58

_current_run_forever = core.LiveTrader.run_forever
_current_learning_summary = core.LiveTrader.learning_summary
_current_runtime_status = core.LiveTrader.runtime_status
_prior_load_specialist_row = v64._load_specialist_row
_prior_audited_specialist = v64._audited_specialist


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


def _decision_time(row: dict[str, Any]) -> datetime | None:
    context = dict(row.get("mtf_context") or {})
    decision = _parse_time(context.get("decision_time"))
    if decision is not None:
        return decision
    candle = _parse_time(row.get("candle_time"))
    return candle + timedelta(minutes=5) if candle is not None else None


def _opportunity_key(symbol: str, observed: datetime, side: str) -> str:
    raw = f"{symbol}|{observed.isoformat()}|{side}|{ACADEMY_VERSION}"
    return hashlib.sha1(raw.encode()).hexdigest()


def _matching_zone(zones: dict[str, list[dict[str, Any]]], overall: str) -> dict[str, Any] | None:
    items = list(zones.get("demand" if overall == "bullish" else "supply") or [])
    return dict(items[0]) if items else None


def _live_policy_evidence(state: dict[str, Any]) -> dict[str, Any]:
    scorable = int(_num(state.get("scorable_opportunities")))
    triggered = int(_num(state.get("triggered")))
    total_r = _num(state.get("total_r"))
    return {
        "opportunities": scorable,
        "triggered": triggered,
        "scored": scorable,
        "wins": int(_num(state.get("wins"))),
        "losses": int(_num(state.get("losses"))),
        "breakeven": int(_num(state.get("breakeven"))),
        "total_r": round(total_r, 3),
        "expectancy_per_opportunity_r": state.get("expectancy_per_opportunity_r"),
        "expectancy_per_triggered_r": state.get("expectancy_per_triggered_r"),
        "trigger_rate": state.get("trigger_rate"),
        "entry_policy": ENTRY_POLICY,
        "target_cap_r": v68.LIVE_TARGET_CAP_R,
        "academy_version": ACADEMY_VERSION,
    }


def _current_policy_contract(payload: dict[str, Any]) -> dict[str, Any]:
    specialist = dict(_prior_audited_specialist(payload or {}))
    state = dict((payload or {}).get("current_policy_academy") or specialist.get("current_policy_academy") or {})

    # v68 remains an important backwards-compatibility audit, but the old 173
    # episodes were selected under an older setup/bias contract. Never let that
    # compatibility sample promote today's live execution.
    specialist["compatibility_replay"] = dict(specialist.get("live_policy_replay") or {})
    specialist["compatibility_replay_authoritative_for_promotion"] = False
    specialist["live_promotion_authority"] = ACADEMY_VERSION
    specialist["current_policy_academy_version"] = ACADEMY_VERSION

    if not state:
        specialist.update(
            {
                "current_policy_academy": {},
                "live_policy_execution_evidence": {},
                "live_policy_expectancy_verified": False,
                "live_policy_entry_geometry_verified": False,
                "live_promoted_execution": None,
                "promoted_execution": None,
                "promotion_blocked": True,
                "promotion_block_reason": "Current-policy academy has not produced its first persisted scan state yet.",
                "phase": "CURRENT-POLICY ACADEMY STARTING",
                "status": "current_policy_academy_starting",
                "live_strategy_edge_proven": False,
            }
        )
        return specialist

    opportunities = int(_num(state.get("opportunities_found")))
    scorable = int(_num(state.get("scorable_opportunities")))
    coverage = scorable / opportunities if opportunities else 0.0
    caught_up = bool(state.get("caught_up"))
    verified = bool(caught_up and opportunities > 0 and coverage >= MIN_SCORABLE_COVERAGE)
    promoted = bool(state.get("promoted")) and verified
    evidence = _live_policy_evidence(state)

    specialist.update(
        {
            "current_policy_academy": state,
            "live_policy_execution_evidence": {"market_after_zone_confirmation": evidence},
            "live_policy_expectancy_verified": verified,
            "live_policy_entry_geometry_verified": verified,
            "live_policy_scorable_coverage": round(coverage, 4),
            "live_policy_rescore_status": state.get("status") or "scanning",
            "live_promoted_execution": "market_after_zone_confirmation" if promoted else None,
            "promoted_execution": "market_after_zone_confirmation" if promoted else None,
            "promotion_blocked": not promoted,
            "promotion_block_reason": (
                None
                if promoted
                else "Current-policy archive scan is complete, but the exact live entry has not met the promotion thresholds."
                if verified
                else "Current-policy academy is still scanning the M1-covered archive or has not yet reached 95% scorable opportunity coverage."
            ),
            "phase": (
                "LIVE ENTRY POLICY PROMOTED"
                if promoted
                else "CURRENT-POLICY ACADEMY VERIFIED"
                if verified
                else "CURRENT-POLICY ACADEMY SCANNING"
            ),
            "status": (
                "mature_candidate"
                if promoted
                else "current_policy_verified_no_promotion"
                if verified
                else "current_policy_academy_scanning"
            ),
            "live_entry_execution_edge_supported": promoted,
            "live_policy_historical_news_gate_replayed": False,
            "live_policy_historical_news_caveat": (
                "The six-year archive does not contain a complete red-folder calendar. The production news gate remains an additional fail-closed filter and is not credited as historical edge."
            ),
            "live_strategy_edge_proven": False,
        }
    )
    return specialist


async def _load_current_policy_state(self: core.LiveTrader) -> dict[str, Any]:
    try:
        rows = await self.repo.client.get(
            "live_trader_zone_retrace_current_policy_state",
            params={"select": "*", "symbol": f"eq.{self.symbol}", "limit": "1"},
        )
        return dict(rows[0] or {}) if rows else {}
    except Exception:
        return {}


async def _load_specialist_row_v71(self: core.LiveTrader) -> dict[str, Any]:
    specialist = dict(await _prior_load_specialist_row(self) or {})
    state = await _load_current_policy_state(self)
    if state:
        specialist["current_policy_academy"] = state
    return specialist


class CurrentPolicyZoneRetraceAcademy(v68.ZoneRetraceLivePolicyReplayer):
    """Discover and score opportunities under today's exact live policy.

    The compatibility replay asks whether old pullback episodes survive today's
    gates. This academy does the reverse and more important test: it walks the M5
    archive causally, lets the current v43/v45 bias and current v62/v63 zone stack
    decide when a live retracement watch would exist, then follows that watch on
    source M1 using the same v58 confirmation and v49 target policy.
    """

    def __init__(self, owner: core.LiveTrader) -> None:
        super().__init__(owner)
        self.owner = owner
        self.engine = core.LiveTrader(owner.settings, owner.repo)
        self.source = SourceRepository(owner.settings)
        self._stop = asyncio.Event()
        self.last_state: dict[str, Any] = {}
        self.last_error: str | None = None
        self.rows_scanned_runtime = 0
        self.opportunities_runtime = 0

    async def _state(self) -> dict[str, Any]:
        rows = await self.repo.client.get(
            "live_trader_zone_retrace_current_policy_state",
            params={"select": "*", "symbol": f"eq.{self.symbol}", "limit": "1"},
        )
        return dict(rows[0] or {}) if rows else {}

    async def _m1_coverage_start(self) -> datetime | None:
        cached = getattr(self, "_current_policy_m1_coverage_start_v71", None)
        if cached is not None:
            return cached
        rows = await self.source.client.get(
            "market_candles",
            params={
                "select": "candle_time",
                "symbol": f"eq.{self.symbol}",
                "interval": "eq.1min",
                "order": "candle_time.asc",
                "limit": "1",
            },
        )
        start = _parse_time((rows[0] or {}).get("candle_time")) if rows else None
        self._current_policy_m1_coverage_start_v71 = start
        return start

    async def _scan_window(self, cursor: datetime) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        select = (
            "candle_time,open,high,low,close,atr_14,session,regime,direction,"
            "return_12_pct,return_48_pct,trend_12_atr,trend_48_atr,mtf_context,outcome_complete"
        )
        warm = await self.repo.client.get(
            "m5_research_snapshots",
            params={
                "select": select,
                "symbol": f"eq.{self.symbol}",
                "outcome_complete": "eq.true",
                "candle_time": f"lte.{cursor.isoformat()}",
                "order": "candle_time.desc",
                "limit": "720",
            },
        )
        warm.reverse()
        batch = await self.repo.client.get(
            "m5_research_snapshots",
            params={
                "select": select,
                "symbol": f"eq.{self.symbol}",
                "outcome_complete": "eq.true",
                "candle_time": f"gt.{cursor.isoformat()}",
                "order": "candle_time.asc",
                "limit": str(SCAN_BATCH_ROWS),
            },
        )
        return list(warm), list(batch)

    def _opportunity(
        self,
        history: list[dict[str, Any]],
        row: dict[str, Any],
        decision: datetime,
    ) -> dict[str, Any] | None:
        if not academy.broker_market_open(decision) or not session_gate._inside_london_window(decision):
            return None
        self.engine._rows = list(history[-720:])
        bias, _ = self.engine._bias(row)
        liquidity = self.engine._liquidity(history)
        clear, assessment = clear_gate._clear_bias_assessment(bias, liquidity)
        if not clear:
            return None
        overall = str(bias.get("overall") or "neutral").lower()
        if overall not in {"bullish", "bearish"}:
            return None
        price = _num(row.get("close"))
        atr = max(_num(row.get("atr_14")), 0.01)
        if price <= 0:
            return None
        zones = self.engine._zone_candidates(history, price, bias)
        zone = _matching_zone(zones, overall)
        if not zone:
            return None
        if _num(zone.get("quality")) < MIN_ZONE_QUALITY:
            return None
        if _num(zone.get("distance_atr"), 999.0) > MAX_ZONE_DISTANCE_ATR:
            return None
        side = "BUY" if overall == "bullish" else "SELL"
        return {
            "observed_at": decision,
            "side": side,
            "bias": overall,
            "session": str(row.get("session") or "unknown"),
            "start_price": round(price, 3),
            "atr": round(atr, 3),
            "source_zone": dict(zone),
            "clear_bias_gate": assessment,
        }

    async def _replay_current_opportunity(
        self,
        opportunity: dict[str, Any],
    ) -> dict[str, Any]:
        observed = opportunity["observed_at"]
        expected_bias = str(opportunity.get("bias") or "")
        horizon_minutes = max(1, int(self.settings.live_trader_learning_horizon_minutes))
        search_end = observed + timedelta(minutes=horizon_minutes)
        source_end = search_end + timedelta(minutes=horizon_minutes + 5)
        warm, future = await self._m5_window(observed, search_end)
        m1_rows = await self._m1_window(observed, source_end)
        search_path = hardening._causal_m1_path(m1_rows, observed, search_end)

        base = {
            "opportunity_key": _opportunity_key(self.symbol, observed, str(opportunity.get("side") or "")),
            "independence_key": _opportunity_key(self.symbol, observed, str(opportunity.get("side") or "")),
            "symbol": self.symbol,
            "observed_at": observed.isoformat(),
            "session": opportunity.get("session"),
            "bias": expected_bias,
            "start_price": opportunity.get("start_price"),
            "atr": opportunity.get("atr"),
            "source_zone": opportunity.get("source_zone"),
            "clear_bias_gate": opportunity.get("clear_bias_gate"),
            "academy_version": ACADEMY_VERSION,
        }

        if not v68._path_complete(search_path):
            return {
                **base,
                "entry_at": None,
                "status": "unscorable_search_path",
                "path_complete": False,
                "trade_outcome": None,
                "realised_r": None,
                "learning_success": None,
                "details": {
                    "entry_policy": ENTRY_POLICY,
                    "search_path": {key: search_path.get(key) for key in ("initial_gap_seconds", "gap_count", "endpoint_lag_seconds")},
                },
                "release_at": search_end,
            }

        self._last_entry_search_diagnostics_v70 = {}
        entry = self._find_entry(
            expected_bias=expected_bias,
            observed=observed,
            search_end=search_end,
            warm=warm,
            future=future,
            m1_rows=list(search_path.get("bars") or m1_rows),
        )
        diagnostics = dict(getattr(self, "_last_entry_search_diagnostics_v70", {}) or {})

        if entry is None:
            return {
                **base,
                "entry_at": None,
                "status": "no_entry",
                "path_complete": True,
                "trade_outcome": "no_live_policy_entry",
                "realised_r": 0.0,
                "learning_success": None,
                "details": {
                    "entry_policy": ENTRY_POLICY,
                    "entry_search_diagnostics": diagnostics,
                    "historical_news_gate_replayed": False,
                },
                "release_at": search_end,
            }

        entry_at = entry["entry_at"]
        outcome_end = entry_at + timedelta(minutes=horizon_minutes)
        outcome_path = hardening._causal_m1_path(m1_rows, entry_at, outcome_end)
        entry_base = {
            **base,
            "entry_at": entry_at.isoformat(),
            "side": entry.get("side"),
            "entry": entry.get("entry"),
            "stop": entry.get("stop"),
            "target": entry.get("target"),
            "target_r": entry.get("target_r"),
            "source_zone": entry.get("source_zone") or opportunity.get("source_zone"),
            "clear_bias_gate": entry.get("clear_bias_gate") or opportunity.get("clear_bias_gate"),
            "confirmation": entry.get("confirmation"),
        }
        if not v68._path_complete(outcome_path):
            return {
                **entry_base,
                "status": "unscorable_outcome_path",
                "path_complete": False,
                "trade_outcome": None,
                "realised_r": None,
                "learning_success": None,
                "details": {
                    "entry_policy": ENTRY_POLICY,
                    "entry_search_diagnostics": diagnostics,
                    "outcome_path": {key: outcome_path.get(key) for key in ("initial_gap_seconds", "gap_count", "endpoint_lag_seconds")},
                },
                "release_at": outcome_end,
            }

        trade = dict(entry.get("trade") or {})
        # Re-apply the production target cap at the final scoring point so no
        # future upstream target-policy change can silently bypass the academy.
        trade = v49._apply_target_cap(trade)
        result = integrity._trade_path_result_v39(
            trade,
            list(outcome_path.get("bars") or []),
            float(outcome_path.get("endpoint_price")),
        )
        return {
            **entry_base,
            "target": trade.get("target"),
            "target_r": round(abs(_num(trade.get("target")) - _num(trade.get("entry"))) / max(abs(_num(trade.get("entry")) - _num(trade.get("stop"))), 0.000001), 3),
            "status": "scored",
            "path_complete": True,
            "trade_outcome": result.get("trade_outcome"),
            "realised_r": result.get("realised_r"),
            "learning_success": result.get("learning_success"),
            "details": {
                "entry_policy": ENTRY_POLICY,
                "entry_search_diagnostics": diagnostics,
                "target_policy": trade.get("target_policy"),
                "historical_news_gate_replayed": False,
                "same_entry_minute_policy": "stop_first",
            },
            "release_at": outcome_end,
        }

    async def _store_opportunity(self, result: dict[str, Any]) -> None:
        stored = {key: value for key, value in result.items() if key != "release_at"}
        stored["updated_at"] = core.utc_now().isoformat()
        await self.repo.client.upsert(
            "live_trader_zone_retrace_current_policy_opportunities",
            stored,
            on_conflict="opportunity_key",
            return_rows=False,
        )

    async def _aggregate(self, *, cursor: datetime | None, rows_scanned: int, coverage_start: datetime | None, caught_up: bool) -> dict[str, Any]:
        rows = await self.repo.client.get(
            "live_trader_zone_retrace_current_policy_opportunities",
            params={
                "select": "status,entry_at,path_complete,realised_r,learning_success",
                "symbol": f"eq.{self.symbol}",
                "academy_version": f"eq.{ACADEMY_VERSION}",
                "limit": "5000",
            },
        )
        opportunities = len(rows)
        scorable_rows = [row for row in rows if bool(row.get("path_complete")) and str(row.get("status") or "") in {"scored", "no_entry"}]
        scorable = len(scorable_rows)
        unscorable = opportunities - scorable
        triggered_rows = [row for row in scorable_rows if row.get("entry_at")]
        triggered = len(triggered_rows)
        total_r = sum(_num(row.get("realised_r")) for row in scorable_rows if row.get("realised_r") is not None)
        wins = sum(1 for row in triggered_rows if _num(row.get("realised_r")) > 0)
        losses = sum(1 for row in triggered_rows if _num(row.get("realised_r")) < 0)
        breakeven = sum(1 for row in triggered_rows if row.get("realised_r") is not None and _num(row.get("realised_r")) == 0)
        expectancy_opportunity = total_r / scorable if scorable else None
        expectancy_triggered = total_r / triggered if triggered else None
        trigger_rate = triggered / scorable if scorable else None
        coverage = scorable / opportunities if opportunities else 0.0
        promoted = bool(
            caught_up
            and opportunities > 0
            and coverage >= MIN_SCORABLE_COVERAGE
            and scorable >= MIN_PROMOTION_OPPORTUNITIES
            and triggered >= MIN_PROMOTION_TRIGGERED
            and expectancy_opportunity is not None
            and expectancy_opportunity > MIN_PROMOTION_EXPECTANCY_R
        )
        status = "caught_up_promoted" if caught_up and promoted else "caught_up_not_promoted" if caught_up else "scanning"
        previous = await self._state()
        payload = {
            "symbol": self.symbol,
            "academy_version": ACADEMY_VERSION,
            "status": status,
            "cursor_time": cursor.isoformat() if cursor is not None else previous.get("cursor_time"),
            "m1_coverage_start": coverage_start.isoformat() if coverage_start is not None else previous.get("m1_coverage_start"),
            "rows_scanned": int(_num(previous.get("rows_scanned"))) + max(0, rows_scanned),
            "opportunities_found": opportunities,
            "scorable_opportunities": scorable,
            "unscorable_opportunities": unscorable,
            "triggered": triggered,
            "wins": wins,
            "losses": losses,
            "breakeven": breakeven,
            "total_r": round(total_r, 3),
            "expectancy_per_opportunity_r": round(expectancy_opportunity, 4) if expectancy_opportunity is not None else None,
            "expectancy_per_triggered_r": round(expectancy_triggered, 4) if expectancy_triggered is not None else None,
            "trigger_rate": round(trigger_rate, 4) if trigger_rate is not None else None,
            "caught_up": caught_up,
            "promoted": promoted,
            "last_cycle_at": core.utc_now().isoformat(),
            "last_error": self.last_error,
            "policy": {
                "opportunity_definition": "current v43/v45 clear bias + current preferred matching zone quality >=58 and <=1.8 ATR + London publication window",
                "entry_policy": ENTRY_POLICY,
                "target_cap_r": v68.LIVE_TARGET_CAP_R,
                "evaluation_horizon_minutes": int(self.settings.live_trader_learning_horizon_minutes),
                "independence_policy": "non-overlapping watch/outcome windows; scanner cursor advances through each completed opportunity lifecycle",
                "minimum_scorable_coverage": MIN_SCORABLE_COVERAGE,
                "promotion_min_opportunities": MIN_PROMOTION_OPPORTUNITIES,
                "promotion_min_triggered": MIN_PROMOTION_TRIGGERED,
                "promotion_min_expectancy_r": MIN_PROMOTION_EXPECTANCY_R,
                "historical_news_gate_replayed": False,
            },
            "updated_at": core.utc_now().isoformat(),
        }
        await self.repo.client.upsert(
            "live_trader_zone_retrace_current_policy_state",
            payload,
            on_conflict="symbol",
            return_rows=False,
        )
        self.last_state = dict(payload)
        specialist = dict(getattr(self.owner, "_zone_retrace_learning_v58", {}) or {})
        specialist["current_policy_academy"] = dict(payload)
        self.owner._zone_retrace_learning_v58 = specialist
        return payload

    async def run_cycle(self) -> bool:
        state = await self._state()
        coverage_start = await self._m1_coverage_start()
        if coverage_start is None:
            raise RuntimeError("Current-policy academy cannot start because source M1 coverage was not found.")
        cursor = _parse_time(state.get("cursor_time")) or (coverage_start - timedelta(minutes=5))
        warm, batch = await self._scan_window(cursor)
        if not batch:
            await self._aggregate(cursor=cursor, rows_scanned=0, coverage_start=coverage_start, caught_up=True)
            return False

        rolling = list(warm)
        seen = {str(row.get("candle_time") or "") for row in rolling}
        examined = 0
        next_cursor = cursor
        found_result: dict[str, Any] | None = None

        for row in batch:
            stamp = _parse_time(row.get("candle_time"))
            if stamp is None:
                continue
            examined += 1
            if str(row.get("candle_time") or "") not in seen:
                rolling.append(row)
                seen.add(str(row.get("candle_time") or ""))
            next_cursor = stamp
            decision = _decision_time(row)
            if decision is None or decision < coverage_start:
                continue
            opportunity = self._opportunity(list(rolling[-720:]), row, decision)
            if opportunity is None:
                continue

            found_result = await self._replay_current_opportunity(opportunity)
            await self._store_opportunity(found_result)
            self.opportunities_runtime += 1
            release_at = found_result.get("release_at")
            if isinstance(release_at, datetime):
                next_cursor = max(next_cursor, release_at)
            break

        self.rows_scanned_runtime += examined
        caught_up = bool(found_result is None and len(batch) < SCAN_BATCH_ROWS)
        await self._aggregate(
            cursor=next_cursor,
            rows_scanned=examined,
            coverage_start=coverage_start,
            caught_up=caught_up,
        )
        return True

    async def run_forever(self) -> None:
        while not self._stop.is_set():
            try:
                progressed = await self.run_cycle()
                self.last_error = None
                delay = IDLE_SECONDS if progressed else CAUGHT_UP_SECONDS
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                self.last_error = str(exc)[:500]
                core.logger.exception("Current-policy Zone Retracement Academy failed")
                try:
                    state = await self._state()
                    coverage = await self._m1_coverage_start()
                    await self._aggregate(
                        cursor=_parse_time(state.get("cursor_time")),
                        rows_scanned=0,
                        coverage_start=coverage,
                        caught_up=False,
                    )
                except Exception:
                    pass
                delay = 15.0
            try:
                await asyncio.wait_for(self._stop.wait(), timeout=delay)
            except asyncio.TimeoutError:
                pass


async def _run_forever_v71(self: core.LiveTrader) -> None:
    worker = getattr(self, "_zone_retrace_current_policy_academy_v71", None)
    if worker is None:
        worker = CurrentPolicyZoneRetraceAcademy(self)
        self._zone_retrace_current_policy_academy_v71 = worker
    task = asyncio.create_task(worker.run_forever(), name="eve-zone-retrace-current-policy-academy")
    try:
        await _current_run_forever(self)
    finally:
        await worker.stop()
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass


async def _learning_summary_v71(self: core.LiveTrader) -> dict[str, Any]:
    summary = dict(await _current_learning_summary(self))
    state = await _load_current_policy_state(self)
    specialist = dict(summary.get("zone_retrace_specialist") or getattr(self, "_zone_retrace_learning_v58", {}) or {})
    if state:
        specialist["current_policy_academy"] = state
    if specialist:
        specialist = _current_policy_contract(specialist)
        summary["zone_retrace_specialist"] = specialist
    summary["zone_retrace_current_policy_academy"] = state or {
        "academy_version": ACADEMY_VERSION,
        "status": "waiting_for_first_scan",
    }
    return summary


def _runtime_status_v71(self: core.LiveTrader) -> dict[str, Any]:
    status = dict(_current_runtime_status(self))
    worker = getattr(self, "_zone_retrace_current_policy_academy_v71", None)
    state = dict(getattr(worker, "last_state", {}) or {}) if worker is not None else {}
    status.update(
        {
            "zone_retrace_current_policy_academy_version": ACADEMY_VERSION,
            "zone_retrace_current_policy_academy_running": worker is not None and not worker._stop.is_set(),
            "zone_retrace_current_policy_academy_status": state.get("status"),
            "zone_retrace_current_policy_rows_scanned": state.get("rows_scanned"),
            "zone_retrace_current_policy_opportunities": state.get("opportunities_found"),
            "zone_retrace_current_policy_triggered": state.get("triggered"),
            "zone_retrace_current_policy_promoted": state.get("promoted"),
            "zone_retrace_live_promotion_authority": ACADEMY_VERSION,
            "zone_retrace_compatibility_replay_authoritative": False,
        }
    )
    return status


v64._load_specialist_row = _load_specialist_row_v71
v64._audited_specialist = _current_policy_contract
core.LiveTrader.run_forever = _run_forever_v71  # type: ignore[method-assign]
core.LiveTrader.learning_summary = _learning_summary_v71  # type: ignore[method-assign]
core.LiveTrader.runtime_status = _runtime_status_v71  # type: ignore[method-assign]
