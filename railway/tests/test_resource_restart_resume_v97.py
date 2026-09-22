from __future__ import annotations

from datetime import datetime, timedelta, timezone

from app.services import resource_bounded_v97 as resources


def utc(hour: int, minute: int = 0) -> datetime:
    return datetime(2026, 9, 22, hour, minute, tzinfo=timezone.utc)


def test_restore_uses_latest_successful_attempt_per_stage_and_keeps_job_id() -> None:
    rows = [
        {
            "id": 14,
            "cycle_id": "cycle-1",
            "stage_name": "fabric",
            "ordinal": 1,
            "outcome": "progressed",
            "operation_ok": True,
            "elapsed_ms": 7000,
            "cpu_user_ms": 500,
            "cpu_system_ms": 50,
            "process_max_rss_mb": 100,
            "result_summary": {"rows": 2},
        },
        {
            "id": 15,
            "cycle_id": "cycle-1",
            "stage_name": "discovery",
            "ordinal": 2,
            "outcome": "progressed",
            "operation_ok": True,
            "elapsed_ms": 225000,
            "cpu_user_ms": 43000,
            "cpu_system_ms": 1400,
            "process_max_rss_mb": 630,
            "result_summary": {"actions": ["tested_mutation"]},
        },
        {
            "id": 16,
            "cycle_id": "cycle-1",
            "stage_name": "scientist",
            "ordinal": 3,
            "outcome": "failed",
            "operation_ok": False,
            "elapsed_ms": 500000,
            "cpu_user_ms": 38000,
            "cpu_system_ms": 1600,
            "process_max_rss_mb": 1430,
            "result_summary": {},
        },
    ]

    restored = resources.restored_stage_results(rows)

    assert set(restored) == {"fabric", "discovery"}
    assert restored["fabric"]["stage_run_id"] == 14
    assert restored["discovery"]["stage_run_id"] == 15
    assert restored["discovery"]["restored_from_durable_telemetry"] is True


def test_restart_compute_budget_does_not_reset() -> None:
    restored = {
        "fabric": {"elapsed_ms": 7_000},
        "discovery": {"elapsed_ms": 225_000},
        "scientist_failed_attempt": {"elapsed_ms": 500_000},
    }

    assert resources.active_compute_ms(restored) == 732_000
    assert resources.remaining_cycle_budget_seconds(restored, 2700) == 1968.0


def test_persisted_next_due_prevents_redeploy_from_restarting_cadence() -> None:
    last_cycle = {
        "finished_at": utc(14).isoformat(),
        "next_due_at": utc(20).isoformat(),
    }

    assert resources.cadence_delay_seconds(
        last_cycle,
        now=utc(17),
        interval_minutes=360,
    ) == 3 * 60 * 60
    assert resources.cadence_delay_seconds(
        last_cycle,
        now=utc(20, 1),
        interval_minutes=360,
    ) == 0.0


def test_legacy_finished_at_cadence_fallback_is_still_restart_safe() -> None:
    last_cycle = {"finished_at": utc(14).isoformat()}
    assert resources.cadence_delay_seconds(
        last_cycle,
        now=utc(17),
        interval_minutes=360,
    ) == 3 * 60 * 60


def test_resource_summary_reports_peak_cpu_and_budget_pressure() -> None:
    results = {
        "fabric": {
            "process_max_rss_mb": 100,
            "cpu_user_ms": 500,
            "cpu_system_ms": 50,
        },
        "scientist": {
            "process_max_rss_mb": 1884,
            "cpu_user_ms": 69000,
            "cpu_system_ms": 2000,
        },
    }

    summary = resources.resource_summary(results, memory_ceiling_mb=2048)

    assert summary["max_stage_rss_mb"] == 1884
    assert summary["total_stage_cpu_ms"] == 71550
    assert summary["resource_budget_status"] == "near_ceiling"
    assert 0.91 < summary["peak_to_ceiling_ratio"] < 0.93


def test_resource_summary_detects_ceiling_breach() -> None:
    summary = resources.resource_summary(
        {"scientist": {"process_max_rss_mb": 2050}},
        memory_ceiling_mb=2048,
    )
    assert summary["resource_budget_status"] == "breached"



def test_restore_prefers_successful_retry_after_failed_attempt_same_stage() -> None:
    rows = [
        {
            "id": 20,
            "cycle_id": "cycle-retry",
            "stage_name": "scientist",
            "ordinal": 3,
            "outcome": "failed",
            "operation_ok": False,
            "elapsed_ms": 420000,
            "cpu_user_ms": 30000,
            "cpu_system_ms": 1000,
            "process_max_rss_mb": 1500,
            "result_summary": {"reason": "timeout"},
        },
        {
            "id": 21,
            "cycle_id": "cycle-retry",
            "stage_name": "scientist",
            "ordinal": 3,
            "outcome": "progressed",
            "operation_ok": True,
            "elapsed_ms": 180000,
            "cpu_user_ms": 25000,
            "cpu_system_ms": 900,
            "process_max_rss_mb": 1200,
            "result_summary": {"actions": ["new_evidence"]},
        },
    ]

    restored = resources.restored_stage_results(rows)

    assert set(restored) == {"scientist"}
    assert restored["scientist"]["stage_run_id"] == 21
    assert restored["scientist"]["outcome"] == "progressed"
    assert restored["scientist"]["restored_from_durable_telemetry"] is True


def test_resource_accounting_includes_failed_and_successful_retry_attempts() -> None:
    attempts = {
        "20": {
            "elapsed_ms": 420000,
            "cpu_user_ms": 30000,
            "cpu_system_ms": 1000,
            "process_max_rss_mb": 1500,
        },
        "21": {
            "elapsed_ms": 180000,
            "cpu_user_ms": 25000,
            "cpu_system_ms": 900,
            "process_max_rss_mb": 1200,
        },
    }

    assert resources.active_compute_ms(attempts) == 600000
    summary = resources.resource_summary(attempts, memory_ceiling_mb=1536)
    assert summary["max_stage_rss_mb"] == 1500
    assert summary["total_stage_cpu_ms"] == 56900
    assert summary["resource_budget_status"] == "near_ceiling"
