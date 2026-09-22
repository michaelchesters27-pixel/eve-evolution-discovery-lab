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

from app.services.resource_bounded_v97 import RESOURCE_VERSION


def _apply_memory_ceiling_from_env() -> int | None:
    raw = str(os.environ.get("EVE_BOUNDED_MEMORY_MB") or "").strip()
    if not raw:
        return None
    try:
        requested = int(raw)
    except ValueError:
        return None
    limit_mb = max(512, min(4096, requested))
    if sys.platform != "win32":
        limit_bytes = limit_mb * 1024 * 1024
        try:
            resource.setrlimit(resource.RLIMIT_AS, (limit_bytes, limit_bytes))
        except (ValueError, OSError) as exc:
            # A configured production ceiling is a safety contract, not advisory.
            # Never run a heavy stage unbounded because the OS refused RLIMIT_AS.
            raise RuntimeError(f"could_not_enforce_bounded_memory_ceiling:{exc}") from exc
    else:
        # Windows development cannot enforce RLIMIT_AS. Production is Linux.
        return None
    return limit_mb


MEMORY_CEILING_MB = _apply_memory_ceiling_from_env()

# Apply the address-space ceiling before importing the heavy research modules.
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

STAGES: tuple[tuple[str, int], ...] = (
    ("fabric", 1),
    ("discovery", 2),
    ("scientist", 3),
    ("historical_academy", 4),
    ("zone_replay", 5),
    ("current_policy", 6),
)

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
        result = {key: value.get(key) for key in keep if key in value}
        result["resource_version"] = RESOURCE_VERSION
        result["memory_ceiling_mb"] = MEMORY_CEILING_MB
        return result
    return str(type(value).__name__)


def _classify_stage_result(value: Any) -> str:
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
) -> int | None:
    try:
        summary = result_summary if isinstance(result_summary, dict) else {"value": result_summary}
        summary = {
            **summary,
            "resource_version": RESOURCE_VERSION,
            "memory_ceiling_mb": MEMORY_CEILING_MB,
            "pid": os.getpid(),
        }
        inserted = await repo.client.insert(
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
                "result_summary": summary,
                "error": error,
            },
            return_rows=True,
        )
        if inserted and isinstance(inserted[0], dict) and inserted[0].get("id") is not None:
            return int(inserted[0]["id"])
        return None
    except Exception:
        logger.exception("Could not persist bounded-worker stage telemetry for %s", stage_name)
        return None


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
    except MemoryError as exc:
        result = None
        summary = None
        outcome = "failed"
        operation_ok = False
        error = f"memory_ceiling_exceeded_or_allocation_failed:{exc}"[:2000]
        logger.exception("Bounded EVE stage %s hit its memory ceiling", name)
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
    stage_run_id = await _write_stage_telemetry(
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
        "cycle_id": cycle_id,
        "stage": name,
        "ordinal": ordinal,
        "outcome": outcome,
        "result": summary,
        "elapsed_ms": round(elapsed_ms, 3),
        "cpu_user_ms": round((after.ru_utime - before.ru_utime) * 1000.0, 3),
        "cpu_system_ms": round((after.ru_stime - before.ru_stime) * 1000.0, 3),
        "process_max_rss_mb": round(_max_rss_mb(after), 3),
        "memory_ceiling_mb": MEMORY_CEILING_MB,
        "resource_version": RESOURCE_VERSION,
        "stage_run_id": stage_run_id,
        "memory_ceiling_enforced": MEMORY_CEILING_MB is not None,
    }
    if error:
        payload["error"] = error
    return payload


async def _operation_for_stage(
    stage_name: str,
    settings: Any,
    source: SourceRepository,
    repo: DiscoveryRepository,
) -> Callable[[], Awaitable[Any]]:
    if stage_name == "fabric":
        fabric = FabricBuilder(settings, source, repo)
        return fabric.build_once

    if stage_name == "discovery":
        orchestrator = DiscoveryOrchestrator(settings, source, repo)
        return orchestrator.run_once

    if stage_name == "scientist":
        orchestrator = DiscoveryOrchestrator(settings, source, repo)
        intelligence = IntelligenceDirector(settings, repo, orchestrator.rows)

        async def scientist_cycle() -> Any:
            return await intelligence.run_science_once()

        return scientist_cycle

    if stage_name == "historical_academy":
        historical = LiveTraderHistoricalLearner(settings, source, repo)
        return historical.learn_cycle

    if stage_name == "zone_replay":
        live = LiveTrader(settings, repo)
        replay = ZoneRetraceLivePolicyReplayer(live)
        return replay.run_batch

    if stage_name == "current_policy":
        live = LiveTrader(settings, repo)
        current_policy = CurrentPolicyZoneRetraceAcademy(live)
        return current_policy.run_cycle

    raise ValueError(f"Unknown bounded research stage: {stage_name}")


async def run_named_stage(stage_name: str, cycle_id: str, ordinal: int) -> dict[str, Any]:
    settings = get_settings()
    source = SourceRepository(settings)
    repo = DiscoveryRepository(settings)
    operation = await _operation_for_stage(stage_name, settings, source, repo)
    return await _stage(stage_name, ordinal, cycle_id, operation, repo)


async def run_once() -> dict[str, Any]:
    """Compatibility/test runner.

    Production v96 invokes one fresh process per stage. This function retains the
    old one-process sequence for local/admin regression tests only.
    """
    settings = get_settings()
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
                "result_summary": {
                    "telemetry_version": TELEMETRY_VERSION,
                    "resource_version": RESOURCE_VERSION,
                    "execution_mode": "compatibility_single_process",
                },
            },
            return_rows=False,
        )
    except Exception:
        logger.exception("Could not persist bounded-worker cycle start telemetry")

    results: dict[str, Any] = {}
    for stage_name, ordinal in STAGES:
        results[stage_name] = await run_named_stage(stage_name, cycle_id, ordinal)

    progressed = sum(1 for item in results.values() if item.get("outcome") == "progressed")
    no_op = sum(1 for item in results.values() if item.get("outcome") == "no_op")
    completed = sum(1 for item in results.values() if item.get("outcome") == "completed")
    failed = sum(1 for item in results.values() if item.get("outcome") == "failed")
    cycle_outcome = (
        "failed"
        if failed
        else "completed_with_progress"
        if progressed
        else "completed_without_measured_progress"
        if completed
        else "completed_no_op"
    )
    cycle_finished = _now()
    elapsed_ms = (time.perf_counter() - cycle_perf) * 1000.0
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
                "result_summary": {
                    "telemetry_version": TELEMETRY_VERSION,
                    "resource_version": RESOURCE_VERSION,
                    "stage_outcomes": {name: item.get("outcome") for name, item in results.items()},
                },
                "updated_at": cycle_finished.isoformat(),
            },
            filters={"cycle_id": f"eq.{cycle_id}"},
        )
    except Exception:
        logger.exception("Could not persist bounded-worker cycle completion telemetry")

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
    stage_name = str(os.environ.get("EVE_BOUNDED_STAGE") or "").strip()
    cycle_id = str(os.environ.get("EVE_BOUNDED_CYCLE_ID") or uuid.uuid4())
    if stage_name:
        ordinal = int(os.environ.get("EVE_BOUNDED_STAGE_ORDINAL") or "0")
        result = asyncio.run(run_named_stage(stage_name, cycle_id, ordinal))
    else:
        result = asyncio.run(run_once())
    print(json.dumps(result, sort_keys=True, default=str), flush=True)
    if not result.get("ok"):
        raise SystemExit(1)
