from __future__ import annotations

import asyncio
import os
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

os.environ.setdefault("SOURCE_SUPABASE_URL", "https://source.invalid")
os.environ.setdefault("SOURCE_SUPABASE_READ_ONLY_KEY", "test-read-only-key-1234567890")
os.environ.setdefault("DISCOVERY_SUPABASE_URL", "https://discovery.invalid")
os.environ.setdefault("DISCOVERY_SUPABASE_SERVICE_ROLE_KEY", "test-service-role-key-1234567890")
os.environ.setdefault("ADMIN_TOKEN", "test-admin-token")

from app import main


class PagedClient:
    def __init__(self, rows):
        self.rows = list(rows)
        self.patches = []

    async def get(self, table: str, *, params: dict | None = None, **_kwargs):
        assert table == "bounded_research_stage_runs"
        params = dict(params or {})
        limit = int(params.get("limit") or 200)
        offset = int(params.get("offset") or 0)
        return self.rows[offset : offset + limit]

    async def patch(self, table: str, values: dict, *, filters: dict):
        self.patches.append((table, dict(values), dict(filters)))
        row_id = int(str(filters["id"]).split(".", 1)[1])
        row = next((item for item in self.rows if int(item["id"]) == row_id), None)
        if row is None:
            return []
        row.update(values)
        return [dict(row)]


def test_attempt_reader_is_complete_beyond_200(monkeypatch) -> None:
    rows = [
        {
            "id": index + 1,
            "cycle_id": "11111111-1111-1111-1111-111111111111",
            "stage_name": "scientist",
            "ordinal": 3,
            "outcome": "failed",
            "operation_ok": False,
            "started_at": "2026-09-22T10:00:00+00:00",
            "finished_at": "2026-09-22T10:00:01+00:00",
            "elapsed_ms": 1000.0,
            "cpu_user_ms": 0.0,
            "cpu_system_ms": 0.0,
            "process_max_rss_mb": 100.0,
            "result_summary": {},
        }
        for index in range(201)
    ]
    client = PagedClient(rows)
    monkeypatch.setattr(main, "discovery_repo", SimpleNamespace(client=client))

    loaded = asyncio.run(main._cycle_stage_attempts(rows[0]["cycle_id"]))

    assert len(loaded) == 201
    assert sum(float(row["elapsed_ms"]) for row in loaded) == 201000.0


def test_running_attempt_is_reconciled_as_interrupted_with_conservative_budget(monkeypatch) -> None:
    started = datetime.now(timezone.utc) - timedelta(seconds=12)
    rows = [
        {
            "id": 1,
            "cycle_id": "11111111-1111-1111-1111-111111111111",
            "stage_name": "scientist",
            "ordinal": 3,
            "outcome": "running",
            "operation_ok": False,
            "started_at": started.isoformat(),
            "finished_at": None,
            "elapsed_ms": 1000.0,
            "cpu_user_ms": None,
            "cpu_system_ms": None,
            "process_max_rss_mb": None,
            "result_summary": {},
        }
    ]
    client = PagedClient(rows)
    monkeypatch.setattr(main, "discovery_repo", SimpleNamespace(client=client))

    loaded = asyncio.run(main._cycle_stage_attempts(rows[0]["cycle_id"]))

    assert loaded[0]["outcome"] == "interrupted"
    assert loaded[0]["operation_ok"] is False
    assert float(loaded[0]["elapsed_ms"]) >= 10000.0
    assert loaded[0]["error"] == "restart_reconciled_unfinished_stage_attempt"
    assert client.patches


def test_supervisor_cancellation_terminates_child_and_persists_interruption(monkeypatch) -> None:
    started_at = datetime.now(timezone.utc)
    cleanup = []
    finalised = []

    class FakeProcess:
        returncode = None
        pid = 999999
        stdout = object()

    async def fake_start(*_args, **_kwargs):
        return 77, started_at

    async def fake_spawn(*_args, **_kwargs):
        return FakeProcess()

    async def forever(*_args, **_kwargs):
        await asyncio.Event().wait()

    async def fake_terminate(process):
        cleanup.append(process.pid)
        process.returncode = -15

    async def fake_finish(stage_run_id, *, outcome, reason, started_at):
        finalised.append((stage_run_id, outcome, reason))
        return 1000.0

    monkeypatch.setattr(main, "_start_stage_attempt", fake_start)
    monkeypatch.setattr(main.asyncio, "create_subprocess_exec", fake_spawn)
    monkeypatch.setattr(main, "_read_bounded_child", forever)
    monkeypatch.setattr(main, "_bounded_lease_heartbeat", forever)
    monkeypatch.setattr(main, "_terminate_bounded_child", fake_terminate)
    monkeypatch.setattr(main, "_finish_supervisor_stage_attempt", fake_finish)

    async def run():
        task = asyncio.create_task(
            main._run_bounded_stage(
                "11111111-1111-1111-1111-111111111111",
                "scientist",
                3,
                1500,
                owner_id="owner",
                lease_token="token",
            )
        )
        await asyncio.sleep(0)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

    asyncio.run(run())

    assert cleanup == [999999]
    assert finalised == [(77, "interrupted", "supervisor_cancelled_during_stage")]



def test_checkpoint_accepts_attempt_already_finalized_by_child(monkeypatch) -> None:
    class RaceClient:
        async def patch(self, table: str, values: dict, *, filters: dict):
            assert table == "bounded_research_stage_runs"
            return []

        async def get(self, table: str, *, params: dict | None = None, **_kwargs):
            assert table == "bounded_research_stage_runs"
            return [{
                "id": 77,
                "outcome": "progressed",
                "operation_ok": True,
                "finished_at": datetime.now(timezone.utc).isoformat(),
            }]

    monkeypatch.setattr(main, "discovery_repo", SimpleNamespace(client=RaceClient()))

    asyncio.run(
        main._checkpoint_stage_attempt(
            77,
            datetime.now(timezone.utc) - timedelta(seconds=5),
        )
    )


def test_checkpoint_fails_when_attempt_is_missing(monkeypatch) -> None:
    class MissingClient:
        async def patch(self, table: str, values: dict, *, filters: dict):
            return []

        async def get(self, table: str, *, params: dict | None = None, **_kwargs):
            return []

    monkeypatch.setattr(main, "discovery_repo", SimpleNamespace(client=MissingClient()))

    with pytest.raises(RuntimeError, match="checkpoint was not acknowledged"):
        asyncio.run(
            main._checkpoint_stage_attempt(
                78,
                datetime.now(timezone.utc) - timedelta(seconds=5),
            )
        )
