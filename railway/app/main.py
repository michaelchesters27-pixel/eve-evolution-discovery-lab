from __future__ import annotations

import asyncio
import json
import logging
import os
import signal
import socket
import sys
import time
import uuid
from collections import deque
from datetime import datetime, timedelta, timezone
from contextlib import asynccontextmanager
from typing import Any

from fastapi import Depends, FastAPI, Header, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response
from pydantic import BaseModel, Field

from app.settings import Settings, get_settings
from app.services.fabric_builder import FabricBuilder
from app.services.evidence_director import EvidenceDirectedIntelligenceDirector as IntelligenceDirector
from app.services.live_trader import LiveTrader
from app.services.mt5_generator import decode_package
from app.services.orchestrator_v3 import DiscoveryOrchestrator
from app.services import mtf_reasoning as _mtf_reasoning  # noqa: F401 — activates shared research/live semantics
from app.services import resource_bounded_v97 as resources
from app.services.passport import passport_is_complete
from app.services.repository import DiscoveryRepository, SourceRepository

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

settings = get_settings()
source_repo = SourceRepository(settings)
discovery_repo = DiscoveryRepository(settings)
orchestrator = DiscoveryOrchestrator(settings, source_repo, discovery_repo)
intelligence = IntelligenceDirector(settings, discovery_repo, orchestrator.rows)
fabric = FabricBuilder(settings, source_repo, discovery_repo)
live_trader = LiveTrader(settings, discovery_repo)
worker_task: asyncio.Task[Any] | None = None
intelligence_task: asyncio.Task[Any] | None = None
fabric_task: asyncio.Task[Any] | None = None
live_trader_task: asyncio.Task[Any] | None = None
bounded_research_task: asyncio.Task[Any] | None = None


def _rpc_object(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return dict(value)
    if isinstance(value, list) and value and isinstance(value[0], dict):
        first = dict(value[0])
        if len(first) == 1:
            inner = next(iter(first.values()))
            if isinstance(inner, dict):
                return dict(inner)
        return first
    return {}


def _bounded_owner_id() -> str:
    return ":".join(
        [
            str(os.environ.get("RAILWAY_SERVICE_ID") or "evolution"),
            socket.gethostname(),
            str(os.getpid()),
        ]
    )


async def _claim_bounded_supervisor(owner_id: str) -> dict[str, Any]:
    result = await discovery_repo.client.rpc(
        "claim_bounded_research_supervisor_v96",
        {
            "p_owner_id": owner_id,
            "p_lease_seconds": settings.bounded_research_lease_seconds,
        },
    )
    return _rpc_object(result)


async def _renew_bounded_supervisor(owner_id: str, token: str) -> bool:
    result = await discovery_repo.client.rpc(
        "renew_bounded_research_supervisor_v96",
        {
            "p_owner_id": owner_id,
            "p_lease_token": token,
            "p_lease_seconds": settings.bounded_research_lease_seconds,
        },
    )
    return bool(_rpc_object(result).get("renewed"))


async def _release_bounded_supervisor(owner_id: str, token: str) -> None:
    try:
        await discovery_repo.client.rpc(
            "release_bounded_research_supervisor_v96",
            {"p_owner_id": owner_id, "p_lease_token": token},
        )
    except Exception:
        logger.exception("Could not release bounded research supervisor lease")


async def _record_supervisor_stage_failure(
    cycle_id: str,
    stage_name: str,
    ordinal: int,
    reason: str,
    *,
    elapsed_ms: float = 0.0,
) -> dict[str, Any]:
    now = datetime.now(timezone.utc).isoformat()
    payload = {
        "cycle_id": cycle_id,
        "stage_name": stage_name,
        "ordinal": ordinal,
        "outcome": "failed",
        "operation_ok": False,
        "started_at": now,
        "finished_at": now,
        "elapsed_ms": round(elapsed_ms, 3),
        "cpu_user_ms": None,
        "cpu_system_ms": None,
        "process_max_rss_mb": None,
        "result_summary": {
            "resource_version": resources.RESOURCE_VERSION,
            "memory_ceiling_mb": settings.bounded_research_memory_mb,
            "supervisor_failure": reason[:1000],
        },
        "error": reason[:2000],
    }
    stage_run_id: int | None = None
    try:
        inserted = await discovery_repo.client.insert("bounded_research_stage_runs", payload, return_rows=True)
        if inserted and isinstance(inserted[0], dict) and inserted[0].get("id") is not None:
            stage_run_id = int(inserted[0]["id"])
    except Exception:
        logger.exception("Could not persist supervisor-generated stage failure")
    return {
        "ok": False,
        "cycle_id": cycle_id,
        "stage": stage_name,
        "ordinal": ordinal,
        "outcome": "failed",
        "error": reason[:2000],
        "elapsed_ms": round(elapsed_ms, 3),
        "memory_ceiling_mb": settings.bounded_research_memory_mb,
        "resource_version": resources.RESOURCE_VERSION,
        "stage_run_id": stage_run_id,
    }


async def _read_bounded_child(
    process: asyncio.subprocess.Process,
    *,
    cycle_id: str,
    stage_name: str,
) -> tuple[dict[str, Any] | None, str]:
    tail: deque[str] = deque(maxlen=80)
    summary: dict[str, Any] | None = None
    assert process.stdout is not None
    while True:
        line = await process.stdout.readline()
        if not line:
            break
        decoded = line.decode("utf-8", errors="replace").rstrip()
        if decoded:
            tail.append(decoded[-2000:])
        candidate = decoded.strip()
        if candidate.startswith("{"):
            try:
                payload = json.loads(candidate)
            except json.JSONDecodeError:
                continue
            if (
                isinstance(payload, dict)
                and str(payload.get("cycle_id") or "") == cycle_id
                and str(payload.get("stage") or "") == stage_name
            ):
                summary = payload
    await process.wait()
    return summary, "\n".join(tail)


async def _start_stage_attempt(
    cycle_id: str,
    stage_name: str,
    ordinal: int,
) -> tuple[int, datetime] | None:
    started_at = datetime.now(timezone.utc)
    try:
        inserted = await discovery_repo.client.insert(
            "bounded_research_stage_runs",
            {
                "cycle_id": cycle_id,
                "stage_name": stage_name,
                "ordinal": ordinal,
                "outcome": "running",
                "operation_ok": False,
                "started_at": started_at.isoformat(),
                "finished_at": None,
                "heartbeat_at": started_at.isoformat(),
                "elapsed_ms": 0.0,
                "cpu_user_ms": None,
                "cpu_system_ms": None,
                "process_max_rss_mb": None,
                "result_summary": {
                    "resource_version": resources.RESOURCE_VERSION,
                    "memory_ceiling_mb": settings.bounded_research_memory_mb,
                    "durable_attempt_started_before_compute": True,
                },
                "error": None,
            },
            return_rows=True,
        )
    except Exception:
        logger.exception("Could not durably start bounded stage attempt %s", stage_name)
        return None
    if not inserted or not isinstance(inserted[0], dict) or inserted[0].get("id") is None:
        return None
    return int(inserted[0]["id"]), started_at


async def _checkpoint_stage_attempt(stage_run_id: int, started_at: datetime) -> None:
    now = datetime.now(timezone.utc)
    elapsed_ms = max(0.0, (now - started_at).total_seconds() * 1000.0)
    patched = await discovery_repo.client.patch(
        "bounded_research_stage_runs",
        {
            "heartbeat_at": now.isoformat(),
            "elapsed_ms": round(elapsed_ms, 3),
        },
        filters={"id": f"eq.{stage_run_id}", "outcome": "eq.running"},
    )
    if not patched:
        raise RuntimeError(f"bounded stage attempt {stage_run_id} checkpoint was not acknowledged")


async def _finish_supervisor_stage_attempt(
    stage_run_id: int,
    *,
    outcome: str,
    reason: str,
    started_at: datetime,
) -> float:
    now = datetime.now(timezone.utc)
    elapsed_ms = max(0.0, (now - started_at).total_seconds() * 1000.0)
    try:
        await discovery_repo.client.patch(
            "bounded_research_stage_runs",
            {
                "outcome": outcome,
                "operation_ok": False,
                "finished_at": now.isoformat(),
                "heartbeat_at": now.isoformat(),
                "elapsed_ms": round(elapsed_ms, 3),
                "result_summary": {
                    "resource_version": resources.RESOURCE_VERSION,
                    "memory_ceiling_mb": settings.bounded_research_memory_mb,
                    "supervisor_failure": reason[:1000],
                },
                "error": reason[:2000],
            },
            filters={"id": f"eq.{stage_run_id}"},
        )
    except Exception:
        logger.exception("Could not finalise bounded stage attempt %s", stage_run_id)
    return elapsed_ms


async def _terminate_bounded_child(process: asyncio.subprocess.Process) -> None:
    if process.returncode is not None:
        return
    try:
        if sys.platform != "win32":
            os.killpg(process.pid, signal.SIGTERM)
        else:
            process.terminate()
    except ProcessLookupError:
        return
    except Exception:
        try:
            process.terminate()
        except ProcessLookupError:
            return

    try:
        await asyncio.wait_for(process.wait(), timeout=5.0)
        return
    except asyncio.TimeoutError:
        pass

    try:
        if sys.platform != "win32":
            os.killpg(process.pid, signal.SIGKILL)
        else:
            process.kill()
    except ProcessLookupError:
        return
    except Exception:
        try:
            process.kill()
        except ProcessLookupError:
            return
    await process.wait()


async def _bounded_lease_heartbeat(
    owner_id: str,
    lease_token: str,
    stage_run_id: int,
    started_at: datetime,
) -> str | None:
    while True:
        await asyncio.sleep(settings.bounded_research_lease_renew_seconds)
        try:
            await _checkpoint_stage_attempt(stage_run_id, started_at)
        except Exception as exc:
            logger.exception("Bounded stage telemetry heartbeat failed")
            return f"durable_stage_checkpoint_failed:{str(exc)[:500]}"
        try:
            renewed = await _renew_bounded_supervisor(owner_id, lease_token)
        except Exception as exc:
            logger.exception("Bounded research lease renewal raised")
            return f"durable_supervisor_lease_renewal_failed:{str(exc)[:500]}"
        if not renewed:
            return "durable_supervisor_lease_lost_during_stage"


async def _run_bounded_stage(
    cycle_id: str,
    stage_name: str,
    ordinal: int,
    timeout_seconds: float,
    *,
    owner_id: str,
    lease_token: str,
) -> dict[str, Any]:
    attempt = await _start_stage_attempt(cycle_id, stage_name, ordinal)
    if attempt is None:
        return {
            "ok": False,
            "cycle_id": cycle_id,
            "stage": stage_name,
            "ordinal": ordinal,
            "outcome": "failed",
            "error": "durable_stage_attempt_start_failed_compute_not_started",
            "elapsed_ms": 0.0,
            "stage_run_id": None,
            "resource_version": resources.RESOURCE_VERSION,
        }

    stage_run_id, started_at = attempt
    env = dict(os.environ)
    env.update(
        {
            "EVE_BOUNDED_CYCLE_ID": cycle_id,
            "EVE_BOUNDED_STAGE": stage_name,
            "EVE_BOUNDED_STAGE_ORDINAL": str(ordinal),
            "EVE_BOUNDED_STAGE_RUN_ID": str(stage_run_id),
            "EVE_BOUNDED_STAGE_ATTEMPT_STARTED_AT": started_at.isoformat(),
            "EVE_BOUNDED_MEMORY_MB": str(settings.bounded_research_memory_mb),
        }
    )
    process: asyncio.subprocess.Process | None = None
    child_task: asyncio.Task[Any] | None = None
    heartbeat_task: asyncio.Task[Any] | None = None
    try:
        process = await asyncio.create_subprocess_exec(
            sys.executable,
            "-m",
            "app.bounded_worker",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
            env=env,
            start_new_session=(sys.platform != "win32"),
        )
        child_task = asyncio.create_task(
            _read_bounded_child(process, cycle_id=cycle_id, stage_name=stage_name),
            name=f"bounded-stage-read-{stage_name}",
        )
        heartbeat_task = asyncio.create_task(
            _bounded_lease_heartbeat(owner_id, lease_token, stage_run_id, started_at),
            name=f"bounded-lease-heartbeat-{stage_name}",
        )
        done, _ = await asyncio.wait(
            {child_task, heartbeat_task},
            timeout=max(1.0, timeout_seconds),
            return_when=asyncio.FIRST_COMPLETED,
        )

        if heartbeat_task in done:
            failure_reason = heartbeat_task.result()
            if failure_reason:
                await _terminate_bounded_child(process)
                if child_task and not child_task.done():
                    child_task.cancel()
                    try:
                        await child_task
                    except asyncio.CancelledError:
                        pass
                elapsed_ms = await _finish_supervisor_stage_attempt(
                    stage_run_id,
                    outcome="interrupted",
                    reason=failure_reason,
                    started_at=started_at,
                )
                return {
                    "ok": False,
                    "cycle_id": cycle_id,
                    "stage": stage_name,
                    "ordinal": ordinal,
                    "outcome": "failed",
                    "error": failure_reason,
                    "elapsed_ms": round(elapsed_ms, 3),
                    "stage_run_id": stage_run_id,
                    "resource_version": resources.RESOURCE_VERSION,
                }

        if child_task in done:
            summary, tail = child_task.result()
            if (
                process.returncode == 0
                and isinstance(summary, dict)
                and summary.get("ok") is True
                and summary.get("telemetry_persisted") is True
                and int(summary.get("stage_run_id") or 0) == stage_run_id
            ):
                return summary

            reason = "child_completion_not_durably_acknowledged"
            if isinstance(summary, dict) and summary.get("error"):
                reason = str(summary.get("error"))[:2000]
            elif process.returncode not in {0, None}:
                reason = f"child_exit_code_{process.returncode}"
            if tail:
                reason += ":" + tail[-2000:]
            elapsed_ms = await _finish_supervisor_stage_attempt(
                stage_run_id,
                outcome="failed",
                reason=reason,
                started_at=started_at,
            )
            return {
                "ok": False,
                "cycle_id": cycle_id,
                "stage": stage_name,
                "ordinal": ordinal,
                "outcome": "failed",
                "error": reason[:2000],
                "elapsed_ms": round(elapsed_ms, 3),
                "stage_run_id": stage_run_id,
                "resource_version": resources.RESOURCE_VERSION,
            }

        await _terminate_bounded_child(process)
        if child_task and not child_task.done():
            child_task.cancel()
            try:
                await child_task
            except asyncio.CancelledError:
                pass
        reason = f"stage_timeout_after_{round(timeout_seconds,1)}s"
        elapsed_ms = await _finish_supervisor_stage_attempt(
            stage_run_id,
            outcome="interrupted",
            reason=reason,
            started_at=started_at,
        )
        return {
            "ok": False,
            "cycle_id": cycle_id,
            "stage": stage_name,
            "ordinal": ordinal,
            "outcome": "failed",
            "error": reason,
            "elapsed_ms": round(elapsed_ms, 3),
            "stage_run_id": stage_run_id,
            "resource_version": resources.RESOURCE_VERSION,
        }
    except asyncio.CancelledError:
        if process is not None:
            await _terminate_bounded_child(process)
        if child_task and not child_task.done():
            child_task.cancel()
            try:
                await child_task
            except asyncio.CancelledError:
                pass
        await _finish_supervisor_stage_attempt(
            stage_run_id,
            outcome="interrupted",
            reason="supervisor_cancelled_during_stage",
            started_at=started_at,
        )
        raise
    except Exception as exc:
        if process is not None:
            await _terminate_bounded_child(process)
        reason = f"bounded_stage_supervisor_exception:{str(exc)[:1000]}"
        elapsed_ms = await _finish_supervisor_stage_attempt(
            stage_run_id,
            outcome="interrupted",
            reason=reason,
            started_at=started_at,
        )
        return {
            "ok": False,
            "cycle_id": cycle_id,
            "stage": stage_name,
            "ordinal": ordinal,
            "outcome": "failed",
            "error": reason,
            "elapsed_ms": round(elapsed_ms, 3),
            "stage_run_id": stage_run_id,
            "resource_version": resources.RESOURCE_VERSION,
        }
    finally:
        if heartbeat_task is not None:
            heartbeat_task.cancel()
            try:
                await heartbeat_task
            except asyncio.CancelledError:
                pass
        if process is not None and process.returncode is None:
            await _terminate_bounded_child(process)


async def _load_running_cycle() -> dict[str, Any] | None:
    rows = await discovery_repo.client.get(
        "bounded_research_cycles",
        params={
            "select": "*",
            "outcome": "eq.running",
            "order": "started_at.desc",
            "limit": "10",
        },
    )
    if not rows:
        return None
    newest = dict(rows[0])
    # Once the singleton lease is ours, older concurrent-looking running rows
    # cannot still be authoritative. Preserve them as explicit failed history.
    for stale in rows[1:]:
        stale_id = str(stale.get("cycle_id") or "")
        if not stale_id:
            continue
        now = datetime.now(timezone.utc).isoformat()
        await discovery_repo.client.patch(
            "bounded_research_cycles",
            {
                "finished_at": now,
                "outcome": "failed",
                "stages_failed": max(1, int(stale.get("stages_failed") or 0)),
                "result_summary": {
                    **dict(stale.get("result_summary") or {}),
                    "resource_version": resources.RESOURCE_VERSION,
                    "reason": "superseded_stale_running_cycle_after_singleton_lease_recovery",
                },
                "updated_at": now,
            },
            filters={"cycle_id": f"eq.{stale_id}"},
        )
    return newest


async def _cycle_stage_attempts(cycle_id: str) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    offset = 0
    page_size = 200
    while True:
        page = list(
            await discovery_repo.client.get(
                "bounded_research_stage_runs",
                params={
                    "select": "*",
                    "cycle_id": f"eq.{cycle_id}",
                    "order": "id.desc",
                    "limit": str(page_size),
                    "offset": str(offset),
                },
            )
            or []
        )
        rows.extend(dict(row) for row in page)
        if len(page) < page_size:
            break
        offset += page_size

    now = datetime.now(timezone.utc)
    for row in rows:
        if str(row.get("outcome") or "") != "running":
            continue
        started_at = resources.parse_utc(row.get("started_at")) or now
        elapsed_ms = max(
            float(row.get("elapsed_ms") or 0.0),
            min(
                max(0.0, (now - started_at).total_seconds() * 1000.0),
                float(settings.bounded_research_stage_timeout_seconds) * 1000.0,
            ),
        )
        stage_run_id = int(row.get("id") or 0)
        if stage_run_id <= 0:
            continue
        patched = await discovery_repo.client.patch(
            "bounded_research_stage_runs",
            {
                "outcome": "interrupted",
                "operation_ok": False,
                "finished_at": now.isoformat(),
                "heartbeat_at": now.isoformat(),
                "elapsed_ms": round(elapsed_ms, 3),
                "error": "restart_reconciled_unfinished_stage_attempt",
                "result_summary": {
                    **dict(row.get("result_summary") or {}),
                    "resource_version": resources.RESOURCE_VERSION,
                    "restart_reconciled": True,
                    "conservative_elapsed_budget": True,
                },
            },
            filters={"id": f"eq.{stage_run_id}", "outcome": "eq.running"},
        )
        if patched:
            row.update(dict(patched[0]))
        else:
            row.update(
                {
                    "outcome": "interrupted",
                    "operation_ok": False,
                    "finished_at": now.isoformat(),
                    "elapsed_ms": round(elapsed_ms, 3),
                    "error": "restart_reconciled_unfinished_stage_attempt",
                }
            )
    return rows


async def _last_finalised_cycle() -> dict[str, Any] | None:
    rows = await discovery_repo.client.get(
        "bounded_research_cycles",
        params={
            "select": "*",
            "finished_at": "not.is.null",
            "outcome": "neq.running",
            "order": "finished_at.desc",
            "limit": "1",
        },
    )
    return dict(rows[0]) if rows else None


async def _finalise_bounded_cycle(
    cycle_id: str,
    results: dict[str, dict[str, Any]],
    *,
    cycle_started_at: datetime,
    supervisor_owner: str,
    resume_count: int,
) -> dict[str, Any]:
    progressed = sum(1 for item in results.values() if item.get("outcome") == "progressed")
    no_op = sum(1 for item in results.values() if item.get("outcome") == "no_op")
    completed = sum(1 for item in results.values() if item.get("outcome") == "completed")
    failed = sum(1 for item in results.values() if item.get("outcome") == "failed")
    outcome = (
        "failed"
        if failed
        else "completed_with_progress"
        if progressed
        else "completed_without_measured_progress"
        if completed
        else "completed_no_op"
    )
    now_dt = datetime.now(timezone.utc)
    now = now_dt.isoformat()
    wall_elapsed_ms = max(0.0, (now_dt - cycle_started_at).total_seconds() * 1000.0)

    try:
        attempt_rows = await _cycle_stage_attempts(cycle_id)
    except Exception:
        logger.exception("Could not reload bounded stage attempts during finalisation")
        attempt_rows = []
    attempts = {str(row.get("id") or index): dict(row) for index, row in enumerate(attempt_rows)}
    active_compute_ms = resources.active_compute_ms(attempts) if attempts else resources.active_compute_ms(results)
    resource = resources.resource_summary(
        attempts if attempts else results,
        memory_ceiling_mb=settings.bounded_research_memory_mb,
    )
    next_due = now_dt + timedelta(minutes=settings.bounded_research_interval_minutes)
    stage_job_ids = {
        name: item.get("stage_run_id")
        for name, item in results.items()
        if item.get("stage_run_id") is not None
    }
    restored_stages = sorted(
        name for name, item in results.items() if item.get("restored_from_durable_telemetry")
    )
    summary = {
        "telemetry_version": "eve-bounded-stage-telemetry-v2",
        "resource_version": resources.RESOURCE_VERSION,
        "execution_mode": "isolated_stage_processes",
        "memory_ceiling_mb": settings.bounded_research_memory_mb,
        "stage_timeout_seconds": settings.bounded_research_stage_timeout_seconds,
        "cycle_timeout_seconds": settings.bounded_research_timeout_seconds,
        "stage_outcomes": {name: item.get("outcome") for name, item in results.items()},
        "stage_job_ids": stage_job_ids,
        "restart_resumable": True,
        "resume_count": resume_count,
        "restored_completed_stages": restored_stages,
        "persistent_cadence": True,
        "next_due_at": next_due.isoformat(),
        "mode_exclusion": "bounded_vs_resident_heavy_workers",
        **resource,
    }
    try:
        await discovery_repo.client.patch(
            "bounded_research_cycles",
            {
                "finished_at": now,
                "outcome": outcome,
                "stages_total": len(results),
                "stages_progressed": progressed,
                "stages_no_op": no_op,
                "stages_completed": completed,
                "stages_failed": failed,
                "elapsed_ms": round(wall_elapsed_ms, 3),
                "active_compute_ms": round(active_compute_ms, 3),
                "max_stage_rss_mb": resource.get("max_stage_rss_mb"),
                "total_stage_cpu_ms": resource.get("total_stage_cpu_ms"),
                "resource_budget_status": resource.get("resource_budget_status"),
                "next_due_at": next_due.isoformat(),
                "supervisor_owner": supervisor_owner,
                "result_summary": summary,
                "updated_at": now,
            },
            filters={"cycle_id": f"eq.{cycle_id}"},
        )
        await discovery_repo.event(
            "error" if failed else "info",
            "bounded_research_supervisor",
            (
                f"Isolated bounded cycle {outcome}: {progressed} progressed, "
                f"{no_op} no-op, {completed} completed without measured progress, {failed} failed; "
                f"peak stage RSS={resource.get('max_stage_rss_mb')}MB."
            ),
            {"cycle_id": cycle_id, **summary},
        )
    except Exception:
        logger.exception("Could not persist isolated bounded-cycle completion")
    return {
        "ok": failed == 0,
        "cycle_id": cycle_id,
        "outcome": outcome,
        "progressed": progressed,
        "no_op": no_op,
        "completed": completed,
        "failed": failed,
        "elapsed_ms": round(wall_elapsed_ms, 3),
        "active_compute_ms": round(active_compute_ms, 3),
        "next_due_at": next_due.isoformat(),
        "resource": resource,
        "stages": results,
    }


async def _bounded_research_loop() -> None:
    """Run expensive research as one durable, restart-resumable bounded pipeline."""
    if settings.bounded_research_startup_seconds:
        await asyncio.sleep(settings.bounded_research_startup_seconds)

    owner_id = _bounded_owner_id()
    stages = (
        ("fabric", 1),
        ("discovery", 2),
        ("scientist", 3),
        ("historical_academy", 4),
        ("zone_replay", 5),
        ("current_policy", 6),
    )

    while True:
        lease_token: str | None = None
        try:
            claim = await _claim_bounded_supervisor(owner_id)
            if not bool(claim.get("acquired")):
                logger.info(
                    "Bounded research skipped because durable lease is held by %s until %s",
                    claim.get("owner_id"),
                    claim.get("expires_at"),
                )
                await asyncio.sleep(settings.bounded_research_overlap_retry_seconds)
                continue

            lease_token = str(claim.get("lease_token") or "")
            now_dt = datetime.now(timezone.utc)
            running = await _load_running_cycle()

            if running is None:
                last_cycle = await _last_finalised_cycle()
                delay = resources.cadence_delay_seconds(
                    last_cycle,
                    now=now_dt,
                    interval_minutes=settings.bounded_research_interval_minutes,
                )
                if delay > 0:
                    logger.info(
                        "Bounded research durable cadence not due for %.1f minutes; deployment will not restart heavy work early.",
                        delay / 60.0,
                    )
                    await _release_bounded_supervisor(owner_id, lease_token)
                    lease_token = None
                    await asyncio.sleep(delay)
                    continue

                cycle_id = str(uuid.uuid4())
                cycle_started = now_dt
                resume_count = 0
                results: dict[str, dict[str, Any]] = {}
                attempt_compute_ms = 0.0
                await discovery_repo.client.insert(
                    "bounded_research_cycles",
                    {
                        "cycle_id": cycle_id,
                        "worker_pid": os.getpid(),
                        "started_at": cycle_started.isoformat(),
                        "outcome": "running",
                        "resume_count": 0,
                        "supervisor_owner": owner_id,
                        "result_summary": {
                            "telemetry_version": "eve-bounded-stage-telemetry-v2",
                            "resource_version": resources.RESOURCE_VERSION,
                            "execution_mode": "isolated_stage_processes",
                            "memory_ceiling_mb": settings.bounded_research_memory_mb,
                            "supervisor_owner": owner_id,
                            "restart_resumable": True,
                            "persistent_cadence": True,
                        },
                    },
                    return_rows=False,
                )
            else:
                cycle_id = str(running.get("cycle_id") or "")
                if not cycle_id:
                    raise RuntimeError("running bounded cycle has no cycle_id")
                cycle_started = resources.parse_utc(running.get("started_at")) or now_dt
                resume_count = int(running.get("resume_count") or 0) + 1
                attempts = await _cycle_stage_attempts(cycle_id)
                results = resources.restored_stage_results(attempts)
                attempt_compute_ms = sum(max(0.0, float(row.get("elapsed_ms") or 0.0)) for row in attempts)
                resume_summary = {
                    **dict(running.get("result_summary") or {}),
                    "telemetry_version": "eve-bounded-stage-telemetry-v2",
                    "resource_version": resources.RESOURCE_VERSION,
                    "restart_resumable": True,
                    "resumed_by": owner_id,
                    "resume_count": resume_count,
                    "restored_completed_stages": sorted(results),
                }
                await discovery_repo.client.patch(
                    "bounded_research_cycles",
                    {
                        "worker_pid": os.getpid(),
                        "resume_count": resume_count,
                        "last_resumed_at": now_dt.isoformat(),
                        "supervisor_owner": owner_id,
                        "result_summary": resume_summary,
                        "updated_at": now_dt.isoformat(),
                    },
                    filters={"cycle_id": f"eq.{cycle_id}"},
                )
                logger.info(
                    "Resuming bounded research cycle %s without repeating completed stages: %s",
                    cycle_id,
                    ",".join(sorted(results)) or "none",
                )

            for stage_name, ordinal in stages:
                if stage_name in results and results[stage_name].get("ok") is True:
                    continue

                remaining = max(
                    0.0,
                    float(settings.bounded_research_timeout_seconds) - attempt_compute_ms / 1000.0,
                )
                if remaining <= 0:
                    results[stage_name] = await _record_supervisor_stage_failure(
                        cycle_id,
                        stage_name,
                        ordinal,
                        "cycle_active_compute_budget_exhausted_before_stage_start",
                    )
                    break

                if not await _renew_bounded_supervisor(owner_id, lease_token):
                    results[stage_name] = await _record_supervisor_stage_failure(
                        cycle_id,
                        stage_name,
                        ordinal,
                        "durable_supervisor_lease_lost_before_stage",
                    )
                    break

                timeout = min(float(settings.bounded_research_stage_timeout_seconds), remaining)
                stage_result = await _run_bounded_stage(
                    cycle_id,
                    stage_name,
                    ordinal,
                    timeout,
                    owner_id=owner_id,
                    lease_token=lease_token,
                )
                results[stage_name] = stage_result
                attempt_compute_ms += max(0.0, float(stage_result.get("elapsed_ms") or 0.0))

            final = await _finalise_bounded_cycle(
                cycle_id,
                results,
                cycle_started_at=cycle_started,
                supervisor_owner=owner_id,
                resume_count=resume_count,
            )
            logger.info(
                "Bounded research cycle %s finished outcome=%s peak_stage_rss=%sMB next_due=%s",
                cycle_id,
                final.get("outcome"),
                (final.get("resource") or {}).get("max_stage_rss_mb"),
                final.get("next_due_at"),
            )
        except asyncio.CancelledError:
            # Leave a running cycle open. The next deployment will acquire the
            # durable lease and resume from stage telemetry instead of restarting.
            raise
        except Exception as exc:
            logger.exception("Bounded research supervisor failed safely")
            try:
                await discovery_repo.event(
                    "error",
                    "bounded_research_supervisor",
                    "Bounded research supervisor failed safely; durable running-cycle telemetry is retained for restart recovery.",
                    {
                        "owner_id": owner_id,
                        "resource_version": resources.RESOURCE_VERSION,
                        "error": str(exc)[:2000],
                    },
                )
            except Exception:
                pass
        finally:
            if lease_token:
                await _release_bounded_supervisor(owner_id, lease_token)

        await asyncio.sleep(settings.bounded_research_interval_minutes * 60)


class LiveTraderChatRequest(BaseModel):
    message: str = Field(default="What are we doing?", max_length=4000)


class LiveTraderNewsTimedEventRequest(BaseModel):
    event_date: str = Field(min_length=10, max_length=10)
    event_time: str = Field(min_length=4, max_length=8)
    event_name: str = Field(min_length=1, max_length=180)


class LiveTraderNewsAllDayEventRequest(BaseModel):
    event_date: str = Field(min_length=10, max_length=10)
    event_name: str = Field(min_length=1, max_length=180)


class LiveTraderNewsRemoveEventRequest(BaseModel):
    event_id: str = Field(min_length=1, max_length=128)


class LiveTraderNewsWeekConfirmRequest(BaseModel):
    calendar_checked: bool = False
    expected_event_count: int = Field(ge=0)
    source_reference: str = Field(min_length=3, max_length=500)
    note: str = Field(default="", max_length=1000)


@asynccontextmanager
async def lifespan(_: FastAPI):
    global worker_task, intelligence_task, fabric_task, live_trader_task, bounded_research_task
    # Legacy continuous research remains available for development, but production
    # uses the bounded child worker so historical heaps never live for 24/7.
    if settings.autonomous_enabled:
        worker_task = asyncio.create_task(orchestrator.run_forever(), name="eve-discovery-worker")
        intelligence_task = asyncio.create_task(intelligence.run_forever(), name="eve-autonomous-scientist")
    if settings.fabric_enabled:
        fabric_task = asyncio.create_task(fabric.run_forever(), name="eve-m5-observation-fabric")
    if settings.bounded_research_enabled:
        bounded_research_task = asyncio.create_task(_bounded_research_loop(), name="eve-bounded-research")
    if settings.live_trader_enabled:
        live_trader_task = asyncio.create_task(live_trader.run_forever(), name="eve-live-trader")
    try:
        yield
    finally:
        await live_trader.stop()
        await fabric.stop()
        await intelligence.stop()
        await orchestrator.stop()
        for task in (live_trader_task, bounded_research_task, fabric_task, intelligence_task, worker_task):
            if task:
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass


app = FastAPI(title=settings.app_name, version="2.7.0", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=False,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["*"],
)


def require_admin(
    authorization: str | None = Header(default=None),
    x_admin_token: str | None = Header(default=None),
) -> None:
    supplied = x_admin_token or (authorization.removeprefix("Bearer ").strip() if authorization else "")
    if supplied != settings.admin_token:
        raise HTTPException(status_code=401, detail="Invalid admin token")


def require_package_access(
    authorization: str | None = Header(default=None),
    x_admin_token: str | None = Header(default=None),
) -> None:
    if not settings.package_downloads_require_admin:
        return
    require_admin(authorization=authorization, x_admin_token=x_admin_token)


def package_download_ready(row: dict[str, Any]) -> tuple[bool, str]:
    profile_status = str(row.get("profile_status") or "pending")
    eligible = bool(row.get("download_eligible"))
    passport = dict(row.get("trading_passport") or {})
    if profile_status != "complete":
        reason = str(row.get("profile_reason") or "EVE has not completed this package's Trading Passport yet.")
        return False, reason
    if not eligible:
        return False, "The package is not approved for download after profiling."
    if not passport_is_complete(passport):
        return False, "The package Trading Passport is incomplete, so download is locked."
    if str(row.get("status") or "ready") != "ready":
        return False, str(row.get("profile_reason") or "The package is not ready for download.")
    return True, "ready"


def require_research_access(
    authorization: str | None = Header(default=None),
    x_admin_token: str | None = Header(default=None),
) -> None:
    if not settings.research_api_requires_admin:
        return
    require_admin(authorization=authorization, x_admin_token=x_admin_token)


async def safe_fabric_state() -> dict[str, Any]:
    try:
        state = await fabric.state()
        return {"read_ok": True, **state}
    except Exception as exc:
        logger.exception("Operator API could not read fabric state")
        return {
            "read_ok": False,
            "status": "unavailable",
            "last_error": str(exc)[:500],
        }


async def safe_intelligence_dashboard() -> dict[str, Any]:
    try:
        return await intelligence.dashboard()
    except Exception as exc:
        logger.exception("Operator API could not read intelligence dashboard")
        return {
            "runtime": intelligence.runtime_status(),
            "recent_hypotheses": [],
            "live_setups": [],
            "top_learned_features": [],
            "read_error": str(exc)[:500],
        }


async def safe_dashboard_store() -> dict[str, Any]:
    try:
        return await discovery_repo.dashboard()
    except Exception as exc:
        logger.exception("Operator API could not read discovery dashboard")
        return {"read_error": str(exc)[:500]}


async def safe_data_health_store() -> dict[str, Any]:
    try:
        return await discovery_repo.data_health()
    except Exception as exc:
        logger.exception("Operator API could not read data health")
        return {"status": "unavailable", "read_error": str(exc)[:500]}


@app.get("/health")
async def health() -> dict[str, Any]:
    return {
        "ok": True,
        "app": settings.app_name,
        "environment": settings.environment,
        "runtime": orchestrator.runtime_status(),
        "intelligence": intelligence.runtime_status(),
        "fabric": {**fabric.runtime_status(), "state": await safe_fabric_state()},
        "live_trader": live_trader.runtime_status(),
    }


@app.get("/api/dashboard", dependencies=[Depends(require_research_access)])
async def dashboard() -> dict[str, Any]:
    stored = await safe_dashboard_store()
    return {
        **stored,
        "runtime": orchestrator.runtime_status(),
        "intelligence": intelligence.runtime_status(),
        "fabric": {**fabric.runtime_status(), "state": await safe_fabric_state()},
        "live_trader": live_trader.runtime_status(),
    }


@app.get("/api/intelligence", dependencies=[Depends(require_research_access)])
async def intelligence_dashboard() -> dict[str, Any]:
    return await safe_intelligence_dashboard()


@app.get("/api/live-trader", dependencies=[Depends(require_research_access)])
async def live_trader_snapshot() -> dict[str, Any]:
    return await live_trader.snapshot()


@app.get("/api/live-trader/conversation", dependencies=[Depends(require_research_access)])
async def live_trader_conversation(limit: int = Query(default=40, ge=1, le=100)) -> dict[str, Any]:
    return {"items": await live_trader.conversation(limit), "runtime": live_trader.runtime_status()}


@app.get("/api/live-trader/learning", dependencies=[Depends(require_research_access)])
async def live_trader_learning() -> dict[str, Any]:
    return await live_trader.learning_summary()


@app.post("/api/live-trader/chat", dependencies=[Depends(require_research_access)])
async def live_trader_chat(payload: LiveTraderChatRequest) -> dict[str, Any]:
    return await live_trader.answer(payload.message)


@app.get("/api/admin/live-trader/news-calendar", dependencies=[Depends(require_admin)])
async def live_trader_news_calendar_admin() -> dict[str, Any]:
    return await live_trader.news_confirmation_status(force=True)


@app.post("/api/admin/live-trader/news-events/timed", dependencies=[Depends(require_admin)])
async def live_trader_news_add_timed_admin(payload: LiveTraderNewsTimedEventRequest) -> dict[str, Any]:
    result = await live_trader.add_news_event(payload.event_date, payload.event_time, payload.event_name)
    result["workflow"] = await live_trader.news_confirmation_status(force=True)
    return result


@app.post("/api/admin/live-trader/news-events/all-day", dependencies=[Depends(require_admin)])
async def live_trader_news_add_all_day_admin(payload: LiveTraderNewsAllDayEventRequest) -> dict[str, Any]:
    result = await live_trader.add_all_day_news_event(payload.event_date, payload.event_name)
    result["workflow"] = await live_trader.news_confirmation_status(force=True)
    return result


@app.post("/api/admin/live-trader/news-events/remove", dependencies=[Depends(require_admin)])
async def live_trader_news_remove_admin(payload: LiveTraderNewsRemoveEventRequest) -> dict[str, Any]:
    result = await live_trader.remove_news_event(payload.event_id)
    result["workflow"] = await live_trader.news_confirmation_status(force=True)
    return result


@app.post("/api/admin/live-trader/news-week/confirm", dependencies=[Depends(require_admin)])
async def live_trader_news_confirm_week_admin(payload: LiveTraderNewsWeekConfirmRequest) -> dict[str, Any]:
    result = await live_trader.confirm_news_week(
        calendar_checked=payload.calendar_checked,
        expected_event_count=payload.expected_event_count,
        source_reference=payload.source_reference,
        note=payload.note,
    )
    result["workflow"] = await live_trader.news_confirmation_status(force=True)
    return result


@app.get("/api/fabric", dependencies=[Depends(require_research_access)])
async def fabric_status(limit: int = Query(default=5, ge=1, le=50)) -> dict[str, Any]:
    latest: list[dict[str, Any]] = []
    read_error: str | None = None
    try:
        latest = await discovery_repo.client.get(
            "m5_research_snapshots",
            params={
                "select": "candle_time,outcome_complete,fabric_version",
                "symbol": f"eq.{settings.source_symbol}",
                "order": "candle_time.desc",
                "limit": str(limit),
            },
        )
    except Exception as exc:
        logger.exception("Operator API could not read latest fabric rows")
        read_error = str(exc)[:500]
    return {
        "runtime": fabric.runtime_status(),
        "state": await safe_fabric_state(),
        "latest": latest,
        "read_error": read_error,
    }


@app.get("/api/fabric/audit", dependencies=[Depends(require_research_access)])
async def fabric_audit() -> dict[str, Any]:
    try:
        result = await discovery_repo.client.rpc("get_fabric_audit", {})
        if isinstance(result, dict):
            if isinstance(result.get("get_fabric_audit"), dict):
                return dict(result["get_fabric_audit"])
            return dict(result)
        if isinstance(result, list) and len(result) == 1 and isinstance(result[0], dict):
            row = dict(result[0])
            if isinstance(row.get("get_fabric_audit"), dict):
                return dict(row["get_fabric_audit"])
            return row
        return {"ready_for_scientist_cutover": False, "result": result}
    except Exception as exc:
        logger.exception("Operator API could not run fabric audit")
        return {
            "ready_for_scientist_cutover": False,
            "build_status": "unavailable",
            "gates": {},
            "coverage": {},
            "causality_violations": {},
            "feature_parity": {},
            "last_error": str(exc)[:500],
            "read_error": str(exc)[:500],
        }


@app.get("/api/live-setups", dependencies=[Depends(require_research_access)])
async def live_setups(limit: int = Query(default=100, ge=1, le=500)) -> dict[str, Any]:
    try:
        items = await intelligence.live_setups(limit)
        return {"items": items, "runtime": intelligence.runtime_status()}
    except Exception as exc:
        logger.exception("Operator API could not read live setups")
        return {"items": [], "runtime": intelligence.runtime_status(), "read_error": str(exc)[:500]}


@app.get("/api/scientist/hypotheses", dependencies=[Depends(require_research_access)])
async def scientist_hypotheses(limit: int = Query(default=100, ge=1, le=500)) -> dict[str, Any]:
    return {"items": await intelligence.recent_hypotheses(limit), "runtime": intelligence.runtime_status()}


@app.get("/api/scientist/memory", dependencies=[Depends(require_research_access)])
async def scientist_memory(limit: int = Query(default=100, ge=1, le=500)) -> dict[str, Any]:
    return {"items": await intelligence.feature_memory(limit), "runtime": intelligence.runtime_status()}


@app.get("/api/scientist/evidence", dependencies=[Depends(require_research_access)])
async def scientist_evidence(limit: int = Query(default=100, ge=1, le=500)) -> dict[str, Any]:
    items = await discovery_repo.client.get(
        "scientist_evidence_miner",
        params={
            "select": "*",
            "scientist_version": "eq.eve-autonomous-scientist-v2",
            "research_dataset": "eq.every_m5_fabric",
            "order": "status.desc,evidence_score.desc,q_value.asc",
            "limit": str(limit),
        },
    )
    return {"items": items, "runtime": intelligence.runtime_status()}


@app.get("/api/final-exams", dependencies=[Depends(require_research_access)])
async def final_exams(limit: int = Query(default=100, ge=1, le=500)) -> dict[str, Any]:
    items = await discovery_repo.client.get(
        "final_exam_registry",
        params={"select": "*", "order": "opened_at.desc", "limit": str(limit)},
    )
    return {"items": items, "budget": orchestrator.runtime_status().get("final_exam_budget")}


@app.get("/api/data-health", dependencies=[Depends(require_research_access)])
async def data_health() -> dict[str, Any]:
    stored = await safe_data_health_store()
    return {
        **stored,
        "runtime": orchestrator.runtime_status(),
        "intelligence": intelligence.runtime_status(),
        "fabric": {**fabric.runtime_status(), "state": await safe_fabric_state()},
        "snapshot_definition": (
            "Scientist v2 is authorised on the every-M5 fabric. Each completed M5 state carries causal M1/M15/M30/H1/H4/D1 context, "
            "and cross-timeframe relationship rules are evaluated from the same audited context in historical research and live recognition."
        ),
    }


@app.get("/api/candidates", dependencies=[Depends(require_research_access)])
async def candidates(limit: int = Query(default=100, ge=1, le=500)) -> dict[str, Any]:
    return {"items": await discovery_repo.list_candidates(limit)}


@app.get("/api/lineages", dependencies=[Depends(require_research_access)])
async def lineages(limit: int = Query(default=100, ge=1, le=500)) -> dict[str, Any]:
    return {"items": await discovery_repo.list_lineages(limit)}


@app.get("/api/mutations", dependencies=[Depends(require_research_access)])
async def mutations(limit: int = Query(default=100, ge=1, le=500)) -> dict[str, Any]:
    return {"items": await discovery_repo.list_mutations(limit)}


@app.get("/api/frozen", dependencies=[Depends(require_research_access)])
async def frozen(limit: int = Query(default=100, ge=1, le=500)) -> dict[str, Any]:
    return {"items": await discovery_repo.list_frozen(limit)}


@app.get("/api/packages", dependencies=[Depends(require_research_access)])
async def packages(limit: int = Query(default=100, ge=1, le=500)) -> dict[str, Any]:
    return {"items": await discovery_repo.list_packages(limit)}


@app.get("/api/packages/{package_id}/download")
async def download_package(package_id: str, _: None = Depends(require_package_access)) -> Response:
    row = await discovery_repo.package(package_id)
    if not row:
        raise HTTPException(status_code=404, detail="Package not found")
    ready, reason = package_download_ready(row)
    if not ready:
        raise HTTPException(status_code=409, detail=reason)
    payload = decode_package(row)
    return Response(
        content=payload,
        media_type="application/zip",
        headers={
            "Content-Disposition": f'attachment; filename="{row.get("file_name") or "EVE-DISCOVERY-MT5.zip"}"',
            "X-Checksum-SHA256": str(row.get("sha256") or ""),
        },
    )


@app.get("/api/packages/{package_id}/mq5")
async def download_mq5(package_id: str, _: None = Depends(require_package_access)) -> Response:
    row = await discovery_repo.package(package_id)
    if not row:
        raise HTTPException(status_code=404, detail="Package not found")
    ready, reason = package_download_ready(row)
    if not ready:
        raise HTTPException(status_code=409, detail=reason)
    return Response(
        content=str(row.get("mq5_source") or ""),
        media_type="text/plain; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{row.get("mq5_file_name") or "EVE_Discovery.mq5"}'},
    )


@app.post("/api/admin/run-cycle", dependencies=[Depends(require_admin)])
async def run_cycle() -> dict[str, Any]:
    if settings.bounded_research_enabled:
        raise HTTPException(
            status_code=409,
            detail="Direct heavy discovery execution is disabled while bounded research mode owns historical work.",
        )
    return await orchestrator.run_once()


@app.post("/api/admin/run-scientist", dependencies=[Depends(require_admin)])
async def run_scientist() -> dict[str, Any]:
    if settings.bounded_research_enabled:
        raise HTTPException(
            status_code=409,
            detail="Direct heavy Scientist execution is disabled while bounded research mode owns historical work.",
        )
    return await intelligence.run_science_once(await orchestrator.rows())


@app.post("/api/admin/run-live-watch", dependencies=[Depends(require_admin)])
async def run_live_watch() -> dict[str, Any]:
    return await intelligence.run_live_watch_once()


@app.post("/api/admin/run-live-trader-analysis", dependencies=[Depends(require_admin)])
async def run_live_trader_analysis() -> dict[str, Any]:
    return await live_trader.refresh_state(force_rows=True)


@app.post("/api/admin/run-fabric", dependencies=[Depends(require_admin)])
async def run_fabric() -> dict[str, Any]:
    if settings.bounded_research_enabled:
        raise HTTPException(
            status_code=409,
            detail="Direct fabric execution is disabled while bounded research mode owns historical work.",
        )
    return await fabric.build_once()


@app.post("/api/admin/wake", dependencies=[Depends(require_admin)])
async def wake() -> dict[str, Any]:
    await orchestrator.wake()
    return {"ok": True, "message": "Worker wake requested"}


@app.post("/api/admin/sync-source", dependencies=[Depends(require_admin)])
async def sync_source() -> dict[str, Any]:
    count = await orchestrator.sync_source()
    return {"ok": True, "imported": count}
