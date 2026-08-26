from __future__ import annotations

import asyncio
from datetime import timedelta
from typing import Any

from app.services import live_trader as core
from app.services import live_trader_trade_lock_v28 as lock

SPECIALIST_VERSION = "eve-live-zone-retrace-specialist-v58"
STRATEGY_KEY = "zone_retrace_v1"
LEARNING_CYCLE_SECONDS = 300.0
HISTORICAL_PAGE_SIZE = 1000
HISTORICAL_PAGES = 5
EXECUTIONS = ("market", "pullback_limit", "confirmation_stop")

# Fresh candidates reach the campaign lock through this function. Patching the
# pre-lock candidate keeps already-published campaigns immutable while changing
# only what EVE is allowed to publish next.
_prelock_trade_idea = lock._original_trade_idea
_current_refresh_state = core.LiveTrader.refresh_state
_current_runtime_status = core.LiveTrader.runtime_status


def _num(value: Any, default: float = 0.0) -> float:
    return core.number(value, default)


def _wait(overall: str, reason: str, *, side: str | None = None) -> tuple[dict[str, Any], dict[str, Any]]:
    trade: dict[str, Any] = {
        "action": "WAIT",
        "order_type": "none",
        "reason": reason,
        "manual_only": True,
        "automatic_order_placement": False,
        "strategy_key": STRATEGY_KEY,
        "specialist_version": SPECIALIST_VERSION,
    }
    if side:
        trade["side"] = side
    return {"status": "ZONE RETRACE WAIT", "reason": reason}, trade


def _zone_for_side(zones: dict[str, list[dict[str, Any]]], side: str) -> dict[str, Any] | None:
    kind = "demand" if side == "BUY" else "supply" if side == "SELL" else ""
    items = list((zones or {}).get(kind) or [])
    return dict(items[0]) if items else None


def _candidate_v58(
    self: core.LiveTrader,
    price: float,
    atr: float,
    bias: dict[str, Any],
    zones: dict[str, list[dict[str, Any]]],
    liquidity: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, Any]]:
    setup, trade = _prelock_trade_idea(self, price, atr, bias, zones, liquidity)
    setup = dict(setup or {})
    trade = dict(trade or {})

    order_type = str(trade.get("order_type") or "none").lower()
    action = str(trade.get("action") or "").upper()
    if order_type == "none" or action in {"", "WAIT", "NO TRADE"}:
        return setup, trade

    overall = str((bias or {}).get("overall") or "neutral").lower()
    side = str(trade.get("side") or ("BUY" if order_type.startswith("buy") else "SELL")).upper()
    expected_side = "BUY" if overall == "bullish" else "SELL" if overall == "bearish" else ""
    zone_kind = "demand" if side == "BUY" else "supply"

    if not expected_side or side != expected_side:
        return _wait(overall, "EVE has no specialist entry because the proposed side is not aligned with the live directional bias.", side=side)

    # The specialist never chases a breakout. Confirmation-stop remains a
    # historical execution challenger, but it is not allowed to publish a fresh
    # live idea while the strategy is still specialising in zone entries.
    if order_type in {"buy_stop", "sell_stop"}:
        return _wait(
            overall,
            f"{overall.title()} bias is present, but EVE will not chase a breakout. Waiting for price to retrace into {zone_kind} and confirm.",
            side=side,
        )

    # Limit orders would enter on the touch before confirmation. EVE studies
    # those in the academy, but the live default is confirmation first, market
    # execution second.
    if order_type in {"buy_limit", "sell_limit"}:
        return _wait(
            overall,
            f"{overall.title()} bias is clear. Waiting for the retracement into {zone_kind}; EVE wants confirmation at the zone before entering rather than a blind limit.",
            side=side,
        )

    if order_type != "market":
        return _wait(overall, "EVE is waiting for a valid zone-retracement execution.", side=side)

    zone = _zone_for_side(zones, side)
    if not zone:
        return _wait(overall, f"{overall.title()} bias is clear, but there is no valid {zone_kind} zone for a specialist entry yet.", side=side)

    low = _num(zone.get("low"))
    high = _num(zone.get("high"))
    quality = _num(zone.get("quality"))
    timeframes = dict((bias or {}).get("timeframes") or {})
    m5 = str((timeframes.get("M5") or {}).get("direction") or "")
    m15 = str((timeframes.get("M15") or {}).get("direction") or "")
    in_zone = low <= price <= high if low > 0 and high > 0 else False
    confirmed = m5 == overall and m15 == overall

    if not in_zone or quality < 58 or not confirmed:
        detail = []
        if not in_zone:
            detail.append(f"price is not inside the current {zone_kind} zone")
        if quality < 58:
            detail.append("zone quality is below the specialist threshold")
        if not confirmed:
            detail.append("M5/M15 have not confirmed with the bias")
        return _wait(overall, f"{overall.title()} bias is clear, but " + "; ".join(detail) + ".", side=side)

    trade["strategy_key"] = STRATEGY_KEY
    trade["specialist_version"] = SPECIALIST_VERSION
    trade["execution_class"] = "zone_retrace_confirmation"
    trade["entry_policy"] = "market_after_zone_confirmation"
    trade["source_zone"] = {
        "id": zone.get("id"),
        "kind": zone.get("kind") or zone_kind,
        "low": zone.get("low"),
        "high": zone.get("high"),
        "quality": zone.get("quality"),
        "fresh": zone.get("fresh"),
        "retests": zone.get("retests"),
    }
    trade["reason"] = (
        f"Zone Retracement Specialist: {overall} bias, retracement into {zone_kind}, "
        "and M5/M15 confirmation are aligned. Market execution is permitted."
    )
    setup["status"] = "ZONE RETRACE CONFIRMED"
    setup["reason"] = trade["reason"]
    return setup, trade


def _execution_bucket() -> dict[str, Any]:
    return {
        "opportunities": 0,
        "triggered": 0,
        "scored": 0,
        "wins": 0,
        "losses": 0,
        "breakeven": 0,
        "total_r": 0.0,
        "expectancy_per_opportunity_r": None,
        "expectancy_per_triggered_r": None,
        "trigger_rate": None,
    }


def _score_execution_evidence(rows: list[dict[str, Any]]) -> tuple[int, dict[str, Any]]:
    evidence = {key: _execution_bucket() for key in EXECUTIONS}
    relevant = 0

    for row in rows:
        market_state = dict(row.get("market_state") or {})
        descriptor = dict(market_state.get("setup_family_descriptor") or {})
        bias = str(descriptor.get("bias") or "").lower()
        location = str(descriptor.get("location_relation") or "").lower()
        zone_quality = str(descriptor.get("zone_quality") or "").lower()
        if bias not in {"bullish", "bearish"}:
            continue
        if location not in {"preferred", "at_zone"}:
            continue
        if zone_quality not in {"good", "high"}:
            continue

        relevant += 1
        challengers = dict(row.get("challenger_results") or {})
        for key in EXECUTIONS:
            result = challengers.get(key)
            if not isinstance(result, dict) or not result:
                continue
            bucket = evidence[key]
            bucket["opportunities"] += 1
            triggered = bool(result.get("entry_triggered"))
            if triggered:
                bucket["triggered"] += 1
            realised = result.get("realised_r")
            if realised is None:
                continue
            r = _num(realised)
            # Non-triggered challengers often carry 0R for bookkeeping. They
            # count in opportunity expectancy but not in triggered expectancy.
            bucket["scored"] += 1
            bucket["total_r"] += r
            if r > 0:
                bucket["wins"] += 1
            elif r < 0:
                bucket["losses"] += 1
            else:
                bucket["breakeven"] += 1

    for bucket in evidence.values():
        opportunities = int(bucket["opportunities"])
        triggered = int(bucket["triggered"])
        total_r = float(bucket["total_r"])
        bucket["total_r"] = round(total_r, 3)
        bucket["expectancy_per_opportunity_r"] = round(total_r / opportunities, 4) if opportunities else None
        bucket["expectancy_per_triggered_r"] = round(total_r / triggered, 4) if triggered else None
        bucket["trigger_rate"] = round(triggered / opportunities, 4) if opportunities else None
    return relevant, evidence


def _best_execution(evidence: dict[str, Any]) -> tuple[str | None, str | None]:
    qualified: list[tuple[float, str]] = []
    promoted: list[tuple[float, str]] = []
    for key, bucket in evidence.items():
        opportunities = int(bucket.get("opportunities") or 0)
        triggered = int(bucket.get("triggered") or 0)
        expectancy = bucket.get("expectancy_per_opportunity_r")
        if expectancy is None:
            continue
        score = float(expectancy)
        if opportunities >= 20:
            qualified.append((score, key))
        if opportunities >= 50 and triggered >= 30 and score > 0.10:
            promoted.append((score, key))
    qualified.sort(reverse=True)
    promoted.sort(reverse=True)
    return (qualified[0][1] if qualified else None, promoted[0][1] if promoted else None)


async def _historical_rows(self: core.LiveTrader) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for page in range(HISTORICAL_PAGES):
        offset = page * HISTORICAL_PAGE_SIZE
        batch = await self.repo.client.get(
            "live_trader_historical_learning",
            params={
                "select": "observed_at,market_state,challenger_results,path_complete",
                "path_complete": "eq.true",
                "order": "observed_at.desc",
                "limit": str(HISTORICAL_PAGE_SIZE),
                "offset": str(offset),
            },
        )
        rows.extend(batch)
        if len(batch) < HISTORICAL_PAGE_SIZE:
            break
    return rows


async def _run_specialist_cycle(self: core.LiveTrader) -> dict[str, Any]:
    now = core.utc_now()
    try:
        rows = await _historical_rows(self)
        relevant, evidence = _score_execution_evidence(rows)
        best, promoted = _best_execution(evidence)
        previous = await self.repo.client.get(
            "live_trader_zone_retrace_learning_state",
            params={"select": "cycle_count", "symbol": f"eq.{self.symbol}", "limit": "1"},
        )
        cycle_count = int(_num((previous[0] if previous else {}).get("cycle_count"))) + 1
        payload = {
            "symbol": self.symbol,
            "strategy_key": STRATEGY_KEY,
            "version": SPECIALIST_VERSION,
            "cycle_count": cycle_count,
            "last_cycle_at": now.isoformat(),
            "rows_evaluated": len(rows),
            "relevant_episodes": relevant,
            "execution_evidence": evidence,
            "best_execution": best,
            "promoted_execution": promoted,
            "status": "learning" if promoted is None else "mature_candidate",
            "updated_at": now.isoformat(),
        }
        await self.repo.client.upsert(
            "live_trader_zone_retrace_learning_state",
            payload,
            on_conflict="symbol",
            return_rows=False,
        )
        await self.repo.client.insert(
            "system_events",
            {
                "level": "success",
                "component": "live_trader_zone_retrace_specialist",
                "message": (
                    f"Zone retracement specialist cycle {cycle_count} evaluated {len(rows)} historical episodes; "
                    f"{relevant} matched the specialist location filter. Best execution: {best or 'not enough evidence'}."
                ),
                "details": {
                    "version": SPECIALIST_VERSION,
                    "strategy_key": STRATEGY_KEY,
                    "cycle_count": cycle_count,
                    "rows_evaluated": len(rows),
                    "relevant_episodes": relevant,
                    "best_execution": best,
                    "promoted_execution": promoted,
                    "execution_evidence": evidence,
                },
            },
            return_rows=False,
        )
        self._zone_retrace_learning_v58 = payload
        self._zone_retrace_last_cycle_v58 = now
        return payload
    except Exception as exc:
        core.logger.warning("Zone Retracement Specialist cycle failed: %s", exc)
        payload = dict(getattr(self, "_zone_retrace_learning_v58", {}) or {})
        payload.update({"version": SPECIALIST_VERSION, "strategy_key": STRATEGY_KEY, "status": "error", "last_error": str(exc)[:500]})
        self._zone_retrace_learning_v58 = payload
        self._zone_retrace_last_cycle_v58 = now
        return payload


async def _refresh_state_v58(self: core.LiveTrader, *, force_rows: bool = False) -> dict[str, Any]:
    last = getattr(self, "_zone_retrace_last_cycle_v58", None)
    if last is None or core.utc_now() - last >= timedelta(seconds=LEARNING_CYCLE_SECONDS):
        cycle_lock = getattr(self, "_zone_retrace_cycle_lock_v58", None)
        if cycle_lock is None:
            cycle_lock = asyncio.Lock()
            self._zone_retrace_cycle_lock_v58 = cycle_lock
        async with cycle_lock:
            # Re-check after acquiring the lock because several API/tick refreshes
            # can arrive together. Reserve the slot before I/O so one real cycle
            # can never be counted multiple times.
            last = getattr(self, "_zone_retrace_last_cycle_v58", None)
            if last is None or core.utc_now() - last >= timedelta(seconds=LEARNING_CYCLE_SECONDS):
                self._zone_retrace_last_cycle_v58 = core.utc_now()
                await _run_specialist_cycle(self)

    state = dict(await _current_refresh_state(self, force_rows=force_rows))
    specialist = dict(getattr(self, "_zone_retrace_learning_v58", {}) or {})
    if not specialist:
        try:
            rows = await self.repo.client.get(
                "live_trader_zone_retrace_learning_state",
                params={"select": "*", "symbol": f"eq.{self.symbol}", "limit": "1"},
            )
            specialist = dict(rows[0] or {}) if rows else {}
        except Exception:
            specialist = {}
    specialist.setdefault("version", SPECIALIST_VERSION)
    specialist.setdefault("strategy_key", STRATEGY_KEY)
    specialist["live_entry_policy"] = "market_after_zone_confirmation"
    specialist["breakout_chasing_allowed"] = False
    specialist["blind_limit_entry_allowed"] = False
    state["zone_retrace_learning"] = specialist
    learning = dict(state.get("learning") or {})
    learning["zone_retrace_specialist"] = specialist
    state["learning"] = learning
    self._latest_state = state
    return state


def _runtime_status_v58(self: core.LiveTrader) -> dict[str, Any]:
    state = dict(_current_runtime_status(self))
    specialist = dict(getattr(self, "_zone_retrace_learning_v58", {}) or {})
    state.update(
        {
            "zone_retrace_specialist_version": SPECIALIST_VERSION,
            "zone_retrace_strategy_key": STRATEGY_KEY,
            "zone_retrace_cycle_count": specialist.get("cycle_count"),
            "zone_retrace_last_cycle_at": specialist.get("last_cycle_at"),
            "zone_retrace_live_entry_policy": "market_after_zone_confirmation",
            "zone_retrace_breakout_chasing_allowed": False,
        }
    )
    return state


# Fresh campaign candidates are now specialist-only. Already locked campaigns do
# not call this path and therefore remain exactly as published.
lock._original_trade_idea = _candidate_v58
core.LiveTrader.refresh_state = _refresh_state_v58  # type: ignore[method-assign]
core.LiveTrader.runtime_status = _runtime_status_v58  # type: ignore[method-assign]
