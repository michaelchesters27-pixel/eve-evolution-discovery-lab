from __future__ import annotations

from typing import Any

from app.services import live_trader as core
from app.services import live_trader_execution_cost_model as cost_model
from app.services import live_trader_execution_integrity_v39 as integrity
from app.services import live_trader_execution_sequence_v41 as v41
from app.services import live_trader_execution_sequence_v88 as v88
from app.services import live_trader_learning_v2 as v2

EXECUTION_SCHEMA = "causal-m1-invalidation-aware-cost-v5"
REGRADER_VERSION = "eve-live-historical-execution-regrade-v4"

_gross_scorer = v88._trade_path_result_v88
_current_runtime_status = core.LiveTrader.runtime_status


def _trade_path_result_v90(
    trade: dict[str, Any],
    bars: list[dict[str, Any]],
    resolved_price: float,
) -> dict[str, Any]:
    gross = _gross_scorer(trade, bars, resolved_price)
    return cost_model.apply_cost_model(trade, gross, bars)


def _runtime_status_v90(self: core.LiveTrader) -> dict[str, Any]:
    status = dict(_current_runtime_status(self))
    profile = cost_model.profile_from_settings(self.settings)
    status["execution_cost_model"] = {
        **profile,
        "gross_r_preserved": True,
        "net_r_used_for_forward_trade_skill": True,
        "net_r_used_for_policy_lab_qualification": True,
        "manual_fill_ledger_separate": True,
    }
    status["causal_execution_schema"] = EXECUTION_SCHEMA
    return status


# A cost-model/scoring change invalidates the historical execution regrade cursor.
# The v41 state wrapper reads these globals dynamically, so v4 restarts cleanly.
v41.EXECUTION_SCHEMA = EXECUTION_SCHEMA
v41.REGRADER_VERSION = REGRADER_VERSION
v88.EXECUTION_SCHEMA = EXECUTION_SCHEMA
v88.REGRADER_VERSION = REGRADER_VERSION
integrity.EXECUTION_SCHEMA = EXECUTION_SCHEMA
integrity.REGRADER_VERSION = REGRADER_VERSION
integrity._trade_path_result_v39 = _trade_path_result_v90
v2._trade_path_result = _trade_path_result_v90
core.LiveTrader.runtime_status = _runtime_status_v90  # type: ignore[method-assign]
