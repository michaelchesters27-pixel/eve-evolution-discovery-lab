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
from app.services import live_trader_zone_retrace_evidence_contract_v67 as v67
from app.services import live_trader_zone_retrace_integrity_v64 as v64
from app.services import live_trader_zone_retrace_specialist_v58 as v58
from app.services import live_trader_zone_target_guard_v49 as v49
from app.services.repository import SourceRepository

REPLAY_VERSION = "eve-live-zone-retrace-live-policy-replay-v68"
ENTRY_POLICY = "ranked_zone_retrace_then_m5_m15_confirmation_then_market"
ENTRY_RESOLUTION = "causal_m1_open_or_touch_boundary"
LIVE_TARGET_CAP_R = 1.5
REPLAY_BATCH_SIZE = 4
REPLAY_IDLE_SECONDS = 0.75
MIN_SCORABLE_COVERAGE = 0.95
MIN_PROMOTION_OPPORTUNITIES = 50
MIN_PROMOTION_TRIGGERED = 30
MIN_PROMOTION_EXPECTANCY_R = 0.10

_current_run_forever = core.LiveTrader.run_forever
_current_learning_summary = core.LiveTrader.learning_summary
_current_runtime_status = core.LiveTrader.runtime_status
_prior_load_specialist_row = v64._load_specialist_row


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


def _eligible_episode(row: dict[str, Any]) -> bool:
    market_state = dict(row.get("market_state") or {})
    descriptor = dict(market_state.get("setup_family_descriptor") or {})
    return (
        bool(row.get("path_complete"))
        and str(descriptor.get("bias") or "").lower() in {"bullish", "bearish"}
        and str(descriptor.get("location_relation") or "").lower() in {"preferred", "at_zone"}
        and str(descriptor.get("zone_quality") or "").lower() in {"good", "high"}
        and str(descriptor.get("execution_class") or "").lower() == "pullback"
        and bool(str(row.get("historical_episode_key") or "").strip())
        and bool(str(row.get("independence_key") or "").strip())
    )


def _path_complete(path: dict[str, Any]) -> bool:
    return bool(
        path.get("endpoint_price") is not None
        and path.get("endpoint_time") is not None
        and path.get("endpoint_lag_seconds") is not None
        and float(path.get("endpoint_lag_seconds") or 999999.0) <= hardening.MAX_ENDPOINT_LAG_SECONDS
        and path.get("initial_gap_seconds") is not None
        and float(path.get("initial_gap_seconds") or 999999.0) <= 1.0
        and int(path.get("gap_count") or 0) == 0
    )


def _replay_key(episode_key: str) -> str:
    raw = f"{episode_key}|{REPLAY_VERSION}"
    return hashlib.sha1(raw.encode()).hexdigest()


def _source_zone_for_bias(zones: dict[str, list[dict[str, Any]]], overall: str) -> dict[str, Any] | None:
    items = list(zones.get("demand" if overall == "bullish" else "supply") or [])
    return dict(items[0]) if items else None


def _touch_probe(bar: dict[str, Any], zone: dict[str, Any]) -> tuple[float | None, str | None]:
    low = _num(zone.get("low"))
    high = _num(zone.get("high"))
    open_price = _num(bar.get("open"))
    bar_low = _num(bar.get("low"))
    bar_high = _num(bar.get("high"))
    if low <= 0 or high <= 0 or open_price <= 0:
        return None, None
    if low <= open_price <= high:
        return open_price, "m1_open_inside_zone"
    if bar_low <= high and bar_high >= low:
        if open_price > high:
            return high, "m1_touch_from_above"
        if open_price < low:
            return low, "m1_touch_from_below"
        return open_price, "m1_zone_intersection"
    return None, None


def _live_policy_evidence_from_state(state: dict[str, Any]) -> dict[str, Any]:
    scorable = int(_num(state.get("scorable_episodes")))
    triggered = int(_num(state.get("triggered")))
    wins = int(_num(state.get("wins")))
    losses = int(_num(state.get("losses")))
    breakeven = int(_num(state.get("breakeven")))
    total_r = _num(state.get("total_r"))
    return {
        "opportunities": scorable,
        "triggered": triggered,
        "scored": scorable,
        "wins": wins,
        "losses": losses,
        "breakeven": breakeven,
        "total_r": round(total_r, 3),
        "expectancy_per_opportunity_r": state.get("expectancy_per_opportunity_r"),
        "expectancy_per_triggered_r": state.get("expectancy_per_triggered_r"),
        "trigger_rate": state.get("trigger_rate"),
        "entry_policy": ENTRY_POLICY,
        "entry_resolution": ENTRY_RESOLUTION,
        "target_cap_r": LIVE_TARGET_CAP_R,
        "evaluation_horizon_minutes": state.get("policy", {}).get("evaluation_horizon_minutes") if isinstance(state.get("policy"), dict) else None,
    }


def _evidence_contract_v68(payload: dict[str, Any]) -> dict[str, Any]:
    specialist = dict(v67._evidence_contract(payload or {}))
    replay = dict((payload or {}).get("live_policy_replay") or specialist.get("live_policy_replay") or {})
    if not replay:
        specialist["live_policy_rescore_version"] = REPLAY_VERSION
        specialist["live_policy_rescore_status"] = "waiting_for_replay_worker"
        return specialist

    eligible = int(_num(replay.get("eligible_episodes")))
    scorable = int(_num(replay.get("scorable_episodes")))
    coverage = (scorable / eligible) if eligible else 0.0
    completed = bool(replay.get("completed"))
    coverage_ok = bool(completed and eligible > 0 and coverage >= MIN_SCORABLE_COVERAGE)
    promoted = bool(replay.get("promoted")) and coverage_ok
    evidence = _live_policy_evidence_from_state(replay)

    specialist.update(
        {
            "live_policy_replay": replay,
            "live_policy_rescore_version": REPLAY_VERSION,
            "live_policy_rescore_status": replay.get("status") or "running",
            "live_policy_execution_evidence": {"market_after_zone_confirmation": evidence},
            "live_policy_expectancy_verified": coverage_ok,
            "live_policy_entry_geometry_verified": coverage_ok,
            "live_policy_scorable_coverage": round(coverage, 4),
            "live_policy_historical_news_gate_replayed": False,
            "live_policy_historical_news_caveat": (
                "The historical archive does not contain a six-year red-folder calendar. The live red-folder gate remains an additional fail-closed publication filter and cannot be credited as historical edge."
            ),
            "live_promoted_execution": "market_after_zone_confirmation" if promoted else None,
            "promoted_execution": "market_after_zone_confirmation" if promoted else None,
            "promotion_blocked": not promoted,
            "phase": (
                "LIVE ENTRY POLICY PROMOTED"
                if promoted
                else "LIVE ENTRY POLICY VERIFIED"
                if coverage_ok
                else "LIVE POLICY RESCORE RUNNING"
            ),
            "status": (
                "mature_candidate"
                if promoted
                else "live_entry_policy_verified_no_promotion"
                if coverage_ok
                else "live_policy_rescore_running"
            ),
            "promotion_block_reason": (
                None
                if promoted
                else "Exact live entry-policy replay is complete but has not met the promotion thresholds."
                if coverage_ok
                else "Exact live entry-policy replay has not yet reached at least 95% scorable coverage."
            ),
            "live_entry_execution_edge_supported": promoted,
            # Historical entry evidence is not permission to claim the whole live
            # strategy has an edge because the red-folder filter has no six-year
            # historical archive and forward campaign evidence is still separate.
            "live_strategy_edge_proven": False,
        }
    )
    return specialist


async def _load_replay_state(self: core.LiveTrader) -> dict[str, Any]:
    try:
        rows = await self.repo.client.get(
            "live_trader_zone_retrace_live_policy_state",
            params={"select": "*", "symbol": f"eq.{self.symbol}", "limit": "1"},
        )
        return dict(rows[0] or {}) if rows else {}
    except Exception:
        return {}


async def _load_specialist_row_v68(self: core.LiveTrader) -> dict[str, Any]:
    specialist = dict(await _prior_load_specialist_row(self) or {})
    replay = await _load_replay_state(self)
    if replay:
        specialist["live_policy_replay"] = replay
    return specialist


class ZoneRetraceLivePolicyReplayer:
    """Causally re-score the actual live zone-confirmation entry geometry.

    Historical M5 closes rebuild the same structural bias and ranked MTF zone map.
    Source M1 is then used as the finest available historical execution proxy: a
    trade can publish at an M1 open already inside the zone or at the first zone
    boundary touched during that minute. The entry minute is scored stop-first,
    which is deliberately conservative when intraminute ordering is unknowable.
    """

    def __init__(self, owner: core.LiveTrader) -> None:
        self.owner = owner
        self.settings = owner.settings
        self.repo = owner.repo
        self.symbol = owner.symbol
        self.source = SourceRepository(owner.settings)
        self.engine = core.LiveTrader(owner.settings, owner.repo)
        self._stop = asyncio.Event()
        self.last_error: str | None = None
        self.last_state: dict[str, Any] = {}

    async def stop(self) -> None:
        self._stop.set()

    async def _eligible_rows(self) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        for page in range(v58.HISTORICAL_PAGES):
            offset = page * v58.HISTORICAL_PAGE_SIZE
            batch = await self.repo.client.get(
                "live_trader_historical_learning",
                params={
                    "select": "historical_episode_key,observed_at,independence_key,market_state,path_complete",
                    "symbol": f"eq.{self.symbol}",
                    "path_complete": "eq.true",
                    "order": "observed_at.desc",
                    "limit": str(v58.HISTORICAL_PAGE_SIZE),
                    "offset": str(offset),
                },
            )
            rows.extend(batch)
            if len(batch) < v58.HISTORICAL_PAGE_SIZE:
                break

        independent: dict[str, dict[str, Any]] = {}
        for row in rows:
            if not _eligible_episode(row):
                continue
            key = str(row.get("independence_key") or "")
            if key and key not in independent:
                independent[key] = dict(row)
        return list(independent.values())

    async def _processed_independence(self) -> set[str]:
        rows = await self.repo.client.get(
            "live_trader_zone_retrace_live_policy_replays",
            params={
                "select": "independence_key",
                "symbol": f"eq.{self.symbol}",
                "replay_version": f"eq.{REPLAY_VERSION}",
                "limit": "1000",
            },
        )
        return {str(row.get("independence_key") or "") for row in rows if row.get("independence_key")}

    async def _m5_window(self, observed: datetime, horizon: datetime) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
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
                "candle_time": f"lt.{observed.isoformat()}",
                "order": "candle_time.desc",
                "limit": "720",
            },
        )
        warm.reverse()
        start = observed - timedelta(minutes=10)
        future = await self.repo.client.get(
            "m5_research_snapshots",
            params={
                "select": select,
                "symbol": f"eq.{self.symbol}",
                "outcome_complete": "eq.true",
                "and": f"(candle_time.gte.{start.isoformat()},candle_time.lte.{horizon.isoformat()})",
                "order": "candle_time.asc",
                "limit": "40",
            },
        )
        return list(warm), list(future)

    async def _m1_window(self, start: datetime, end: datetime) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        cursor: str | None = None
        while len(rows) < 1000:
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
            cursor = str(page[-1].get("candle_time") or "")
            if len(page) < 1000:
                break
        return rows

    def _state_for_m5(
        self,
        history: list[dict[str, Any]],
        latest: dict[str, Any],
    ) -> tuple[dict[str, Any], dict[str, Any], bool, dict[str, Any]]:
        self.engine._rows = list(history[-720:])
        bias, _ = self.engine._bias(latest)
        liquidity = self.engine._liquidity(history)
        clear, assessment = clear_gate._clear_bias_assessment(bias, liquidity)
        return bias, liquidity, clear, assessment

    def _find_entry(
        self,
        *,
        expected_bias: str,
        observed: datetime,
        search_end: datetime,
        warm: list[dict[str, Any]],
        future: list[dict[str, Any]],
        m1_rows: list[dict[str, Any]],
    ) -> dict[str, Any] | None:
        m5_states: list[tuple[datetime, dict[str, Any], list[dict[str, Any]]]] = []
        rolling = list(warm)
        seen_candle_times = {str(row.get("candle_time") or "") for row in rolling}
        for row in future:
            stamp = str(row.get("candle_time") or "")
            if stamp not in seen_candle_times:
                rolling.append(row)
                seen_candle_times.add(stamp)
            decision = _decision_time(row)
            if decision is None or decision < observed or decision > search_end:
                continue
            m5_states.append((decision, row, list(rolling[-720:])))

        if not m5_states:
            return None

        state_index = -1
        state_cache: dict[int, tuple[dict[str, Any], dict[str, Any], bool, dict[str, Any]]] = {}
        for bar in m1_rows:
            bar_time = _parse_time(bar.get("candle_time"))
            if bar_time is None or bar_time < observed or bar_time > search_end:
                continue
            while state_index + 1 < len(m5_states) and m5_states[state_index + 1][0] <= bar_time:
                state_index += 1
            if state_index < 0:
                continue

            decision, latest, history = m5_states[state_index]
            if state_index not in state_cache:
                state_cache[state_index] = self._state_for_m5(history, latest)
            bias, liquidity, clear, assessment = state_cache[state_index]
            overall = str(bias.get("overall") or "neutral").lower()
            if overall != expected_bias:
                # An opposite clear bias ends the original directional opportunity;
                # a later opposite trade is a different setup and must not be
                # credited to this independence sample.
                if clear and overall in {"bullish", "bearish"} and overall != expected_bias:
                    return None
                continue
            if not clear:
                continue
            if not academy.broker_market_open(bar_time) or not session_gate._inside_london_window(bar_time):
                continue

            open_price = _num(bar.get("open"))
            atr = max(_num(latest.get("atr_14")), 0.01)
            zones_at_open = self.engine._zone_candidates(history, open_price, bias)
            zone_at_open = _source_zone_for_bias(zones_at_open, overall)
            if not zone_at_open:
                continue
            probe, resolution = _touch_probe(bar, zone_at_open)
            if probe is None:
                continue

            # Ranking depends partly on distance to live price. Recompute at the
            # actual M1 entry proxy rather than assuming the open-price ranking
            # survives a touch into the zone.
            zones = self.engine._zone_candidates(history, probe, bias)
            setup, trade = v58._candidate_v58(self.engine, probe, atr, bias, zones, liquidity)
            trade = dict(trade or {})
            if str(trade.get("order_type") or "").lower() != "market" or str(trade.get("strategy_key") or "") != v58.STRATEGY_KEY:
                continue

            adjusted = v49._apply_target_cap(trade)
            source_zone = dict(adjusted.get("source_zone") or _source_zone_for_bias(zones, overall) or {})
            entry = _num(adjusted.get("entry"))
            stop = _num(adjusted.get("stop"))
            target = _num(adjusted.get("target"))
            risk = abs(entry - stop)
            if entry <= 0 or stop <= 0 or target <= 0 or risk <= 0:
                continue
            target_r = abs(target - entry) / risk
            return {
                "entry_at": bar_time,
                "decision_at": decision,
                "side": str(adjusted.get("side") or "").upper(),
                "entry": round(entry, 3),
                "stop": round(stop, 3),
                "target": round(target, 3),
                "target_r": round(target_r, 3),
                "source_zone": source_zone,
                "clear_bias_gate": assessment,
                "confirmation": {
                    "m5": ((bias.get("timeframes") or {}).get("M5") or {}).get("direction"),
                    "m15": ((bias.get("timeframes") or {}).get("M15") or {}).get("direction"),
                    "overall": overall,
                    "entry_resolution": resolution,
                    "m1_bar_time": bar_time.isoformat(),
                },
                "trade": adjusted,
                "setup": setup,
            }
        return None

    async def _replay_episode(self, row: dict[str, Any]) -> dict[str, Any]:
        observed = _parse_time(row.get("observed_at"))
        if observed is None:
            raise RuntimeError("eligible historical episode has no parseable observed_at")
        episode_key = str(row.get("historical_episode_key") or "")
        independence_key = str(row.get("independence_key") or "")
        descriptor = dict((row.get("market_state") or {}).get("setup_family_descriptor") or {})
        expected_bias = str(descriptor.get("bias") or "").lower()
        horizon_minutes = max(1, int(self.settings.live_trader_learning_horizon_minutes))
        search_end = observed + timedelta(minutes=horizon_minutes)
        source_end = search_end + timedelta(minutes=horizon_minutes + 5)

        warm, future = await self._m5_window(observed, search_end)
        m1_rows = await self._m1_window(observed, source_end)
        search_path = hardening._causal_m1_path(m1_rows, observed, search_end)
        if not _path_complete(search_path):
            return {
                "replay_key": _replay_key(episode_key),
                "historical_episode_key": episode_key,
                "independence_key": independence_key,
                "symbol": self.symbol,
                "observed_at": observed.isoformat(),
                "entry_at": None,
                "status": "unscorable_search_path",
                "path_complete": False,
                "trade_outcome": None,
                "realised_r": None,
                "learning_success": None,
                "replay_version": REPLAY_VERSION,
                "evaluation_horizon_minutes": horizon_minutes,
                "details": {
                    "expected_bias": expected_bias,
                    "entry_policy": ENTRY_POLICY,
                    "entry_resolution": ENTRY_RESOLUTION,
                    "search_path": {key: search_path.get(key) for key in ("initial_gap_seconds", "gap_count", "endpoint_lag_seconds")},
                },
            }

        entry = self._find_entry(
            expected_bias=expected_bias,
            observed=observed,
            search_end=search_end,
            warm=warm,
            future=future,
            m1_rows=list(search_path.get("bars") or m1_rows),
        )
        if entry is None:
            return {
                "replay_key": _replay_key(episode_key),
                "historical_episode_key": episode_key,
                "independence_key": independence_key,
                "symbol": self.symbol,
                "observed_at": observed.isoformat(),
                "entry_at": None,
                "status": "no_entry",
                "path_complete": True,
                "trade_outcome": "no_live_policy_entry",
                "realised_r": 0.0,
                "learning_success": None,
                "replay_version": REPLAY_VERSION,
                "evaluation_horizon_minutes": horizon_minutes,
                "details": {
                    "expected_bias": expected_bias,
                    "entry_policy": ENTRY_POLICY,
                    "entry_resolution": ENTRY_RESOLUTION,
                    "historical_news_gate_replayed": False,
                },
            }

        entry_at = entry["entry_at"]
        outcome_end = entry_at + timedelta(minutes=horizon_minutes)
        outcome_path = hardening._causal_m1_path(m1_rows, entry_at, outcome_end)
        if not _path_complete(outcome_path):
            return {
                "replay_key": _replay_key(episode_key),
                "historical_episode_key": episode_key,
                "independence_key": independence_key,
                "symbol": self.symbol,
                "observed_at": observed.isoformat(),
                "entry_at": entry_at.isoformat(),
                "status": "unscorable_outcome_path",
                "side": entry.get("side"),
                "entry": entry.get("entry"),
                "stop": entry.get("stop"),
                "target": entry.get("target"),
                "target_r": entry.get("target_r"),
                "source_zone": entry.get("source_zone"),
                "clear_bias_gate": entry.get("clear_bias_gate"),
                "confirmation": entry.get("confirmation"),
                "path_complete": False,
                "trade_outcome": None,
                "realised_r": None,
                "learning_success": None,
                "replay_version": REPLAY_VERSION,
                "evaluation_horizon_minutes": horizon_minutes,
                "details": {
                    "expected_bias": expected_bias,
                    "entry_policy": ENTRY_POLICY,
                    "entry_resolution": ENTRY_RESOLUTION,
                    "outcome_path": {key: outcome_path.get(key) for key in ("initial_gap_seconds", "gap_count", "endpoint_lag_seconds")},
                },
            }

        trade = dict(entry.get("trade") or {})
        result = integrity._trade_path_result_v39(
            trade,
            list(outcome_path.get("bars") or []),
            float(outcome_path.get("endpoint_price")),
        )
        return {
            "replay_key": _replay_key(episode_key),
            "historical_episode_key": episode_key,
            "independence_key": independence_key,
            "symbol": self.symbol,
            "observed_at": observed.isoformat(),
            "entry_at": entry_at.isoformat(),
            "status": "scored",
            "side": entry.get("side"),
            "entry": entry.get("entry"),
            "stop": entry.get("stop"),
            "target": entry.get("target"),
            "target_r": entry.get("target_r"),
            "source_zone": entry.get("source_zone"),
            "clear_bias_gate": entry.get("clear_bias_gate"),
            "confirmation": entry.get("confirmation"),
            "path_complete": True,
            "trade_outcome": result.get("trade_outcome"),
            "realised_r": result.get("realised_r"),
            "learning_success": result.get("learning_success"),
            "replay_version": REPLAY_VERSION,
            "evaluation_horizon_minutes": horizon_minutes,
            "details": {
                "expected_bias": expected_bias,
                "entry_policy": ENTRY_POLICY,
                "entry_resolution": ENTRY_RESOLUTION,
                "target_policy": trade.get("target_policy"),
                "historical_news_gate_replayed": False,
                "same_entry_minute_policy": "market scorer is stop-first when stop and target are both inside one M1 bar",
            },
        }

    async def _store_result(self, result: dict[str, Any]) -> None:
        await self.repo.client.upsert(
            "live_trader_zone_retrace_live_policy_replays",
            {**result, "updated_at": core.utc_now().isoformat()},
            on_conflict="replay_key",
            return_rows=False,
        )

    async def _aggregate(self, eligible: list[dict[str, Any]]) -> dict[str, Any]:
        rows = await self.repo.client.get(
            "live_trader_zone_retrace_live_policy_replays",
            params={
                "select": "independence_key,status,entry_at,path_complete,realised_r,learning_success",
                "symbol": f"eq.{self.symbol}",
                "replay_version": f"eq.{REPLAY_VERSION}",
                "limit": "1000",
            },
        )
        eligible_keys = {str(row.get("independence_key") or "") for row in eligible}
        rows = [row for row in rows if str(row.get("independence_key") or "") in eligible_keys]
        processed = len(rows)
        scorable_rows = [row for row in rows if bool(row.get("path_complete")) and str(row.get("status") or "") in {"scored", "no_entry"}]
        unscorable = processed - len(scorable_rows)
        triggered_rows = [row for row in scorable_rows if row.get("entry_at")]
        total_r = sum(_num(row.get("realised_r")) for row in scorable_rows if row.get("realised_r") is not None)
        wins = sum(1 for row in triggered_rows if _num(row.get("realised_r")) > 0)
        losses = sum(1 for row in triggered_rows if _num(row.get("realised_r")) < 0)
        breakeven = sum(1 for row in triggered_rows if row.get("realised_r") is not None and _num(row.get("realised_r")) == 0)
        scorable = len(scorable_rows)
        triggered = len(triggered_rows)
        expectancy_opportunity = total_r / scorable if scorable else None
        expectancy_triggered = total_r / triggered if triggered else None
        trigger_rate = triggered / scorable if scorable else None
        eligible_count = len(eligible)
        completed = bool(eligible_count > 0 and processed >= eligible_count)
        coverage = scorable / eligible_count if eligible_count else 0.0
        promoted = bool(
            completed
            and coverage >= MIN_SCORABLE_COVERAGE
            and scorable >= MIN_PROMOTION_OPPORTUNITIES
            and triggered >= MIN_PROMOTION_TRIGGERED
            and expectancy_opportunity is not None
            and expectancy_opportunity > MIN_PROMOTION_EXPECTANCY_R
        )
        status = "complete_promoted" if promoted else "complete_not_promoted" if completed else "running"
        payload = {
            "symbol": self.symbol,
            "replay_version": REPLAY_VERSION,
            "status": status,
            "eligible_episodes": eligible_count,
            "processed_episodes": processed,
            "scorable_episodes": scorable,
            "unscorable_episodes": unscorable,
            "triggered": triggered,
            "wins": wins,
            "losses": losses,
            "breakeven": breakeven,
            "total_r": round(total_r, 3),
            "expectancy_per_opportunity_r": round(expectancy_opportunity, 4) if expectancy_opportunity is not None else None,
            "expectancy_per_triggered_r": round(expectancy_triggered, 4) if expectancy_triggered is not None else None,
            "trigger_rate": round(trigger_rate, 4) if trigger_rate is not None else None,
            "promoted": promoted,
            "completed": completed,
            "last_processed_at": core.utc_now().isoformat() if processed else None,
            "last_error": self.last_error,
            "policy": {
                "entry_policy": ENTRY_POLICY,
                "entry_resolution": ENTRY_RESOLUTION,
                "target_cap_r": LIVE_TARGET_CAP_R,
                "evaluation_horizon_minutes": int(self.settings.live_trader_learning_horizon_minutes),
                "minimum_scorable_coverage": MIN_SCORABLE_COVERAGE,
                "promotion_min_opportunities": MIN_PROMOTION_OPPORTUNITIES,
                "promotion_min_triggered": MIN_PROMOTION_TRIGGERED,
                "promotion_min_expectancy_r": MIN_PROMOTION_EXPECTANCY_R,
                "historical_news_gate_replayed": False,
                "same_entry_minute_policy": "stop_first",
            },
            "updated_at": core.utc_now().isoformat(),
        }
        await self.repo.client.upsert(
            "live_trader_zone_retrace_live_policy_state",
            payload,
            on_conflict="symbol",
            return_rows=False,
        )
        self.last_state = dict(payload)
        specialist = dict(getattr(self.owner, "_zone_retrace_learning_v58", {}) or {})
        specialist["live_policy_replay"] = dict(payload)
        self.owner._zone_retrace_learning_v58 = specialist
        return payload

    async def run_batch(self) -> bool:
        eligible = await self._eligible_rows()
        processed = await self._processed_independence()
        missing = [row for row in eligible if str(row.get("independence_key") or "") not in processed]
        if not missing:
            await self._aggregate(eligible)
            return False

        for row in missing[:REPLAY_BATCH_SIZE]:
            result = await self._replay_episode(row)
            await self._store_result(result)
            await asyncio.sleep(0)
        await self._aggregate(eligible)
        return True

    async def run_forever(self) -> None:
        while not self._stop.is_set():
            try:
                progressed = await self.run_batch()
                self.last_error = None
                delay = REPLAY_IDLE_SECONDS if progressed else 300.0
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                self.last_error = str(exc)[:500]
                core.logger.exception("Zone Retracement live-policy replay failed")
                try:
                    eligible = await self._eligible_rows()
                    await self._aggregate(eligible)
                except Exception:
                    pass
                delay = 15.0
            try:
                await asyncio.wait_for(self._stop.wait(), timeout=delay)
            except asyncio.TimeoutError:
                pass


async def _run_forever_v68(self: core.LiveTrader) -> None:
    replayer = getattr(self, "_zone_retrace_live_policy_replayer_v68", None)
    if replayer is None:
        replayer = ZoneRetraceLivePolicyReplayer(self)
        self._zone_retrace_live_policy_replayer_v68 = replayer
    task = asyncio.create_task(replayer.run_forever(), name="eve-zone-retrace-live-policy-replay")
    try:
        await _current_run_forever(self)
    finally:
        await replayer.stop()
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass


async def _learning_summary_v68(self: core.LiveTrader) -> dict[str, Any]:
    summary = dict(await _current_learning_summary(self))
    replay = await _load_replay_state(self)
    specialist = dict(summary.get("zone_retrace_specialist") or getattr(self, "_zone_retrace_learning_v58", {}) or {})
    if replay:
        specialist["live_policy_replay"] = replay
    if specialist:
        specialist = _evidence_contract_v68(specialist)
        summary["zone_retrace_specialist"] = specialist
    summary["zone_retrace_live_policy_replay"] = replay or {
        "replay_version": REPLAY_VERSION,
        "status": "waiting_for_first_batch",
    }
    return summary


def _runtime_status_v68(self: core.LiveTrader) -> dict[str, Any]:
    status = dict(_current_runtime_status(self))
    replayer = getattr(self, "_zone_retrace_live_policy_replayer_v68", None)
    state = dict(getattr(replayer, "last_state", {}) or {}) if replayer is not None else {}
    status.update(
        {
            "zone_retrace_live_policy_replay_version": REPLAY_VERSION,
            "zone_retrace_live_policy_replay_running": replayer is not None and not replayer._stop.is_set(),
            "zone_retrace_live_policy_replay_status": state.get("status"),
            "zone_retrace_live_policy_replay_processed": state.get("processed_episodes"),
            "zone_retrace_live_policy_replay_eligible": state.get("eligible_episodes"),
            "zone_retrace_live_policy_replay_promoted": state.get("promoted"),
            "zone_retrace_live_policy_entry_resolution": ENTRY_RESOLUTION,
            "zone_retrace_historical_news_gate_replayed": False,
        }
    )
    return status


# Merge the replay state into every restart/read path, then replace v67's static
# block with a contract that can unlock only from the separate v68 replay ledger.
v64._load_specialist_row = _load_specialist_row_v68
v64._audited_specialist = _evidence_contract_v68
core.LiveTrader.run_forever = _run_forever_v68  # type: ignore[method-assign]
core.LiveTrader.learning_summary = _learning_summary_v68  # type: ignore[method-assign]
core.LiveTrader.runtime_status = _runtime_status_v68  # type: ignore[method-assign]
