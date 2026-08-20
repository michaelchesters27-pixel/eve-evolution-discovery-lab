from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from typing import Any

from app.services import orchestrator_v3
from app.services.composer import mutation_batch

FAIR_LINEAGE_SCHEDULER_VERSION = "eve-lineage-fairness-v1"
FIRST_GENERATION_TARGET = 4
FIRST_GENERATION_PRIORITY = 120
UNSTARTED_SCAN_LIMIT = 100


OriginalDiscoveryOrchestrator = orchestrator_v3.DiscoveryOrchestrator


class FairLineageDiscoveryOrchestrator(OriginalDiscoveryOrchestrator):
    """Prevent new promising lineages from being starved by old mutation work.

    The normal queue remains fitness-driven. A Generation-0 active lineage that
    has not yet received four Generation-1 children gets one reserved high-priority
    child whenever the queue is at or below its configured floor. This keeps the
    queue bounded while guaranteeing that every promising discovery gets a fair
    first evolutionary test.
    """

    async def _lineage_needing_first_generation(self) -> tuple[dict[str, Any] | None, list[dict[str, Any]]]:
        lineages = await self.repo.client.get(
            "mutation_lineages",
            params={
                "select": "*",
                "status": "eq.active",
                "generation": "eq.0",
                "order": "created_at.desc",
                "limit": str(UNSTARTED_SCAN_LIMIT),
            },
        )
        for lineage in lineages:
            lineage_id = str(lineage.get("id") or "")
            if not lineage_id:
                continue
            children = await self.repo.client.get(
                "mutation_candidates",
                params={
                    "select": "mutation_key,generation,status,requested_at",
                    "lineage_id": f"eq.{lineage_id}",
                    "generation": "eq.1",
                    "order": "requested_at.asc",
                    "limit": str(FIRST_GENERATION_TARGET),
                },
            )
            if len(children) < FIRST_GENERATION_TARGET:
                return dict(lineage), [dict(row) for row in children]
        return None, []

    @staticmethod
    def _fair_seed(lineage_key: str, slot: int, attempt: int) -> int:
        payload = f"{lineage_key}:{slot}:{attempt}".encode()
        return int(hashlib.sha256(payload).hexdigest()[:12], 16)

    async def ensure_mutation_queue(self) -> int:
        queued = await self.repo.count_by_status("mutation_candidates", "queued")

        # Never let fairness grow an already-overfull queue. At the normal floor,
        # one reserved child may temporarily make floor+1; the worker immediately
        # claims that priority-120 child, bringing the queue back to its floor.
        if queued <= self.settings.lineage_queue_floor:
            lineage, existing = await self._lineage_needing_first_generation()
            if lineage is not None:
                memory = await self.repo.mutation_memory()
                lineage_key = str(lineage.get("lineage_key") or lineage.get("id") or "lineage")
                existing_keys = {str(row.get("mutation_key") or "") for row in existing}
                slot = len(existing) + 1
                created: list[dict[str, Any]] = []

                # Different deterministic slot seeds make duplicate one-gene
                # children unlikely; the explicit key check prevents reseeding an
                # identical child if the grammar happens to choose the same gene.
                for attempt in range(12):
                    batch = mutation_batch(
                        lineage,
                        count=1,
                        generation=1,
                        seed=self._fair_seed(lineage_key, slot, attempt),
                        memory=memory,
                    )
                    if not batch:
                        continue
                    candidate = dict(batch[0])
                    key = str(candidate.get("mutation_key") or "")
                    if key and key not in existing_keys:
                        candidate["priority"] = max(FIRST_GENERATION_PRIORITY, int(candidate.get("priority") or 0))
                        created = [candidate]
                        break

                if created:
                    await self.repo.seed_mutations(created)
                    await self.repo.event(
                        "success",
                        "evolution_fairness",
                        (
                            f"Reserved Generation-1 mutation {slot}/{FIRST_GENERATION_TARGET} for "
                            f"{lineage.get('name') or lineage_key}; new promising lineages cannot be starved by old queue work."
                        ),
                        {
                            "scheduler_version": FAIR_LINEAGE_SCHEDULER_VERSION,
                            "lineage_id": lineage.get("id"),
                            "lineage_key": lineage_key,
                            "generation": 1,
                            "first_generation_slot": slot,
                            "first_generation_target": FIRST_GENERATION_TARGET,
                            "reserved_priority": FIRST_GENERATION_PRIORITY,
                            "queue_before": queued,
                            "queue_floor": self.settings.lineage_queue_floor,
                            "confirmation_holdout": "sealed",
                        },
                    )
                    self.last_action = f"Reserved fair Generation-1 mutation for {lineage.get('name') or lineage_key}"
                    return len(created)

        return await super().ensure_mutation_queue()

    def runtime_status(self) -> dict[str, Any]:
        status = super().runtime_status()
        status["lineage_scheduler_version"] = FAIR_LINEAGE_SCHEDULER_VERSION
        status["lineage_scheduler"] = {
            "policy": "guaranteed first-generation access, then normal fitness competition",
            "first_generation_target": FIRST_GENERATION_TARGET,
            "reserved_priority": FIRST_GENERATION_PRIORITY,
            "queue_floor": self.settings.lineage_queue_floor,
            "checked_at": datetime.now(timezone.utc).isoformat(),
        }
        return status


# app.main imports orchestrator_v3 after the app package initializer. Replacing
# the exported class here keeps the production import stable while installing the
# fairness policy as a narrow, testable extension of the v3 integrity orchestrator.
orchestrator_v3.DiscoveryOrchestrator = FairLineageDiscoveryOrchestrator
