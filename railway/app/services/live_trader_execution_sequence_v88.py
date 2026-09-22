from __future__ import annotations

from typing import Any

from app.services import live_trader as core
from app.services import live_trader_execution_integrity_v39 as integrity
from app.services import live_trader_execution_sequence_v41 as v41
from app.services import live_trader_learning_v2 as v2

EXECUTION_SCHEMA = "causal-m1-invalidation-aware-v4"
REGRADER_VERSION = "eve-live-historical-execution-regrade-v3"


def _with_ambiguity(result: dict[str, Any], seen: bool) -> dict[str, Any]:
    if seen:
        result = dict(result)
        result["entry_target_same_bar_ambiguous"] = True
        result["entry_target_ambiguity_policy"] = (
            "No target credit on an intrabar limit-fill candle unless post-fill target traversal is provable from the close; "
            "otherwise exposure carries forward to later bars."
        )
    return result


def _limit_path_result_v88(
    trade: dict[str, Any],
    bars: list[dict[str, Any]],
    resolved_price: float,
) -> dict[str, Any]:
    """Conservatively score LIMIT entries when M1 OHLC cannot prove event order.

    The prior scorer correctly assumed stop-first after exposure, but it could still
    award a target on the first fill candle when that target may have occurred
    before the limit entry.  This scorer never grants that optimistic credit.

    If the order was already marketable at the candle open, exposure is proven from
    the open.  For an intrabar fill, a same-candle target is credited only when the
    candle close itself proves that price traversed from the entry to/through the
    target after the fill.  Otherwise the trade remains exposed and is evaluated on
    subsequent bars (or marked to market at the horizon).
    """

    order_type = str(trade.get("order_type") or "none").lower()
    side = str(trade.get("side") or "").upper()
    entry = core.number(trade.get("entry"))
    stop = core.number(trade.get("stop"))
    target = core.number(trade.get("target"))
    risk = abs(entry - stop)
    if side not in {"BUY", "SELL"} or entry <= 0 or stop <= 0 or target <= 0 or risk <= 0:
        return {
            "entry_triggered": False,
            "trade_outcome": "invalid",
            "realised_r": None,
            "learning_success": None,
        }

    triggered = False
    ambiguity_seen = False

    for bar in bars:
        open_price = core.number(bar.get("open"))
        low = core.number(bar.get("low"))
        high = core.number(bar.get("high"))
        close = core.number(bar.get("close"))

        first_fill_bar = False
        filled_at_open = False

        if not triggered:
            if order_type == "buy_limit":
                filled_at_open = 0 < open_price <= entry
                entry_hit = filled_at_open or low <= entry
            elif order_type == "sell_limit":
                filled_at_open = open_price >= entry > 0
                entry_hit = filled_at_open or high >= entry
            else:
                entry_hit = False

            if not entry_hit:
                continue

            triggered = True
            first_fill_bar = True

        if side == "BUY":
            stop_hit = low <= stop
            target_hit = high >= target
        else:
            stop_hit = high >= stop
            target_hit = low <= target

        # Adverse ambiguity remains stop-first once exposure exists.
        if stop_hit:
            return _with_ambiguity(
                {
                    "entry_triggered": True,
                    "trade_outcome": "stop",
                    "realised_r": -1.0,
                    "learning_success": False,
                },
                ambiguity_seen,
            )

        if target_hit:
            target_proven_after_entry = True
            if first_fill_bar and not filled_at_open:
                # With only OHLC, H/L order is unknown.  The close can prove a
                # post-entry traversal: after a BUY limit fill at the low side,
                # close >= target requires price to cross target afterwards; the
                # SELL case is symmetric.
                target_proven_after_entry = close >= target if side == "BUY" else close <= target
                if not target_proven_after_entry:
                    ambiguity_seen = True

            if target_proven_after_entry:
                rr = abs(target - entry) / risk
                return _with_ambiguity(
                    {
                        "entry_triggered": True,
                        "trade_outcome": "target",
                        "realised_r": round(rr, 3),
                        "learning_success": True,
                    },
                    ambiguity_seen,
                )

    if not triggered:
        return {
            "entry_triggered": False,
            "trade_outcome": "not_triggered",
            "realised_r": 0.0,
            "learning_success": None,
        }

    mtm_r = (resolved_price - entry) / risk if side == "BUY" else (entry - resolved_price) / risk
    mtm_r = round(core.clamp(mtm_r, -1.0, max(core.number(trade.get("risk_reward")), 3.0)), 3)
    if mtm_r >= 0.15:
        outcome = "expired_win"
        success: bool | None = True
    elif mtm_r <= -0.15:
        outcome = "expired_loss"
        success = False
    else:
        outcome = "expired_flat"
        success = None
    return _with_ambiguity(
        {
            "entry_triggered": True,
            "trade_outcome": outcome,
            "realised_r": mtm_r,
            "learning_success": success,
        },
        ambiguity_seen,
    )


def _trade_path_result_v88(
    trade: dict[str, Any],
    bars: list[dict[str, Any]],
    resolved_price: float,
) -> dict[str, Any]:
    order_type = str(trade.get("order_type") or "none").lower()
    if order_type in {"buy_limit", "sell_limit"}:
        return _limit_path_result_v88(trade, bars, resolved_price)
    return v41._old_scorer(trade, bars, resolved_price)


# A scorer-version change invalidates the old historical regrade cursor.  v41's
# state wrapper reads these module globals dynamically, so the existing bounded
# regrader restarts from the first historical episode under v3.
v41.EXECUTION_SCHEMA = EXECUTION_SCHEMA
v41.REGRADER_VERSION = REGRADER_VERSION
integrity.EXECUTION_SCHEMA = EXECUTION_SCHEMA
integrity.REGRADER_VERSION = REGRADER_VERSION
integrity._trade_path_result_v39 = _trade_path_result_v88
v2._trade_path_result = _trade_path_result_v88
