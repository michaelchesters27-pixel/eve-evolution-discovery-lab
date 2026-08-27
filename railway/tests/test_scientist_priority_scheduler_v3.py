import asyncio
from types import SimpleNamespace

from app.services import orchestrator_v3
from app.services.fair_lineage_scheduler import FairLineageDiscoveryOrchestrator
from app.services.scientist_priority_scheduler_v3 import (
    SCIENTIST_DATASET,
    SCIENTIST_MUTATION_PRIORITY,
    ScientistPriorityDiscoveryOrchestrator,
)


def _rules(dataset=SCIENTIST_DATASET):
    return {
        "family": "composed_signal",
        "market": {
            "symbol": "XAU/USD",
            "timeframe": "M5",
            "snapshot_interval": "5min",
            "source_interval": "5min",
            "research_dataset": dataset,
        },
        "schedule": {"weekdays": [1, 2, 3, 4, 5], "months": list(range(1, 13)), "sessions": ["london"]},
        "environment": {"regimes": [], "trend_12": "any", "trend_48": "any"},
        "entry": {
            "direction_rule": "current_direction",
            "condition_mode": "all",
            "conditions": [{"type": "direction_matches_trend12"}],
        },
        "risk": {
            "stop_atr": 1.0,
            "target_atr": 2.0,
            "horizon_minutes": 60,
            "max_hold_minutes": 60,
            "cooldown_minutes": 15,
            "cost_r": 0.04,
        },
    }


def _lineage(generation=1):
    return {
        "id": "11111111-1111-1111-1111-111111111111",
        "lineage_key": "lineage-scientist-test",
        "family": "composed_signal",
        "name": "EVE Scientist test",
        "generation": generation,
        "champion_kind": "mutation",
        "champion_id": "22222222-2222-2222-2222-222222222222",
        "champion_rules": _rules(),
        "champion_metrics": {"development": {}, "validation": {}},
        "champion_fitness": 50.0,
    }


class FakeClient:
    def __init__(self, lineage=None, exams=None):
        self.lineage = lineage
        self.exams = list(exams or [])
        self.children = []

    async def get(self, table, *, params=None, **_kwargs):
        if table == "mutation_lineages":
            return [self.lineage] if self.lineage else []
        if table == "mutation_candidates":
            generation_filter = str((params or {}).get("generation") or "")
            if generation_filter.startswith("eq."):
                generation = int(generation_filter.split(".", 1)[1])
                return [row for row in self.children if int(row.get("generation") or 0) == generation]
            return list(self.children)
        if table == "final_exam_registry":
            return list(self.exams)
        return []


class FakeRepo:
    def __init__(self, lineage=None, exams=None):
        self.client = FakeClient(lineage, exams)
        self.events = []

    async def count_by_status(self, table, status):
        assert table == "mutation_candidates"
        assert status == "queued"
        return 20

    async def mutation_memory(self):
        return []

    async def seed_mutations(self, rows):
        self.client.children.extend(dict(row) for row in rows)

    async def event(self, level, component, message, details):
        self.events.append((level, component, message, details))


def _settings():
    return SimpleNamespace(
        lineage_queue_floor=20,
        minimum_generations_before_final=3,
    )


def test_production_orchestrator_keeps_fairness_and_adds_scientist_priority():
    assert orchestrator_v3.DiscoveryOrchestrator is ScientistPriorityDiscoveryOrchestrator
    assert issubclass(ScientistPriorityDiscoveryOrchestrator, FairLineageDiscoveryOrchestrator)


def test_scientist_lineage_gets_reserved_progression_beyond_generation_one():
    repo = FakeRepo(_lineage(generation=1))
    worker = ScientistPriorityDiscoveryOrchestrator(_settings(), None, repo)

    created = asyncio.run(worker.ensure_mutation_queue())

    assert created == 1
    assert len(repo.client.children) == 1
    child = repo.client.children[0]
    assert int(child.get("generation") or 0) == 2
    assert int(child.get("priority") or 0) >= SCIENTIST_MUTATION_PRIORITY
    assert repo.events[-1][1] == "scientist_progression"
    assert repo.events[-1][3]["research_dataset"] == SCIENTIST_DATASET


def test_legacy_august_exams_do_not_consume_scientist_budget():
    legacy_exams = [{"id": f"legacy-{i}", "details": {}} for i in range(11)]
    scientist_exams = [
        {"id": "scientist-1", "details": {"research_dataset": SCIENTIST_DATASET}},
        {"id": "scientist-2", "details": {"research_dataset": SCIENTIST_DATASET}},
    ]
    repo = FakeRepo(exams=legacy_exams + scientist_exams)
    worker = ScientistPriorityDiscoveryOrchestrator(_settings(), None, repo)
    worker.final_exams_per_epoch = 8

    fabric_rows = [
        {
            "candle_time": "2026-08-27T20:35:00+00:00",
            "fabric_version": "eve-multitimeframe-fabric-v1",
        }
    ]
    available, epoch, used = asyncio.run(worker._final_exam_available(fabric_rows))

    assert available is True
    assert epoch == "2026-08"
    assert used == 2
    assert worker.final_exam_budget_status["research_dataset"] == SCIENTIST_DATASET
    assert worker.final_exam_budget_status["remaining"] == 6

    legacy_rows = [{"candle_time": "2026-08-27T20:35:00+00:00"}]
    legacy_available, _, legacy_used = asyncio.run(worker._final_exam_available(legacy_rows))
    assert legacy_available is False
    assert legacy_used == 11
