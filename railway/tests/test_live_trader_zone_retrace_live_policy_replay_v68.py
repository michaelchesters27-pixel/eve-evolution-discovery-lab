import asyncio
from types import SimpleNamespace

import pytest

from app.services import live_trader_zone_retrace_live_policy_replay_v68 as v68


def test_touch_probe_uses_open_when_already_inside_zone() -> None:
    probe, resolution = v68._touch_probe(
        {"open": 100.5, "low": 99.8, "high": 101.2},
        {"low": 100.0, "high": 101.0},
    )
    assert probe == 100.5
    assert resolution == "m1_open_inside_zone"


def test_touch_probe_uses_first_zone_boundary_when_bar_retraces_from_above() -> None:
    probe, resolution = v68._touch_probe(
        {"open": 102.0, "low": 100.7, "high": 102.1},
        {"low": 100.0, "high": 101.0},
    )
    assert probe == 101.0
    assert resolution == "m1_touch_from_above"


def test_touch_probe_returns_none_when_minute_never_reaches_zone() -> None:
    probe, resolution = v68._touch_probe(
        {"open": 102.0, "low": 101.4, "high": 102.3},
        {"low": 100.0, "high": 101.0},
    )
    assert probe is None
    assert resolution is None


def test_live_promotion_unlocks_only_from_completed_high_coverage_replay() -> None:
    payload = {
        "execution_evidence": {"market": {"opportunities": 173}},
        "best_execution": "market",
        "promoted_execution": "market",
        "live_policy_replay": {
            "replay_version": v68.REPLAY_VERSION,
            "status": "complete_promoted",
            "eligible_episodes": 100,
            "processed_episodes": 100,
            "scorable_episodes": 96,
            "unscorable_episodes": 4,
            "triggered": 50,
            "wins": 30,
            "losses": 20,
            "breakeven": 0,
            "total_r": 12.0,
            "expectancy_per_opportunity_r": 0.125,
            "expectancy_per_triggered_r": 0.24,
            "trigger_rate": 0.5208,
            "promoted": True,
            "completed": True,
            "policy": {"evaluation_horizon_minutes": 60},
        },
    }

    specialist = v68._evidence_contract_v68(payload)

    assert specialist["research_promoted_execution"] == "market"
    assert specialist["live_policy_expectancy_verified"] is True
    assert specialist["live_promoted_execution"] == "market_after_zone_confirmation"
    assert specialist["promoted_execution"] == "market_after_zone_confirmation"
    assert specialist["promotion_blocked"] is False
    assert specialist["live_strategy_edge_proven"] is False


def test_live_promotion_stays_blocked_when_replay_is_incomplete() -> None:
    payload = {
        "execution_evidence": {"market": {"opportunities": 173}},
        "best_execution": "market",
        "promoted_execution": "market",
        "live_policy_replay": {
            "replay_version": v68.REPLAY_VERSION,
            "status": "running",
            "eligible_episodes": 100,
            "processed_episodes": 70,
            "scorable_episodes": 70,
            "unscorable_episodes": 0,
            "triggered": 45,
            "wins": 30,
            "losses": 15,
            "breakeven": 0,
            "total_r": 20.0,
            "expectancy_per_opportunity_r": 0.2857,
            "expectancy_per_triggered_r": 0.4444,
            "trigger_rate": 0.6429,
            "promoted": True,
            "completed": False,
            "policy": {"evaluation_horizon_minutes": 60},
        },
    }

    specialist = v68._evidence_contract_v68(payload)

    assert specialist["live_policy_expectancy_verified"] is False
    assert specialist["live_promoted_execution"] is None
    assert specialist["promoted_execution"] is None
    assert specialist["promotion_blocked"] is True
    assert specialist["phase"] == "LIVE POLICY RESCORE RUNNING"


def test_live_promotion_stays_blocked_below_scorable_coverage_floor() -> None:
    payload = {
        "execution_evidence": {"market": {"opportunities": 173}},
        "best_execution": "market",
        "promoted_execution": "market",
        "live_policy_replay": {
            "replay_version": v68.REPLAY_VERSION,
            "status": "complete_not_promoted",
            "eligible_episodes": 100,
            "processed_episodes": 100,
            "scorable_episodes": 94,
            "unscorable_episodes": 6,
            "triggered": 50,
            "wins": 35,
            "losses": 15,
            "breakeven": 0,
            "total_r": 20.0,
            "expectancy_per_opportunity_r": 0.2128,
            "expectancy_per_triggered_r": 0.4,
            "trigger_rate": 0.5319,
            "promoted": True,
            "completed": True,
            "policy": {"evaluation_horizon_minutes": 60},
        },
    }

    specialist = v68._evidence_contract_v68(payload)

    assert specialist["live_policy_expectancy_verified"] is False
    assert specialist["live_promoted_execution"] is None
    assert specialist["promotion_blocked"] is True



class ResourceReplayClient:
    def __init__(self, snapshot: dict) -> None:
        self.snapshot = snapshot
        self.rpc_calls: list[tuple[str, dict]] = []
        self.upserts: list[tuple[str, dict, str]] = []

    async def rpc(self, function: str, payload: dict | None = None):
        self.rpc_calls.append((function, dict(payload or {})))
        return dict(self.snapshot)

    async def upsert(self, table: str, payload: dict, *, on_conflict: str, return_rows: bool = False):
        self.upserts.append((table, dict(payload), on_conflict))
        return []


def resource_replayer(snapshot: dict):
    client = ResourceReplayClient(snapshot)
    item = object.__new__(v68.ZoneRetraceLivePolicyReplayer)
    item.repo = SimpleNamespace(client=client)
    item.symbol = "XAU/USD"
    item.settings = SimpleNamespace(live_trader_learning_horizon_minutes=60)
    item.owner = SimpleNamespace(_zone_retrace_learning_v58={})
    item.last_error = None
    item.last_state = {}
    return item, client


def test_resource_work_snapshot_is_bounded_and_requires_complete_server_side_scan() -> None:
    snapshot = {
        "version": v68.RESOURCE_WORK_VERSION,
        "complete_server_side_scan": True,
        "eligible_episodes": 158,
        "processed_episodes": 158,
        "scorable_episodes": 158,
        "unscorable_episodes": 0,
        "triggered": 1,
        "wins": 1,
        "losses": 0,
        "breakeven": 0,
        "total_r": 1.5,
        "pending": [],
    }
    replayer, client = resource_replayer(snapshot)

    result = asyncio.run(replayer._work_snapshot())

    assert result == snapshot
    assert client.rpc_calls == [
        (
            "get_live_trader_zone_replay_work_v97",
            {
                "p_symbol": "XAU/USD",
                "p_replay_version": v68.REPLAY_VERSION,
                "p_limit": v68.REPLAY_BATCH_SIZE,
            },
        )
    ]


def test_resource_work_snapshot_fails_closed_if_server_side_scan_is_not_complete() -> None:
    replayer, _ = resource_replayer(
        {
            "version": v68.RESOURCE_WORK_VERSION,
            "complete_server_side_scan": False,
            "pending": [],
        }
    )

    with pytest.raises(RuntimeError, match="complete server-side scan"):
        asyncio.run(replayer._work_snapshot())


def test_resource_aggregate_preserves_current_v68_evidence_semantics() -> None:
    snapshot = {
        "version": v68.RESOURCE_WORK_VERSION,
        "complete_server_side_scan": True,
        "eligible_episodes": 158,
        "processed_episodes": 158,
        "scorable_episodes": 158,
        "unscorable_episodes": 0,
        "triggered": 1,
        "wins": 1,
        "losses": 0,
        "breakeven": 0,
        "total_r": 1.5,
        "pending": [],
    }
    replayer, client = resource_replayer(snapshot)

    state = asyncio.run(replayer._aggregate(snapshot))

    assert state["eligible_episodes"] == 158
    assert state["processed_episodes"] == 158
    assert state["scorable_episodes"] == 158
    assert state["triggered"] == 1
    assert state["wins"] == 1
    assert state["losses"] == 0
    assert state["total_r"] == 1.5
    assert state["expectancy_per_opportunity_r"] == 0.0095
    assert state["expectancy_per_triggered_r"] == 1.5
    assert state["trigger_rate"] == 0.0063
    assert state["promoted"] is False
    assert state["completed"] is True
    assert state["status"] == "complete_not_promoted"
    assert state["policy"]["resource_work_version"] == v68.RESOURCE_WORK_VERSION
    assert state["policy"]["complete_server_side_eligible_scan"] is True
    assert state["policy"]["historical_heap_scan_in_worker"] is False
    assert len(client.upserts) == 1
