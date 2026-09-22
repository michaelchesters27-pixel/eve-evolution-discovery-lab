from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from app.services import live_trader as core
from app.services import live_trader_historical_runtime_v30 as historical_runtime
from app.services import live_trader_policy_lab_v85 as policy_lab
from app.services import live_trader_trade_lock_v28 as lock
from app.services import live_trader_trade_outcomes_v38 as outcomes
from app.services import live_trader_zone_retrace_current_policy_academy_v71 as academy
from app.services import live_trader_zone_retrace_integrity_v64 as v64
from app.services import live_trader_zone_retrace_specialist_v58 as v58

VERSION = "eve-live-authoritative-state-v94"
TELEMETRY_VERSION = "eve-bounded-stage-telemetry-v1"
ACADEMY_CACHE_SECONDS = 10.0
TELEMETRY_CACHE_SECONDS = 60.0
FINAL_PERSIST_SECONDS = 10.0

_current_refresh_state = core.LiveTrader.refresh_state
_current_learning_summary = core.LiveTrader.learning_summary
_current_runtime_status = core.LiveTrader.runtime_status
_current_maybe_persist_state = core.LiveTrader._maybe_persist_state


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


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


async def _academy_snapshot(self: core.LiveTrader, *, force: bool = False) -> dict[str, Any]:
    now = _utc_now()
    cached_at = getattr(self, "_authoritative_academy_at_v94", None)
    cached = getattr(self, "_authoritative_academy_v94", None)
    if (
        not force
        and isinstance(cached_at, datetime)
        and isinstance(cached, dict)
        and now - cached_at < timedelta(seconds=ACADEMY_CACHE_SECONDS)
    ):
        return dict(cached)

    identity = academy._academy_identity(self.settings)
    cohort_id = str(identity["cohort_id"])
    try:
        rows = await self.repo.client.get(
            "live_trader_zone_retrace_current_policy_cohort_state",
            params={
                "select": "*",
                "cohort_id": f"eq.{cohort_id}",
                "limit": "1",
            },
        )
        state = dict(rows[0] or {}) if rows else {}
        result = {
            "read_ok": True,
            "available": bool(state),
            "expected_cohort_id": cohort_id,
            "state": state,
            "reason": None if state else "current cohort has not produced a persisted academy state yet",
        }
    except Exception as exc:
        result = {
            "read_ok": False,
            "available": False,
            "expected_cohort_id": cohort_id,
            "state": {},
            "reason": str(exc)[:500],
        }

    self._authoritative_academy_at_v94 = now
    self._authoritative_academy_v94 = dict(result)
    return result


async def _stage_telemetry_snapshot(self: core.LiveTrader, *, force: bool = False) -> dict[str, Any]:
    now = _utc_now()
    cached_at = getattr(self, "_bounded_stage_telemetry_at_v94", None)
    cached = getattr(self, "_bounded_stage_telemetry_v94", None)
    if (
        not force
        and isinstance(cached_at, datetime)
        and isinstance(cached, dict)
        and now - cached_at < timedelta(seconds=TELEMETRY_CACHE_SECONDS)
    ):
        return dict(cached)

    try:
        cycles = await self.repo.client.get(
            "bounded_research_cycles",
            params={
                "select": "cycle_id,worker_pid,started_at,finished_at,outcome,stages_total,stages_progressed,stages_no_op,stages_completed,stages_failed,elapsed_ms,result_summary",
                "order": "started_at.desc",
                "limit": "1",
            },
        )
        if not cycles:
            result = {
                "version": TELEMETRY_VERSION,
                "read_ok": True,
                "available": False,
                "cycle": None,
                "stages": [],
                "note": "No Fix-8 bounded cycle has completed or started yet.",
            }
        else:
            cycle = dict(cycles[0] or {})
            cycle_id = str(cycle.get("cycle_id") or "")
            stages = await self.repo.client.get(
                "bounded_research_stage_runs",
                params={
                    "select": "stage_name,ordinal,outcome,operation_ok,started_at,finished_at,elapsed_ms,cpu_user_ms,cpu_system_ms,process_max_rss_mb,result_summary,error",
                    "cycle_id": f"eq.{cycle_id}",
                    "order": "ordinal.asc",
                    "limit": "20",
                },
            )
            result = {
                "version": TELEMETRY_VERSION,
                "read_ok": True,
                "available": True,
                "cycle": cycle,
                "stages": list(stages or []),
                "success_label_policy": (
                    "Only outcome=progressed means measured work advanced. no_op is reported explicitly; "
                    "completed means the operation returned without an exposed measurable work counter."
                ),
            }
    except Exception as exc:
        result = {
            "version": TELEMETRY_VERSION,
            "read_ok": False,
            "available": False,
            "cycle": None,
            "stages": [],
            "reason": str(exc)[:500],
        }

    self._bounded_stage_telemetry_at_v94 = now
    self._bounded_stage_telemetry_v94 = dict(result)
    return result


def _synchronise_specialist(
    self: core.LiveTrader,
    state: dict[str, Any],
    academy_result: dict[str, Any],
) -> None:
    current = dict(
        state.get("zone_retrace_learning")
        or (state.get("learning") or {}).get("zone_retrace_specialist")
        or getattr(self, "_zone_retrace_learning_v58", {})
        or {}
    )
    academy_state = dict(academy_result.get("state") or {})
    if academy_state:
        current["current_policy_academy"] = academy_state
    elif academy_result.get("read_ok") and not current.get("current_policy_academy"):
        current["current_policy_academy"] = {}

    if current:
        current = v64._audited_specialist(current)
        self._zone_retrace_learning_v58 = dict(current)
        state["zone_retrace_learning"] = dict(current)
        learning = dict(state.get("learning") or {})
        learning["zone_retrace_specialist"] = dict(current)
        learning["strategy_specialist"] = dict(current)
        state["learning"] = learning


def _authority_metadata(
    academy_result: dict[str, Any],
    policy_summary: dict[str, Any],
    telemetry: dict[str, Any],
) -> dict[str, Any]:
    academy_state = dict(academy_result.get("state") or {})
    completeness = dict(policy_summary.get("summary_completeness") or {})
    cycle = dict(telemetry.get("cycle") or {})
    return {
        "version": VERSION,
        "authoritative": True,
        "assembled_after_all_runtime_wrappers": True,
        "persisted_after_all_runtime_wrappers": True,
        "current_policy_academy_source": "live_trader_zone_retrace_current_policy_cohort_state",
        "current_policy_academy_read_ok": bool(academy_result.get("read_ok")),
        "current_policy_academy_cohort_id": academy_result.get("expected_cohort_id"),
        "current_policy_academy_status": academy_state.get("status") if academy_state else "waiting_for_first_scan",
        "current_policy_academy_updated_at": academy_state.get("updated_at"),
        "policy_lab_summary_source": completeness.get("source") or "server_side_sql_aggregation",
        "policy_lab_summary_complete": completeness.get("complete") is True,
        "policy_lab_summary_rolling": completeness.get("rolling"),
        "policy_lab_health_present": True,
        "bounded_stage_telemetry_version": TELEMETRY_VERSION,
        "bounded_stage_telemetry_read_ok": bool(telemetry.get("read_ok")),
        "bounded_stage_cycle_id": cycle.get("cycle_id"),
        "bounded_stage_cycle_outcome": cycle.get("outcome"),
        "assembled_at": _utc_now().isoformat(),
    }


async def _persist_final_state(self: core.LiveTrader, state: dict[str, Any], *, force: bool = False) -> None:
    now = _utc_now()
    last = getattr(self, "_last_authoritative_persist_at_v94", None)
    if not force and isinstance(last, datetime) and now - last < timedelta(seconds=FINAL_PERSIST_SECONDS):
        return
    try:
        await self.repo.client.upsert(
            "live_trader_state",
            {
                "symbol": self.symbol,
                "state": state,
                "updated_at": now.isoformat(),
            },
            on_conflict="symbol",
            return_rows=False,
        )
        self._last_authoritative_persist_at_v94 = now
        # Keep the original throttle clock aligned so any out-of-band call to the
        # older persistence hook cannot immediately overwrite the final state.
        self._last_persist_at = now
        self._authoritative_state_last_error_v94 = None
    except Exception as exc:
        self._authoritative_state_last_error_v94 = str(exc)[:500]
        core.logger.warning("Live Trader v94 could not persist authoritative final state: %s", exc)


async def _maybe_persist_state_v94(self: core.LiveTrader, state: dict[str, Any]) -> None:
    # The inner core refresh calls this before v83/v85/v91 have finished adding
    # their fields. During a top-level v94 refresh, defer that stale write and let
    # v94 persist once after the complete wrapper chain is assembled.
    if bool(getattr(self, "_authoritative_refresh_active_v94", False)):
        self._authoritative_pending_state_v94 = state
        return
    await _current_maybe_persist_state(self, state)


async def _refresh_state_v94(self: core.LiveTrader, *, force_rows: bool = False) -> dict[str, Any]:
    self._authoritative_refresh_active_v94 = True
    try:
        state = dict(await _current_refresh_state(self, force_rows=force_rows))
    finally:
        self._authoritative_refresh_active_v94 = False

    academy_result = await _academy_snapshot(self)
    _synchronise_specialist(self, state, academy_result)

    policy_summary = await policy_lab._policy_lab_summary(self)
    policy_health = dict(state.get("policy_lab_health") or {})
    policy_health.update(
        {
            "authoritative_state_version": VERSION,
            "summary_status": policy_summary.get("status") or "ok",
            "summary_complete": bool((policy_summary.get("summary_completeness") or {}).get("complete")),
            "summary_version": policy_summary.get("summary_version") or policy_lab.SUMMARY_VERSION,
        }
    )
    state["policy_lab_health"] = policy_health

    learning = dict(state.get("learning") or {})
    learning["policy_lab"] = dict(policy_summary)
    learning["policy_lab_health"] = dict(policy_health)
    state["learning"] = learning

    academy_state = dict(academy_result.get("state") or {})
    state["zone_retrace_current_policy_academy"] = academy_state or {
        "academy_version": academy.ACADEMY_VERSION,
        "cohort_id": academy_result.get("expected_cohort_id"),
        "status": "waiting_for_first_scan" if academy_result.get("read_ok") else "state_read_error",
        "read_error": None if academy_result.get("read_ok") else academy_result.get("reason"),
    }

    telemetry = await _stage_telemetry_snapshot(self)
    state["bounded_research_telemetry"] = telemetry
    state["state_authority"] = _authority_metadata(academy_result, policy_summary, telemetry)

    self._latest_state = state
    await _persist_final_state(self, state)
    return state


async def _learning_summary_v94(self: core.LiveTrader) -> dict[str, Any]:
    summary = dict(await _current_learning_summary(self))
    academy_result = await _academy_snapshot(self)
    academy_state = dict(academy_result.get("state") or {})
    if academy_state:
        specialist = dict(summary.get("zone_retrace_specialist") or {})
        specialist["current_policy_academy"] = academy_state
        summary["zone_retrace_specialist"] = v64._audited_specialist(specialist)
    summary["zone_retrace_current_policy_academy"] = academy_state or {
        "academy_version": academy.ACADEMY_VERSION,
        "cohort_id": academy_result.get("expected_cohort_id"),
        "status": "waiting_for_first_scan" if academy_result.get("read_ok") else "state_read_error",
        "read_error": None if academy_result.get("read_ok") else academy_result.get("reason"),
    }
    summary["bounded_research_telemetry"] = await _stage_telemetry_snapshot(self)
    summary["state_authority"] = dict((self._latest_state or {}).get("state_authority") or {})
    return summary


def _runtime_status_v94(self: core.LiveTrader) -> dict[str, Any]:
    status = dict(_current_runtime_status(self))
    authority = dict((getattr(self, "_latest_state", {}) or {}).get("state_authority") or {})
    telemetry = dict(getattr(self, "_bounded_stage_telemetry_v94", {}) or {})
    cycle = dict(telemetry.get("cycle") or {})
    academy_result = dict(getattr(self, "_authoritative_academy_v94", {}) or {})
    academy_state = dict(academy_result.get("state") or {})
    status.update(
        {
            "authoritative_state_version": VERSION,
            "authoritative_state_final_wrapper": True,
            "authoritative_state_persisted_after_all_wrappers": True,
            "authoritative_state_last_error": getattr(self, "_authoritative_state_last_error_v94", None),
            "authoritative_current_policy_source": "persisted_cohort_state",
            "authoritative_current_policy_status": academy_state.get("status") or authority.get("current_policy_academy_status"),
            "authoritative_current_policy_cohort_id": (
                academy_state.get("cohort_id")
                or academy_result.get("expected_cohort_id")
                or authority.get("current_policy_academy_cohort_id")
            ),
            "policy_lab_health_persisted_in_final_state": True,
            "bounded_stage_telemetry_version": TELEMETRY_VERSION,
            "bounded_stage_latest_cycle_id": cycle.get("cycle_id"),
            "bounded_stage_latest_cycle_outcome": cycle.get("outcome"),
            "bounded_stage_no_op_is_not_progress": True,
        }
    )
    return status


core.LiveTrader._maybe_persist_state = _maybe_persist_state_v94  # type: ignore[method-assign]
core.LiveTrader.refresh_state = _refresh_state_v94  # type: ignore[method-assign]
core.LiveTrader.learning_summary = _learning_summary_v94  # type: ignore[method-assign]
core.LiveTrader.runtime_status = _runtime_status_v94  # type: ignore[method-assign]

# Keep every compatibility alias pointing to the same final authoritative refresh.
lock._maybe_persist_state_v28 = _maybe_persist_state_v94
lock._refresh_state_v28 = _refresh_state_v94
historical_runtime._refresh_state_v30 = _refresh_state_v94
outcomes._refresh_v38 = _refresh_state_v94
v58._refresh_state_v58 = _refresh_state_v94
v64.v58._refresh_state_v58 = _refresh_state_v94
v64.historical_runtime._refresh_state_v30 = _refresh_state_v94
v64.outcomes._refresh_v38 = _refresh_state_v94
