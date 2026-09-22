from __future__ import annotations

import asyncio
import json
import logging
import os
import resource
import sys
import time
import uuid
from datetime import datetime, timezone
from typing import Any, Awaitable, Callable

from app.settings import get_settings
from app.services.fabric_builder import FabricBuilder
from app.services.evidence_director import EvidenceDirectedIntelligenceDirector as IntelligenceDirector
from app.services.live_trader import LiveTrader
from app.services.live_trader_historical_learning_v29 import LiveTraderHistoricalLearner
from app.services.live_trader_zone_retrace_live_policy_replay_v68 import ZoneRetraceLivePolicyReplayer
from app.services.live_trader_zone_retrace_current_policy_academy_v71 import CurrentPolicyZoneRetraceAcademy
from app.services.orchestrator_v3 import DiscoveryOrchestrator
from app.services.repository import DiscoveryRepository, SourceRepository
from app.services import mtf_reasoning as _mtf_reasoning  # noqa: F401

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

TELEMETRY_VERSION = "eve-bounded-stage-telemetry-v1"

_PROGRESS_COUNTERS = (
    "rows",
    "written",
    "imported",
    "signals",
    "hypotheses_queued",
    "episodes",
    "episodes_recorded",
    "processed_episodes",
    "opportunities_found",
)
_FAILURE_STATUSES = {"error", "failed", "failure", "unavailable"}
_NO_OP_STATUSES = {
    "idle",
    "no_op",
    "noop",
    "caught_up",
    "waiting",
    "no_candidate",
    "no_work",
    "empty",
}


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _summary(value: Any) -> Any:
    if isinstance(value, bool) or value is None:
        return value
    if isinstance(value, (str, int, float)):
        return value
    if isinstance(value, dict):
        keep = (
            "ok",
            "status",
            "reason",
            "actions",
            "rows",
            "episodes",
            "scored",
            "challengers",
            "imported",
            "written",
            "signals",
            "hypotheses_queued",
            "dataset_rows",
            "caught_up",
            "episodes_recorded",
            "processed_episodes",
            "opportunities_found",
            "cursor_time",
        )
        return {key: value.get(key) for key in keep if key in value}
    return str(type(value).__name__)


def _classify_stage_result(value: Any) -> str:
    """Classify work honestly instead of treating every non-exception as progress."""
    if value is False or value is None:
        return "no_op"
    if value is True:
        return "progressed"
    if not isinstance(value, dict):
        return "completed"

    status = str(value.get("status") or "").strip().lower()
    if value.get("ok") is False or status in _FAILURE_STATUSES:
        return "failed"

    actions = value.get("actions")
    if isinstance(actions, (list, tuple, dict, set)) and len(actions) > 0:
        return "progressed"
    if isinstance(actions, str) and actions.strip():
        return "progressed"

    for key in _PROGRESS_COUNTERS:
        raw = value.get(key)
        if isinstance(raw, bool):
            if raw:
                return "progressed"
            continue
        try:
            if raw is not None and float(raw) > 0:
                return "progressed"
        except (TypeError, ValueError):
            pass

    if status in _NO_OP_STATUSES or bool(value.get("caught_up")):
        return "no_op"
    return "completed"


def _usage() -> resource.struct_rusage:
    return resource.getrusage(resource.RUSAGE_SELF)


def _max_rss_mb(usage: resource.struct_rusage) -> float:
    # Linux ru_maxrss is KiB; macOS uses bytes. Production and CI are Linux,
    # but keep the conversion correct for local macOS development too.
    raw = float(usage.ru_maxrss)
    return raw / (1024.0 * 1024.0) if sys.platform == "darwin" else raw / 1024.0


async def _write_stage_telemetry(
    repo: DiscoveryRepository,
    *,
    cycle_id: str,
    stage_name: str,
    ordinal: int,
    outcome: str,
    operation_ok: bool,
    started_at: datetime,
    finished_at: datetime,
    elapsed_ms: float,
    cpu_user_ms: float,
    cpu_system_ms: float,
    process_max_rss_mb: float,
    result_summary: Any,
    error: str | None,
) -> None:
    try:
        await repo.client.insert(
            "bounded_research_stage_runs",
            {
                "cycle_id": cycle_id,
                "stage_name": stage_name,
                "ordinal": ordinal,
                "outcome": outcome,
                "operation_ok": operation_ok,
                "started_at": started_at.isoformat(),
                "finished_at": finished_at.isoformat(),
                "elapsed_ms": round(elapsed_ms, 3),
                "cpu_user_ms": round(cpu_user_ms, 3),
                "cpu_system_ms": round(cpu_system_ms, 3),
                "process_max_rss_mb": round(process_max_rss_mb, 3),
                "result_summary": result_summary if isinstance(result_summary, dict) else {"value": result_summary},
                "error": error,
            },
            return_rows=False,
        )
    except Exception:
        logger.exception("Could not persist bounded-worker stage telemetry for %s", stage_name)


async def _stage(
    name: str,
    ordinal: int,
    cycle_id: str,
    operation: Callable[[], Awaitable[Any]],
    repo: DiscoveryRepository,
) -> dict[str, Any]:
    started_at = _now()
    started_perf = time.perf_counter()
    before = _usage()
    try:
        result = await operation()
        summary = _summary(result)
        outcome = _classify_stage_result(result)
        operation_ok = outcome != "failed"
        error = None if operation_ok else str((result or {}).get("reason") or (result or {}).get("status") or "stage returned failure")[:2000]
        if outcome == "progressed":
            logger.info("Bounded EVE stage %s progressed: %s", name, summary)
        elif outcome == "no_op":
            logger.info("Bounded EVE stage %s completed with no work: %s", name, summary)
        elif outcome == "completed":
            logger.info("Bounded EVE stage %s completed; result exposes no measurable work counter: %s", name, summary)
        else:
            logger.error("Bounded EVE stage %s returned failure: %s", name, summary)
    except Exception as exc:
        result = None
        summary = None
        outcome = "failed"
        operation_ok = False
        error = str(exc)[:2000]
        logger.exception("Bounded EVE stage %s failed", name)
        try:
            await repo.event(
                "error",
                "bounded_worker",
                f"Bounded research stage {name} failed safely.",
                {"stage": name, "cycle_id": cycle_id, "error": error},
            )
        except Exception:
            logger.exception("Could not persist bounded-worker failure event")

    finished_at = _now()
    after = _usage()
    elapsed_ms = (time.perf_counter() - started_perf) * 1000.0
    await _write_stage_telemetry(
        repo,
        cycle_id=cycle_id,
        stage_name=name,
        ordinal=ordinal,
        outcome=outcome,
        operation_ok=operation_ok,
        started_at=started_at,
        finished_at=finished_at,
        elapsed_ms=elapsed_ms,
        cpu_user_ms=(after.ru_utime - before.ru_utime) * 1000.0,
        cpu_system_ms=(after.ru_stime - before.ru_stime) * 1000.0,
        process_max_rss_mb=_max_rss_mb(after),
        result_summary=summary,
        error=error,
    )
    payload = {
        "ok": operation_ok,
        "outcome": outcome,
        "result": summary,
        "elapsed_ms": round(elapsed_ms, 3),
        "cpu_user_ms": round((after.ru_utime - before.ru_utime) * 1000.0, 3),
        "cpu_system_ms": round((after.ru_stime - before.ru_stime) * 1000.0, 3),
        "process_max_rss_mb": round(_max_rss_mb(after), 3),
    }
    if error:
        payload["error"] = error
    return payload


async def run_once() -> dict[str, Any]:
    settings = get_settings()
    source = SourceRepository(settings)
    repo = DiscoveryRepository(settings)
    cycle_id = str(os.environ.get("EVE_BOUNDED_CYCLE_ID") or uuid.uuid4())
    cycle_started = _now()
    cycle_perf = time.perf_counter()

    try:
        await repo.client.insert(
            "bounded_research_cycles",
            {
                "cycle_id": cycle_id,
                "worker_pid": os.getpid(),
                "started_at": cycle_started.isoformat(),
                "outcome": "running",
                "result_summary": {"telemetry_version": TELEMETRY_VERSION},
            },
            return_rows=False,
        )
    except Exception:
        logger.exception("Could not persist bounded-worker cycle start telemetry")

    orchestrator = DiscoveryOrchestrator(settings, source, repo)
    intelligence = IntelligenceDirector(settings, repo, orchestrator.rows)
    fabric = FabricBuilder(settings, source, repo)
    live = LiveTrader(settings, repo)
    historical = LiveTraderHistoricalLearner(settings, source, repo)
    replay = ZoneRetraceLivePolicyReplayer(live)
    current_policy = CurrentPolicyZoneRetraceAcademy(live)

    results: dict[str, Any] = {}

    # Keep each expensive activity bounded to exactly one unit of work. The
    # process exits after this sequence, releasing every historical row/cache.
    results["fabric"] = await _stage("fabric", 1, cycle_id, fabric.build_once, repo)
    results["discovery"] = await _stage("discovery", 2, cycle_id, orchestrator.run_once, repo)

    async def scientist_cycle() -> Any:
        rows = await orchestrator.rows()
        return await intelligence.run_science_once(rows)

    results["scientist"] = await _stage("scientist", 3, cycle_id, scientist_cycle, repo)
    results["historical_academy"] = await _stage("historical_academy", 4, cycle_id, historical.learn_cycle, repo)
    results["zone_replay"] = await _stage("zone_replay", 5, cycle_id, replay.run_batch, repo)
    results["current_policy"] = await _stage("current_policy", 6, cycle_id, current_policy.run_cycle, repo)

    progressed = sum(1 for item in results.values() if item.get("outcome") == "progressed")
    no_op = sum(1 for item in results.values() if item.get("outcome") == "no_op")
    completed = sum(1 for item in results.values() if item.get("outcome") == "completed")
    failed = sum(1 for item in results.values() if item.get("outcome") == "failed")

    if failed:
        cycle_outcome = "failed"
    elif progressed:
        cycle_outcome = "completed_with_progress"
    elif completed:
        cycle_outcome = "completed_without_measured_progress"
    else:
        cycle_outcome = "completed_no_op"

    cycle_finished = _now()
    elapsed_ms = (time.perf_counter() - cycle_perf) * 1000.0
    compact = {
        "telemetry_version": TELEMETRY_VERSION,
        "stage_outcomes": {name: item.get("outcome") for name, item in results.items()},
    }
    try:
        await repo.client.patch(
            "bounded_research_cycles",
            {
                "finished_at": cycle_finished.isoformat(),
                "outcome": cycle_outcome,
                "stages_total": len(results),
                "stages_progressed": progressed,
                "stages_no_op": no_op,
                "stages_completed": completed,
                "stages_failed": failed,
                "elapsed_ms": round(elapsed_ms, 3),
                "result_summary": compact,
                "updated_at": cycle_finished.isoformat(),
            },
            filters={"cycle_id": f"eq.{cycle_id}"},
        )
    except Exception:
        logger.exception("Could not persist bounded-worker cycle completion telemetry")

    try:
        await repo.event(
            "error" if failed else "info",
            "bounded_worker",
            (
                f"Bounded research cycle {cycle_outcome}: "
                f"{progressed} progressed, {no_op} no-op, {completed} completed without measured progress, {failed} failed."
            ),
            {
                "cycle_id": cycle_id,
                "telemetry_version": TELEMETRY_VERSION,
                "outcome": cycle_outcome,
                "stages": results,
            },
        )
    except Exception:
        logger.exception("Could not persist bounded-worker completion event")

    return {
        "ok": failed == 0,
        "cycle_id": cycle_id,
        "outcome": cycle_outcome,
        "progressed": progressed,
        "no_op": no_op,
        "completed": completed,
        "failed": failed,
        "elapsed_ms": round(elapsed_ms, 3),
        "stages": results,
    }


if __name__ == "__main__":
    result = asyncio.run(run_once())
    print(json.dumps(result, sort_keys=True, default=str))
    if not result.get("ok"):
        raise SystemExit(1)
