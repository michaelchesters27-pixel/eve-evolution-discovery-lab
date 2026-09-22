from __future__ import annotations

import asyncio
from types import SimpleNamespace

from app.services import live_trader_authoritative_state_v94 as v94


class FakeClient:
    def __init__(self) -> None:
        self.upserts: list[tuple[str, dict, str]] = []

    async def upsert(self, table: str, payload: dict, *, on_conflict: str, return_rows: bool = False):
        self.upserts.append((table, dict(payload), on_conflict))
        return []


class FakeRepo:
    def __init__(self) -> None:
        self.client = FakeClient()


def engine() -> SimpleNamespace:
    return SimpleNamespace(
        symbol="XAU/USD",
        repo=FakeRepo(),
        settings=SimpleNamespace(),
        _latest_state={},
        _last_persist_at=None,
        _authoritative_refresh_active_v94=False,
    )


def test_final_wrapper_defers_inner_persist_and_writes_complete_state(monkeypatch) -> None:
    item = engine()

    async def inner_refresh(self, *, force_rows: bool = False):
        state = {
            "symbol": "XAU/USD",
            "learning": {},
            "policy_lab_health": {"version": "eve-live-policy-lab-v85"},
            "evidence_provenance": {"version": "eve-live-evidence-provenance-v91"},
        }
        # Simulate the core refresh trying to persist before v85/v91/v94 finish.
        await v94._maybe_persist_state_v94(self, state)
        return state

    async def academy_snapshot(self, *, force: bool = False):
        return {
            "read_ok": True,
            "available": True,
            "expected_cohort_id": "coh_current",
            "state": {
                "cohort_id": "coh_current",
                "status": "caught_up_not_promoted",
                "caught_up": True,
                "updated_at": "2026-09-22T10:00:00+00:00",
            },
            "reason": None,
        }

    async def policy_summary(self):
        return {
            "summary_version": "eve-live-policy-lab-complete-summary-v93",
            "summary_completeness": {
                "complete": True,
                "rolling": False,
                "source": "server_side_sql_aggregation",
            },
            "leaderboard": [],
        }

    async def telemetry(self, *, force: bool = False):
        return {
            "version": v94.TELEMETRY_VERSION,
            "read_ok": True,
            "available": True,
            "cycle": {
                "cycle_id": "cycle-1",
                "outcome": "completed_with_progress",
            },
            "stages": [
                {"stage_name": "zone_replay", "outcome": "no_op"},
                {"stage_name": "current_policy", "outcome": "progressed"},
            ],
        }

    monkeypatch.setattr(v94, "_current_refresh_state", inner_refresh)
    monkeypatch.setattr(v94, "_academy_snapshot", academy_snapshot)
    monkeypatch.setattr(v94.policy_lab, "_policy_lab_summary", policy_summary)
    monkeypatch.setattr(v94, "_stage_telemetry_snapshot", telemetry)

    state = asyncio.run(v94._refresh_state_v94(item))

    # The attempted inner write was deferred; only the fully assembled final state
    # reached the durable state table.
    assert len(item.repo.client.upserts) == 1
    table, payload, conflict = item.repo.client.upserts[0]
    assert table == "live_trader_state"
    assert conflict == "symbol"
    persisted = payload["state"]
    assert persisted == state
    assert persisted["evidence_provenance"]["version"] == "eve-live-evidence-provenance-v91"
    assert persisted["policy_lab_health"]["summary_complete"] is True
    assert persisted["learning"]["policy_lab"]["summary_completeness"]["complete"] is True
    assert persisted["zone_retrace_current_policy_academy"]["caught_up"] is True
    assert persisted["bounded_research_telemetry"]["stages"][0]["outcome"] == "no_op"
    assert persisted["state_authority"]["authoritative"] is True
    assert persisted["state_authority"]["persisted_after_all_runtime_wrappers"] is True
    assert persisted["state_authority"]["current_policy_academy_status"] == "caught_up_not_promoted"
    assert persisted["state_authority"]["bounded_stage_cycle_id"] == "cycle-1"


def test_authoritative_state_marks_missing_academy_explicitly(monkeypatch) -> None:
    item = engine()

    async def inner_refresh(self, *, force_rows: bool = False):
        return {"symbol": "XAU/USD", "learning": {}, "policy_lab_health": {}}

    async def academy_snapshot(self, *, force: bool = False):
        return {
            "read_ok": True,
            "available": False,
            "expected_cohort_id": "coh_expected",
            "state": {},
            "reason": "current cohort has not produced a persisted academy state yet",
        }

    async def policy_summary(self):
        return {
            "summary_version": "eve-live-policy-lab-complete-summary-v93",
            "summary_completeness": {
                "complete": True,
                "rolling": False,
                "source": "server_side_sql_aggregation",
            },
            "leaderboard": [],
        }

    async def telemetry(self, *, force: bool = False):
        return {
            "version": v94.TELEMETRY_VERSION,
            "read_ok": True,
            "available": False,
            "cycle": None,
            "stages": [],
        }

    monkeypatch.setattr(v94, "_current_refresh_state", inner_refresh)
    monkeypatch.setattr(v94, "_academy_snapshot", academy_snapshot)
    monkeypatch.setattr(v94.policy_lab, "_policy_lab_summary", policy_summary)
    monkeypatch.setattr(v94, "_stage_telemetry_snapshot", telemetry)

    state = asyncio.run(v94._refresh_state_v94(item))
    academy_state = state["zone_retrace_current_policy_academy"]
    assert academy_state["status"] == "waiting_for_first_scan"
    assert academy_state["cohort_id"] == "coh_expected"
    assert state["state_authority"]["current_policy_academy_status"] == "waiting_for_first_scan"
