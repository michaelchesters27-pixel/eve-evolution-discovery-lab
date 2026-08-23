from __future__ import annotations

from typing import Any

from app.services import live_trader as core
from app.services import live_trader_execution_integrity_v39 as integrity
from app.services import live_trader_learning_v2 as v2

EXECUTION_SCHEMA = "causal-m1-invalidation-aware-v3"
REGRADER_VERSION = "eve-live-historical-execution-regrade-v2"
_old_scorer = integrity._trade_path_result_v39
_old_regrader_state = integrity.HistoricalExecutionRegrader._state


def _limit_path_result(trade: dict[str, Any], bars: list[dict[str, Any]], resolved_price: float) -> dict[str, Any]:
    order_type = str(trade.get("order_type") or "none").lower()
    side = str(trade.get("side") or "").upper()
    entry = core.number(trade.get("entry"))
    stop = core.number(trade.get("stop"))
    target = core.number(trade.get("target"))
    risk = abs(entry - stop)
    if side not in {"BUY", "SELL"} or entry <= 0 or stop <= 0 or target <= 0 or risk <= 0:
        return {"entry_triggered": False, "trade_outcome": "invalid", "realised_r": None, "learning_success": None}

    triggered = False
    for bar in bars:
        open_price = core.number(bar.get("open"))
        low = core.number(bar.get("low"))
        high = core.number(bar.get("high"))
        if not triggered:
            if order_type == "buy_limit":
                triggered = (0 < open_price <= entry) or low <= entry
            elif order_type == "sell_limit":
                triggered = open_price >= entry > 0 or high >= entry
        if not triggered:
            continue

        # This matches the locked campaign state machine. A LIMIT crossing through
        # entry and stop is exposure followed by a stop, not a free cancellation.
        if side == "BUY":
            stop_hit = low <= stop
            target_hit = high >= target
        else:
            stop_hit = high >= stop
            target_hit = low <= target
        if stop_hit:
            return {"entry_triggered": True, "trade_outcome": "stop", "realised_r": -1.0, "learning_success": False}
        if target_hit:
            rr = abs(target - entry) / risk
            return {"entry_triggered": True, "trade_outcome": "target", "realised_r": round(rr, 3), "learning_success": True}

    if not triggered:
        return {"entry_triggered": False, "trade_outcome": "not_triggered", "realised_r": 0.0, "learning_success": None}

    mtm_r = (resolved_price - entry) / risk if side == "BUY" else (entry - resolved_price) / risk
    mtm_r = round(core.clamp(mtm_r, -1.0, max(core.number(trade.get("risk_reward")), 3.0)), 3)
    if mtm_r >= 0.15:
        return {"entry_triggered": True, "trade_outcome": "expired_win", "realised_r": mtm_r, "learning_success": True}
    if mtm_r <= -0.15:
        return {"entry_triggered": True, "trade_outcome": "expired_loss", "realised_r": mtm_r, "learning_success": False}
    return {"entry_triggered": True, "trade_outcome": "expired_flat", "realised_r": mtm_r, "learning_success": None}


def _trade_path_result_v41(trade: dict[str, Any], bars: list[dict[str, Any]], resolved_price: float) -> dict[str, Any]:
    order_type = str(trade.get("order_type") or "none").lower()
    if order_type in {"buy_limit", "sell_limit"}:
        return _limit_path_result(trade, bars, resolved_price)
    return _old_scorer(trade, bars, resolved_price)


async def _state_v41(self: integrity.HistoricalExecutionRegrader) -> dict[str, Any]:
    state = await _old_regrader_state(self)
    if state and str(state.get("version") or "") != REGRADER_VERSION:
        # A scorer-policy change invalidates the old cursor. Regrade from the first
        # historical episode again rather than mixing two execution schemas.
        return {}
    return state


integrity.EXECUTION_SCHEMA = EXECUTION_SCHEMA
integrity.REGRADER_VERSION = REGRADER_VERSION
integrity._trade_path_result_v39 = _trade_path_result_v41
integrity.HistoricalExecutionRegrader._state = _state_v41
v2._trade_path_result = _trade_path_result_v41
