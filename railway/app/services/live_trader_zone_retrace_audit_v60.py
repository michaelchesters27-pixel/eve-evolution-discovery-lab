from __future__ import annotations

from typing import Any

from app.services import live_trader as core
from app.services import live_trader_zone_retrace_specialist_v58 as v58

AUDIT_VERSION = "eve-live-zone-retrace-audit-v60"
_current_learning_summary = core.LiveTrader.learning_summary


def _num(value: Any, default: float = 0.0) -> float:
    return core.number(value, default)


def _bucket() -> dict[str, Any]:
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


async def _historical_rows_v60(self: core.LiveTrader) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for page in range(v58.HISTORICAL_PAGES):
        offset = page * v58.HISTORICAL_PAGE_SIZE
        batch = await self.repo.client.get(
            "live_trader_historical_learning",
            params={
                "select": "observed_at,independence_key,market_state,challenger_results,path_complete",
                "path_complete": "eq.true",
                "order": "observed_at.desc",
                "limit": str(v58.HISTORICAL_PAGE_SIZE),
                "offset": str(offset),
            },
        )
        rows.extend(batch)
        if len(batch) < v58.HISTORICAL_PAGE_SIZE:
            break
    return rows


def _score_retrace_only(rows: list[dict[str, Any]]) -> tuple[int, dict[str, Any]]:
    """Score independent genuine pullback/retracement episodes only."""
    evidence = {key: _bucket() for key in v58.EXECUTIONS}
    relevant = 0
    seen_independence: set[str] = set()

    for row in rows:
        market_state = dict(row.get("market_state") or {})
        descriptor = dict(market_state.get("setup_family_descriptor") or {})
        bias = str(descriptor.get("bias") or "").lower()
        location = str(descriptor.get("location_relation") or "").lower()
        zone_quality = str(descriptor.get("zone_quality") or "").lower()
        execution_class = str(descriptor.get("execution_class") or "").lower()

        if bias not in {"bullish", "bearish"}:
            continue
        if location not in {"preferred", "at_zone"}:
            continue
        if zone_quality not in {"good", "high"}:
            continue
        if execution_class != "pullback":
            continue

        independence_key = str(row.get("independence_key") or "").strip()
        if independence_key:
            if independence_key in seen_independence:
                continue
            seen_independence.add(independence_key)

        relevant += 1
        challengers = dict(row.get("challenger_results") or {})
        for key in v58.EXECUTIONS:
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


async def _learning_summary_v60(self: core.LiveTrader) -> dict[str, Any]:
    summary = dict(await _current_learning_summary(self))
    specialist = dict(getattr(self, "_zone_retrace_learning_v58", {}) or {})
    if not specialist:
        try:
            rows = await self.repo.client.get(
                "live_trader_zone_retrace_learning_state",
                params={"select": "*", "symbol": f"eq.{self.symbol}", "limit": "1"},
            )
            specialist = dict(rows[0] or {}) if rows else {}
        except Exception as exc:
            specialist = {"status": "error", "last_error": str(exc)[:500]}
    specialist.setdefault("strategy_key", v58.STRATEGY_KEY)
    specialist.setdefault("version", v58.SPECIALIST_VERSION)
    specialist["audit_version"] = AUDIT_VERSION
    specialist["evidence_scope"] = "independent_pullback_only"
    specialist["breakout_examples_excluded"] = True
    specialist["independence_deduplication"] = True
    summary["zone_retrace_specialist"] = specialist
    return summary


# Audit hardening only: live campaign publication remains owned by v58.
v58._historical_rows = _historical_rows_v60
v58._score_execution_evidence = _score_retrace_only
core.LiveTrader.learning_summary = _learning_summary_v60  # type: ignore[method-assign]

# Preserve specialist identity on every future locked campaign so a published
# retracement trade can be audited unambiguously after entry and completion.
from app.services import live_trader_zone_retrace_campaign_audit_v61 as _live_trader_zone_retrace_campaign_audit_v61  # noqa: E402,F401
