from __future__ import annotations

import asyncio

from app import bounded_worker


class FakeClient:
    def __init__(self) -> None:
        self.inserted: list[tuple[str, dict]] = []

    async def insert(self, table: str, payload: dict, *, return_rows: bool = False):
        self.inserted.append((table, dict(payload)))
        return [{"id": len(self.inserted)}] if return_rows else []


class FakeRepo:
    def __init__(self) -> None:
        self.client = FakeClient()
        self.events: list[tuple[str, str, str, dict]] = []

    async def event(self, level: str, component: str, message: str, details: dict | None = None):
        self.events.append((level, component, message, dict(details or {})))


def test_false_boolean_is_no_op_not_successful_progress() -> None:
    assert bounded_worker._classify_stage_result(False) == "no_op"
    assert bounded_worker._classify_stage_result(None) == "no_op"


def test_bare_true_is_completion_not_measured_progress() -> None:
    assert bounded_worker._classify_stage_result(True) == "completed"


def test_caught_up_zero_row_dict_is_no_op() -> None:
    assert bounded_worker._classify_stage_result(
        {"ok": True, "status": "caught_up", "rows": 0}
    ) == "no_op"


def test_measured_work_is_progressed() -> None:
    assert bounded_worker._classify_stage_result(
        {"ok": True, "status": "caught_up", "rows": 4}
    ) == "progressed"
    assert bounded_worker._classify_stage_result(
        {"ok": True, "actions": ["tested_candidate"], "rows": 164000}
    ) == "progressed"


def test_dataset_size_alone_is_not_claimed_as_progress() -> None:
    assert bounded_worker._classify_stage_result(
        {"ok": True, "dataset_rows": 491000}
    ) == "completed"


def test_returned_failure_is_failed_even_without_exception() -> None:
    assert bounded_worker._classify_stage_result(
        {"ok": False, "reason": "no_source_m5"}
    ) == "failed"


def test_stage_persists_explicit_no_op_telemetry() -> None:
    repo = FakeRepo()

    async def operation():
        return False

    result = asyncio.run(
        bounded_worker._stage(
            "zone_replay",
            5,
            "11111111-1111-1111-1111-111111111111",
            operation,
            repo,
        )
    )
    assert result["ok"] is True
    assert result["outcome"] == "no_op"
    assert len(repo.client.inserted) == 1
    table, payload = repo.client.inserted[0]
    assert table == "bounded_research_stage_runs"
    assert payload["outcome"] == "no_op"
    assert payload["operation_ok"] is True
    assert payload["elapsed_ms"] >= 0
    assert payload["process_max_rss_mb"] > 0
    assert result["telemetry_persisted"] is True



def test_stage_fails_closed_when_terminal_telemetry_cannot_be_persisted() -> None:
    class FailingClient(FakeClient):
        async def insert(self, table: str, payload: dict, *, return_rows: bool = False):
            raise RuntimeError("telemetry unavailable")

    repo = FakeRepo()
    repo.client = FailingClient()

    async def operation():
        return {"ok": True, "rows": 2}

    result = asyncio.run(
        bounded_worker._stage(
            "fabric",
            1,
            "11111111-1111-1111-1111-111111111111",
            operation,
            repo,
        )
    )

    assert result["ok"] is False
    assert result["outcome"] == "failed"
    assert result["telemetry_persisted"] is False
    assert result["error"] == "durable_stage_telemetry_not_acknowledged"
