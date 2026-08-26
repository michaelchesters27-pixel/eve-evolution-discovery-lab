from __future__ import annotations

import asyncio
from types import SimpleNamespace

from app.services import live_trader_campaign_consensus_v66 as v66
from app.services import live_trader_trade_lock_v28 as lock


class RaceClient:
    def __init__(self, authoritative: dict) -> None:
        self.authoritative = authoritative
        self.upsert_calls = 0
        self.get_calls = 0

    async def upsert(self, table, rows, *, on_conflict, return_rows=False):
        assert table == "live_trader_campaigns"
        self.upsert_calls += 1
        raise RuntimeError("simulated campaign write failure")

    async def get(self, table, *, params=None, range_start=None, range_end=None):
        assert table == "live_trader_campaigns"
        self.get_calls += 1
        return [{"campaign": dict(self.authoritative), "status": self.authoritative["status"]}]


class Engine:
    symbol = "XAU/USD"

    def __init__(self, client: RaceClient, local: dict, *, new_campaign: bool = True) -> None:
        self.repo = SimpleNamespace(client=client)
        self._live_campaign = local
        self._live_campaign_dirty = True
        self._live_campaign_new_v28 = new_campaign
        self._live_campaign_last_persisted_fingerprint = None


def campaign(campaign_id: str, *, status: str = "active", side: str = "BUY") -> dict:
    return {
        "version": lock.CAMPAIGN_VERSION,
        "id": campaign_id,
        "symbol": "XAU/USD",
        "status": status,
        "side": side,
        "order_type": "market",
        "entry": 100.0,
        "stop": 98.0 if side == "BUY" else 102.0,
        "target": 103.0 if side == "BUY" else 97.0,
        "risk_reward": 1.5,
        "confidence": 80,
        "reason": "zone retracement confirmation",
        "invalidation": "published stop",
        "invalidation_price": 98.0 if side == "BUY" else 102.0,
        "created_at": "2026-08-26T10:00:00+00:00",
        "expires_at": None,
        "triggered_at": "2026-08-26T10:00:00+00:00" if status == "active" else None,
        "completed_at": None,
        "result": None,
        "last_price": 100.0,
        "last_checked_at": "2026-08-26T10:00:00+00:00",
        "published_trade": {
            "action": f"{side} NOW",
            "side": side,
            "order_type": "market",
            "entry": 100.0,
            "stop": 98.0 if side == "BUY" else 102.0,
            "target": 103.0 if side == "BUY" else 97.0,
        },
    }


def test_losing_new_worker_adopts_different_database_open_campaign() -> None:
    local = campaign("local-loser", side="BUY")
    authoritative = campaign("db-winner", side="SELL")
    client = RaceClient(authoritative)
    engine = Engine(client, local, new_campaign=True)

    result = asyncio.run(v66._persist_campaign_v66(engine, local))

    assert result["id"] == "db-winner"
    assert engine._live_campaign["id"] == "db-winner"
    assert engine._live_campaign["side"] == "SELL"
    assert engine._live_campaign_dirty is False
    assert engine._live_campaign_new_v28 is False
    assert engine._campaign_consensus_last_v66["reconciled"] is True
    assert engine._campaign_consensus_last_v66["attempted_campaign_id"] == "local-loser"
    assert engine._campaign_consensus_last_v66["authoritative_campaign_id"] == "db-winner"
    assert client.upsert_calls == 1
    assert client.get_calls == 1


def test_existing_campaign_write_failure_never_rolls_transition_back() -> None:
    local = campaign("same-campaign", status="active", side="BUY")
    stale_database_copy = campaign("same-campaign", status="pending", side="BUY")
    client = RaceClient(stale_database_copy)
    engine = Engine(client, local, new_campaign=False)

    result = asyncio.run(v66._persist_campaign_v66(engine, local))

    assert result["status"] == "active"
    assert engine._live_campaign["status"] == "active"
    assert engine._live_campaign_dirty is True
    assert engine._live_campaign_new_v28 is False
    assert client.upsert_calls == 1
    # Existing campaign failures are retried; they do not consult an older DB
    # copy and therefore cannot roll active execution back to pending.
    assert client.get_calls == 0


def test_new_campaign_same_id_does_not_overwrite_local_state_on_write_failure() -> None:
    local = campaign("same-campaign", status="active", side="BUY")
    database_copy = campaign("same-campaign", status="pending", side="BUY")
    client = RaceClient(database_copy)
    engine = Engine(client, local, new_campaign=True)

    result = asyncio.run(v66._persist_campaign_v66(engine, local))

    assert result["status"] == "active"
    assert engine._live_campaign["status"] == "active"
    assert engine._live_campaign_dirty is True
    assert client.get_calls == 1


def test_authoritative_campaign_replaces_trade_geometry_in_state() -> None:
    state = {
        "setup": {"status": "TRADE ACTIVE"},
        "trade": {"side": "BUY", "entry": 100.0, "stop": 98.0, "target": 103.0},
        "trade_campaign": campaign("local-loser", side="BUY"),
    }
    authoritative = campaign("db-winner", side="SELL")

    v66._apply_campaign_to_state(state, authoritative)

    assert state["trade_campaign"]["id"] == "db-winner"
    assert state["trade"]["side"] == "SELL"
    assert state["trade"]["stop"] == 102.0
    assert state["trade"]["target"] == 97.0
    assert state["trade_lock"]["campaign_id"] == "db-winner"
    assert state["trade_lock"]["database_authoritative"] is True
