from __future__ import annotations

import time
from typing import Any

from app.services import live_trader_zone_retrace_current_policy_academy_v71 as v71

VERSION = "eve-live-current-policy-throughput-v102"
BOUNDED_ROW_BUDGET = 18000
BOUNDED_TIME_BUDGET_SECONDS = 240.0
SCAN_BATCH_ROWS = 900

# Increase only the archive page size. This does not change opportunity,
# execution, target, cost, evidence or promotion semantics.
v71.SCAN_BATCH_ROWS = SCAN_BATCH_ROWS


def _num(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


async def run_bounded_stage(worker: v71.CurrentPolicyZoneRetraceAcademy) -> dict[str, Any]:
    """Advance the exact current-policy archive in many durable small batches.

    Each underlying run_cycle persists its cursor/state before this helper moves
    to the next batch. A restart therefore resumes from the last durable cursor.
    Row and wall-clock budgets bound cost without changing research semantics.
    """

    started = time.monotonic()
    initial = dict(await worker._state())
    initial_rows = int(_num(initial.get("rows_scanned")))
    initial_opportunities = int(_num(initial.get("opportunities_found")))
    batches = 0
    last = initial
    no_progress_streak = 0

    while True:
        elapsed = time.monotonic() - started
        rows_advanced = max(0, int(_num(last.get("rows_scanned"))) - initial_rows)
        if rows_advanced >= BOUNDED_ROW_BUDGET or elapsed >= BOUNDED_TIME_BUDGET_SECONDS:
            break
        if bool(last.get("caught_up")):
            break

        before_rows = int(_num(last.get("rows_scanned")))
        before_cursor = str(last.get("cursor_time") or "")
        result = await worker.run_cycle()
        batches += 1
        last = dict(await worker._state())

        after_rows = int(_num(last.get("rows_scanned")))
        after_cursor = str(last.get("cursor_time") or "")
        if result is False or bool(last.get("caught_up")):
            break

        if after_rows <= before_rows and after_cursor == before_cursor:
            no_progress_streak += 1
            if no_progress_streak >= 2:
                break
        else:
            no_progress_streak = 0

    elapsed = time.monotonic() - started
    final_rows = int(_num(last.get("rows_scanned")))
    final_opportunities = int(_num(last.get("opportunities_found")))
    rows_advanced = max(0, final_rows - initial_rows)
    opportunities_added = max(0, final_opportunities - initial_opportunities)
    caught_up = bool(last.get("caught_up"))

    if caught_up:
        status = "caught_up"
    elif rows_advanced > 0 or opportunities_added > 0:
        status = "progressed"
    else:
        status = "no_op"

    return {
        "ok": True,
        "status": status,
        "rows": rows_advanced,
        "rows_scanned": final_rows,
        "opportunities_found": final_opportunities,
        "opportunities_added": opportunities_added,
        "cursor_time": last.get("cursor_time"),
        "caught_up": caught_up,
        "batches": batches,
        "scan_batch_rows": SCAN_BATCH_ROWS,
        "row_budget": BOUNDED_ROW_BUDGET,
        "time_budget_seconds": BOUNDED_TIME_BUDGET_SECONDS,
        "elapsed_seconds": round(elapsed, 3),
        "throughput_version": VERSION,
        "durable_checkpoint_each_batch": True,
        "trading_rules_changed": False,
        "evidence_semantics_changed": False,
    }
