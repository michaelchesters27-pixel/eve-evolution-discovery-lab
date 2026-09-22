from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

RESOURCE_VERSION = "eve-resource-bounded-workers-v97"


def parse_utc(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def restored_stage_results(rows: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """Restore the latest successful attempt for each stage from durable telemetry."""
    restored: dict[str, dict[str, Any]] = {}
    for row in sorted(rows, key=lambda item: int(item.get("id") or 0), reverse=True):
        stage = str(row.get("stage_name") or "")
        if not stage or stage in restored or row.get("operation_ok") is not True:
            continue
        restored[stage] = {
            "ok": True,
            "cycle_id": str(row.get("cycle_id") or ""),
            "stage": stage,
            "ordinal": int(row.get("ordinal") or 0),
            "outcome": str(row.get("outcome") or "completed"),
            "result": dict(row.get("result_summary") or {}),
            "elapsed_ms": float(row.get("elapsed_ms") or 0.0),
            "cpu_user_ms": float(row.get("cpu_user_ms") or 0.0),
            "cpu_system_ms": float(row.get("cpu_system_ms") or 0.0),
            "process_max_rss_mb": (
                float(row.get("process_max_rss_mb"))
                if row.get("process_max_rss_mb") is not None
                else None
            ),
            "stage_run_id": int(row.get("id") or 0),
            "restored_from_durable_telemetry": True,
        }
    return restored


def active_compute_ms(results: dict[str, dict[str, Any]]) -> float:
    return sum(max(0.0, float(item.get("elapsed_ms") or 0.0)) for item in results.values())


def remaining_cycle_budget_seconds(
    results: dict[str, dict[str, Any]],
    total_timeout_seconds: float,
) -> float:
    return max(0.0, float(total_timeout_seconds) - active_compute_ms(results) / 1000.0)


def cadence_delay_seconds(
    last_cycle: dict[str, Any] | None,
    *,
    now: datetime,
    interval_minutes: int,
) -> float:
    if not last_cycle:
        return 0.0
    explicit = parse_utc(last_cycle.get("next_due_at"))
    finished = parse_utc(last_cycle.get("finished_at"))
    due = explicit or (
        finished + timedelta(minutes=max(1, int(interval_minutes)))
        if finished is not None
        else None
    )
    if due is None:
        return 0.0
    return max(0.0, (due - now.astimezone(timezone.utc)).total_seconds())


def resource_summary(
    results: dict[str, dict[str, Any]],
    *,
    memory_ceiling_mb: int,
) -> dict[str, Any]:
    rss_values = [
        float(item.get("process_max_rss_mb"))
        for item in results.values()
        if item.get("process_max_rss_mb") is not None
    ]
    peak = max(rss_values) if rss_values else None
    cpu_ms = sum(
        max(0.0, float(item.get("cpu_user_ms") or 0.0))
        + max(0.0, float(item.get("cpu_system_ms") or 0.0))
        for item in results.values()
    )
    ratio = (peak / float(memory_ceiling_mb)) if peak is not None and memory_ceiling_mb > 0 else None
    if ratio is None:
        status = "unmeasured"
    elif ratio > 1.0:
        status = "breached"
    elif ratio >= 0.90:
        status = "near_ceiling"
    else:
        status = "within_budget"
    return {
        "resource_version": RESOURCE_VERSION,
        "max_stage_rss_mb": round(peak, 3) if peak is not None else None,
        "memory_ceiling_mb": int(memory_ceiling_mb),
        "peak_to_ceiling_ratio": round(ratio, 4) if ratio is not None else None,
        "total_stage_cpu_ms": round(cpu_ms, 3),
        "resource_budget_status": status,
    }
