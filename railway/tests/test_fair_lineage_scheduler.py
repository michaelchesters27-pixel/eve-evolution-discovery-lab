import asyncio
from types import SimpleNamespace

from app.services import orchestrator_v3
from app.services.fair_lineage_scheduler import (
    FIRST_GENERATION_PRIORITY,
    FIRST_GENERATION_TARGET,
    FairLineageDiscoveryOrchestrator,
)


def _rules():
    return {
        "family": "composed_signal",
        "market": {
            "symbol": "XAU/USD",
            "timeframe": "M5",
            "snapshot_interval": "5min",
            "source_interval": "5min",
            "research_dataset": "every_m5_fabric",
        },
        "schedule": {
            "weekdays": [1, 2, 3, 4, 5],
            "months": list(range(1, 13)),
            "sessions": ["new_york"],
            "hours_utc": [],
            "schedule_kind": "session",
            "everyday_target": True,
        },
        "environment": {
            "regimes": [],
            "trend_12": "any",
            "trend_48": "any",
            "compression": "any",
            "min_alignment_abs": 0,
            "alignment_sign": "any",
            "streak": "any",
        },
        "entry": {
            "direction_rule": "evidence_long",
            "condition_mode": "all",
            "conditions": [{"type": "break_prior_12_low"}],
        },
        "risk": {
            "stop_atr": 1.5,
            "target_atr": 3.0,
            "horizon_minutes": 30,
            "max_hold_minutes": 30,
            "cooldown_minutes": 15,
            "cost_r": 0.04,
            "risk_percent": 0.25,
            "max_daily_loss_percent": 1,
            "max_spread_points": 100,
        },
    }


class FakeClient:
    def __init__(self, lineage):
        self.lineage = lineage
        self.children = []

    async def get(self, table, *, params=None, **_kwargs):
        if table == "mutation_lineages":
            return [self.lineage]
        if table == "mutation_candidates":
            return list(self.children[:FIRST_GENERATION_TARGET])
        return []


class FakeRepo:
    def __init__(self, lineage):
        self.client = FakeClient(lineage)
        self.events = []

    async def count_by_status(self, table, status):
        assert table == "mutation_candidates"
        assert status == "queued"
        return 20

    async def mutation_memory(self):
        return []

    async def seed_mutations(self, rows):
        for row in rows:
            if row.get("mutation_key") not in {item.get("mutation_key") for item in self.client.children}:
                self.client.children.append(dict(row))

    async def event(self, level, component, message, details):
        self.events.append((level, component, message, details))


def _lineage():
    return {
        "id": "b81aba5c-952f-4cfb-ae8a-f5163917f95e",
        "lineage_key": "lineage-57f6b09f27ceae487dea8b69cd86",
        "family": "composed_signal",
        "name": "EVE Scientist 69CD86 · Rank 4",
        "generation": 0,
        "champion_kind": "seed",
        "champion_rules": _rules(),
        "champion_metrics": {"development": {}, "validation": {}},
        "champion_fitness": 36.1717086,
    }


def test_startup_exports_fair_orchestrator():
    assert orchestrator_v3.DiscoveryOrchestrator is FairLineageDiscoveryOrchestrator


def test_full_queue_cannot_starve_new_promising_lineage():
    settings = SimpleNamespace(lineage_queue_floor=20)
    repo = FakeRepo(_lineage())
    worker = FairLineageDiscoveryOrchestrator(settings, None, repo)

    created_each_cycle = [asyncio.run(worker.ensure_mutation_queue()) for _ in range(FIRST_GENERATION_TARGET)]

    assert created_each_cycle == [1, 1, 1, 1]
    assert len(repo.client.children) == FIRST_GENERATION_TARGET
    assert all(int(row.get("generation") or 0) == 1 for row in repo.client.children)
    assert all(int(row.get("priority") or 0) >= FIRST_GENERATION_PRIORITY for row in repo.client.children)
    assert len({row.get("mutation_key") for row in repo.client.children}) == FIRST_GENERATION_TARGET
    assert all(event[1] == "evolution_fairness" for event in repo.events)

    # Once the fair first generation exists, the normal full-queue rule applies
    # again; fairness cannot grow the mutation backlog without bound.
    assert asyncio.run(worker.ensure_mutation_queue()) == 0
    assert len(repo.client.children) == FIRST_GENERATION_TARGET


class WorkRepo:
    def __init__(self):
        self.events = []
        self.claims = []

    async def claim_candidate(self, _worker_id):
        self.claims.append("candidate_claim")
        return {"id": "candidate"}

    async def claim_mutation(self, _worker_id):
        self.claims.append("mutation_claim")
        return {"id": "mutation"}

    async def event(self, level, component, message, details):
        self.events.append((level, component, message, details))


class WorkAllocationHarness(FairLineageDiscoveryOrchestrator):
    def __init__(self):
        settings = SimpleNamespace(lineage_queue_floor=20)
        super().__init__(settings, None, WorkRepo())
        self.processed = []

    async def sync_source(self):
        return 0

    async def rows(self, force=False):
        return [{}] * 5000

    async def profile_legacy_package(self, rows):
        return False

    async def generate_pending_package(self):
        return False

    async def ensure_mutation_queue(self):
        return 0

    async def ensure_candidate_queue(self):
        return 0

    async def process_candidate(self, candidate, rows):
        self.processed.append("candidate")

    async def process_mutation(self, mutation, rows):
        self.processed.append("mutation")


def test_worker_alternates_candidate_and_mutation_when_both_queues_have_work():
    worker = WorkAllocationHarness()

    for _ in range(6):
        result = asyncio.run(worker.run_once())
        assert result["ok"] is True

    assert worker.processed == ["candidate", "mutation", "candidate", "mutation", "candidate", "mutation"]
