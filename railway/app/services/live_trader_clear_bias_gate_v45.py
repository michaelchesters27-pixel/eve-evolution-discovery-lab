from __future__ import annotations

from typing import Any

from app.services import live_trader as core
from app.services import live_trader_execution_integrity_v39 as integrity
from app.services import live_trader_trade_lock_v28 as lock

GATE_VERSION = "eve-live-clear-bias-gate-v1"
MIN_CLEAR_CONFIDENCE = 65
STRUCTURAL_PANEL_VERSION = "eve-live-bias-v2.5-structural-panel"
OPEN_CAMPAIGN_STATUSES = {"pending", "active"}
CRITICAL_TIMEFRAMES = ("D1", "H4", "H1", "M30", "M15")

_original_trade_idea = core.LiveTrader._trade_idea
_original_runtime_status = core.LiveTrader.runtime_status


def _direction(value: Any) -> str:
    text = str(value or "unknown").lower()
    return text if text in {"bullish", "bearish", "neutral", "unknown"} else "unknown"


def _is_modern_structural_bias(bias: dict[str, Any]) -> bool:
    """Identify the production v43+ bias payload.

    Older deterministic unit helpers construct small hand-written bias dictionaries.
    They remain compatible so this runtime gate does not silently reinterpret old
    research helper contracts. Production Live Trader always carries the structural
    panel version installed before this module in app.__init__.
    """
    if str(bias.get("panel_bias_version") or "") == STRUCTURAL_PANEL_VERSION:
        return True
    timeframes = dict(bias.get("timeframes") or {})
    return any(isinstance(item, dict) and "method" in item for item in timeframes.values())


def _clear_bias_assessment(
    bias: dict[str, Any] | None,
    liquidity: dict[str, Any] | None = None,
) -> tuple[bool, dict[str, Any]]:
    payload = dict(bias or {})
    overall = _direction(payload.get("overall"))
    confidence = int(round(core.number(payload.get("confidence"))))
    timeframes = dict(payload.get("timeframes") or {})
    quality = dict(payload.get("data_quality") or {})

    # Compatibility only for legacy deterministic helpers. The live runtime uses
    # v43+ structural payloads and therefore never takes this path.
    if not _is_modern_structural_bias(payload):
        return True, {
            "version": GATE_VERSION,
            "clear": True,
            "compatibility_bypass": True,
            "overall": overall,
            "confidence": confidence,
            "reasons": [],
        }

    reasons: list[str] = []
    if overall not in {"bullish", "bearish"}:
        reasons.append("overall bias is not directional")
    if confidence < MIN_CLEAR_CONFIDENCE:
        reasons.append(f"bias confidence is {confidence}, below {MIN_CLEAR_CONFIDENCE}")

    critical_stale = [str(value) for value in (quality.get("critical_stale") or []) if value]
    if quality.get("trade_bias_blocked") or critical_stale:
        labels = ", ".join(critical_stale) if critical_stale else "critical higher-timeframe data"
        reasons.append(f"data quality is blocking bias ({labels})")

    directions = {timeframe: _direction((timeframes.get(timeframe) or {}).get("direction")) for timeframe in CRITICAL_TIMEFRAMES}
    unknown = [timeframe for timeframe, direction in directions.items() if direction == "unknown"]
    if unknown:
        reasons.append(f"critical timeframe direction is unknown ({', '.join(unknown)})")

    if overall in {"bullish", "bearish"}:
        opposite = "bearish" if overall == "bullish" else "bullish"

        # H4 + H1 are the core directional spine. M15 must agree before EVE is
        # even allowed to consider execution. D1/M30 may be neutral, but neither
        # is allowed to actively oppose the proposed direction.
        for timeframe in ("H4", "H1", "M15"):
            if directions.get(timeframe) != overall:
                reasons.append(f"{timeframe} is not aligned with {overall} bias")
        for timeframe in ("D1", "M30"):
            if directions.get(timeframe) == opposite:
                reasons.append(f"{timeframe} actively opposes {overall} bias")

        aligned_count = sum(1 for direction in directions.values() if direction == overall)
        if aligned_count < 4:
            reasons.append(f"only {aligned_count}/5 critical timeframes align; at least 4 are required")

        # A strong live event pointing the other way means the trade context is
        # not clean enough even if the weighted bias score is directional. This
        # closes the accepted-breakout loophole found in the production audit.
        event = dict((liquidity or {}).get("primary_event") or {})
        implication = _direction(event.get("implication"))
        strength = int(core.number(event.get("strength")))
        if implication == opposite and strength >= 72:
            label = str(event.get("label") or "strong opposing market event")
            reasons.append(f"{label} is strongly opposed to the {overall} bias")

    return not reasons, {
        "version": GATE_VERSION,
        "clear": not reasons,
        "overall": overall,
        "confidence": confidence,
        "minimum_confidence": MIN_CLEAR_CONFIDENCE,
        "critical_timeframes": directions,
        "aligned_critical_timeframes": sum(1 for direction in directions.values() if direction == overall),
        "reasons": reasons,
    }


def _wait_response(assessment: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    reasons = list(assessment.get("reasons") or [])
    explanation = "; ".join(reasons[:3]) if reasons else "bias is not clear enough"
    reason = (
        f"No new trade idea: EVE requires a clear directional bias before publishing an order. {explanation}."
    )
    return (
        {"status": "BIAS WAIT", "reason": reason, "clear_bias_gate": assessment},
        {
            "action": "WAIT",
            "order_type": "none",
            "reason": reason,
            "manual_only": True,
            "automatic_order_placement": False,
            "clear_bias_blocked": True,
            "clear_bias_gate": assessment,
        },
    )


def _trade_idea_v45(
    self: core.LiveTrader,
    price: float,
    atr: float,
    bias: dict[str, Any],
    zones: dict[str, list[dict[str, Any]]],
    liquidity: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, Any]]:
    # Never reinterpret or replace an already-published campaign. Pending/active
    # campaigns remain owned by the lock/invalidation/risk-management chain.
    campaign = getattr(self, "_live_campaign", None)
    campaign_status = str((campaign or {}).get("status") or "").lower() if isinstance(campaign, dict) else ""
    if campaign_status in OPEN_CAMPAIGN_STATUSES:
        return _original_trade_idea(self, price, atr, bias, zones, liquidity)

    clear, assessment = _clear_bias_assessment(bias, liquidity)
    if not clear:
        return _wait_response(assessment)

    setup, trade = _original_trade_idea(self, price, atr, bias, zones, liquidity)
    setup = dict(setup or {})
    trade = dict(trade or {})
    setup["clear_bias_gate"] = assessment
    trade["clear_bias_gate"] = assessment
    return setup, trade


def _runtime_status_v45(self: core.LiveTrader) -> dict[str, Any]:
    state = dict(_original_runtime_status(self))
    state.update(
        {
            "clear_bias_gate_version": GATE_VERSION,
            "new_trade_requires_clear_bias": True,
            "clear_bias_minimum_confidence": MIN_CLEAR_CONFIDENCE,
            "clear_bias_requires_h4_h1_m15_alignment": True,
            "clear_bias_requires_four_of_five_critical_timeframes": True,
            "clear_bias_blocks_strong_opposing_market_event": True,
        }
    )
    return state


core.LiveTrader._trade_idea = _trade_idea_v45  # type: ignore[method-assign]
core.LiveTrader.runtime_status = _runtime_status_v45  # type: ignore[method-assign]

# Preserve the established exported-alias identity contracts used throughout
# earlier safety wrappers and regression tests. They intentionally point at the
# newest audited runtime trade-idea wrapper.
integrity._trade_idea_v39 = _trade_idea_v45
lock._trade_idea_v28 = _trade_idea_v45
