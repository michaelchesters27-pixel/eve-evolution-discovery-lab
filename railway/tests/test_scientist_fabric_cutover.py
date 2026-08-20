import asyncio
from types import SimpleNamespace

from app.services.intelligence_v2 import IntelligenceDirector
from app.services.orchestrator_v3 import DiscoveryOrchestrator
from app.services.research_fabric import (
    FABRIC_DATASET,
    FABRIC_SNAPSHOT_INTERVAL,
    FABRIC_SOURCE_INTERVAL,
    LEGACY_DATASET,
    hard_integrity_passes,
    initial_cutover_passes,
    resolve_dataset_state,
    rules_use_fabric,
)


class FakeClient:
    def __init__(self):
        self.state = {}
        self.upserts = []

    async def get(self, table, *, params=None, range_start=None, range_end=None):
        if table == "scientist_dataset_state" and self.state:
            return [dict(self.state)]
        return []

    async def upsert(self, table, rows, *, on_conflict, return_rows=False):
        payload = dict(rows) if isinstance(rows, dict) else dict(rows[0])
        self.upserts.append((table, payload, on_conflict))
        if table == "scientist_dataset_state":
            self.state = payload
        return []


class FakeRepo:
    def __init__(self):
        self.client = FakeClient()


def audit(*, caught_up=True, audit_current=True, parity=True, lookahead=True):
    gates = {
        "caught_up": caught_up,
        "audit_current": audit_current,
        "enough_history": True,
        "m1_coverage": True,
        "higher_timeframe_coverage": True,
        "historical_outcomes": True,
        "zero_lookahead": lookahead,
        "feature_parity": parity,
    }
    return {
        "ready_for_scientist_cutover": caught_up and all(gates.values()),
        "gates": gates,
        "fabric_version": "eve-multitimeframe-fabric-v1",
    }


def test_initial_cutover_requires_every_hard_gate_and_caught_up():
    assert initial_cutover_passes(audit()) is True
    assert initial_cutover_passes(audit(caught_up=False)) is False
    assert hard_integrity_passes(audit(caught_up=False)) is True
    assert hard_integrity_passes(audit(parity=False)) is False
    assert hard_integrity_passes(audit(lookahead=False)) is False


def test_verified_cutover_is_persistent_but_hard_integrity_can_suspend():
    repo = FakeRepo()

    first = asyncio.run(resolve_dataset_state(repo, "eve-autonomous-scientist-v2", audit()))
    assert first["active_dataset"] == FABRIC_DATASET
    assert first["status"] == "active"
    assert first["cutover_at"]

    # A newly arriving source candle can briefly make caught_up false. Once the
    # cutover is verified this must not flap the scientist back to legacy.
    second = asyncio.run(
        resolve_dataset_state(repo, "eve-autonomous-scientist-v2", audit(caught_up=False))
    )
    assert second["active_dataset"] == FABRIC_DATASET
    assert second["status"] == "active"
    assert second["cutover_at"] == first["cutover_at"]

    suspended = asyncio.run(
        resolve_dataset_state(repo, "eve-autonomous-scientist-v2", audit(caught_up=False, parity=False))
    )
    assert suspended["active_dataset"] == FABRIC_DATASET
    assert suspended["status"] == "suspended_integrity"


def test_rules_explicitly_bind_scientist_candidates_to_the_fabric():
    fabric_rules = {
        "market": {
            "snapshot_interval": FABRIC_SNAPSHOT_INTERVAL,
            "source_interval": FABRIC_SOURCE_INTERVAL,
            "research_dataset": FABRIC_DATASET,
        }
    }
    assert rules_use_fabric(fabric_rules) is True
    assert rules_use_fabric({"market": {"snapshot_interval": "15min", "source_interval": "5min"}}) is False


def test_scientist_proposals_are_tagged_with_active_dataset():
    settings = SimpleNamespace(
        source_symbol="XAU/USD",
        research_timeframe="M5",
        source_snapshot_interval="15min",
        source_candle_interval="5min",
        row_cache_minutes=15,
    )
    director = IntelligenceDirector(settings, FakeRepo(), lambda: None)
    director.active_dataset = FABRIC_DATASET
    director.active_snapshot_interval = FABRIC_SNAPSHOT_INTERVAL
    director.active_source_interval = FABRIC_SOURCE_INTERVAL
    proposals = director._proposals({}, set(), seed=12345)
    assert proposals
    for proposal in proposals:
        market = proposal["rules"]["market"]
        assert market["research_dataset"] == FABRIC_DATASET
        assert market["snapshot_interval"] == FABRIC_SNAPSHOT_INTERVAL
        assert market["source_interval"] == FABRIC_SOURCE_INTERVAL


def test_orchestrator_never_routes_fabric_rules_to_legacy_rows():
    orchestrator = DiscoveryOrchestrator.__new__(DiscoveryOrchestrator)
    legacy = [{"candle_time": "legacy"}]
    fabric = [{"candle_time": "fabric"}]

    async def authorised():
        return fabric

    orchestrator._authorised_fabric_rows = authorised

    fabric_item = {
        "rules": {
            "market": {
                "snapshot_interval": FABRIC_SNAPSHOT_INTERVAL,
                "source_interval": FABRIC_SOURCE_INTERVAL,
                "research_dataset": FABRIC_DATASET,
            }
        }
    }
    legacy_item = {"rules": {"market": {"research_dataset": LEGACY_DATASET}}}

    assert asyncio.run(orchestrator._rows_for_item(fabric_item, legacy)) is fabric
    assert asyncio.run(orchestrator._rows_for_item(legacy_item, legacy)) is legacy
