from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from typing import Any

from app.services import orchestrator_v3
from app.services.composer import mutation_batch
from app.services.orchestrator import canonical

SCIENTIST_PRIORITY_SCHEDULER_VERSION = "eve-scientist-priority-v3"
SCIENTIST_DATASET = "every_m5_fabric"
LEGACY_DATASET = "legacy_15m"
SCIENTIST_MUTATION_PRIORITY = 220
SCIENTIST_ATTEMPTS_PER_GENERATION = 12
SCIENTIST_SCAN_LIMIT = 100


OriginalDiscoveryOrchestrator = orchestrator_v3.DiscoveryOrchestrator


def _research_dataset_from_rules(rules: dict[str, Any]) -> str:
    return str((rules.get("market") or {}).get("research_dataset") or LEGACY_DATASET)


class ScientistPriorityDiscoveryOrchestrator(OriginalDiscoveryOrchestrator):
    """Give current every-M5 Scientist lineages a direct route to final research.

    The previous fairness layer only guaranteed four Generation-1 children. If
    those four children failed to beat the seed, a promising Scientist lineage
    could remain Generation 0 forever while the general legacy queue kept
    mutating older 15-minute lineages. This layer keeps bounded high-priority
    Scientist mutation work flowing until the configured minimum generation for
    a final exam is reached.

    Final-exam spending is also isolated by research dataset. Legacy 15-minute
    exams can no longer consume the every-M5 Scientist's monthly holdout budget.
    Selection, confirmation and holdout quality gates are unchanged.
    """

    @staticmethod
    def _scientist_seed(lineage_key: str, generation: int, slot: int, attempt: int) -> int:
        payload = f"scientist:{lineage_key}:{generation}:{slot}:{attempt}".encode()
        return int(hashlib.sha256(payload).hexdigest()[:12], 16)

    async def _scientist_lineage_needing_progression(
        self,
    ) -> tuple[dict[str, Any] | None, list[dict[str, Any]], int]:
        lineages = await self.repo.client.get(
            "mutation_lineages",
            params={
                "select": "*",
                "status": "eq.active",
                "order": "created_at.asc",
                "limit": str(SCIENTIST_SCAN_LIMIT),
            },
        )
        target_generation = max(1, int(self.settings.minimum_generations_before_final))
        for lineage in lineages:
            rules = dict(lineage.get("champion_rules") or {})
            if _research_dataset_from_rules(rules) != SCIENTIST_DATASET:
                continue
            current_generation = int(lineage.get("generation") or 0)
            if current_generation >= target_generation:
                continue
            next_generation = current_generation + 1
            lineage_id = str(lineage.get("id") or "")
            if not lineage_id:
                continue
            children = await self.repo.client.get(
                "mutation_candidates",
                params={
                    "select": "mutation_key,generation,status,promoted,priority,requested_at",
                    "lineage_id": f"eq.{lineage_id}",
                    "generation": f"eq.{next_generation}",
                    "order": "requested_at.asc",
                    "limit": str(SCIENTIST_ATTEMPTS_PER_GENERATION + 20),
                },
            )
            # Do not manufacture duplicate concurrent work. Let the existing
            # high-priority child finish before adding another one.
            if any(str(row.get("status") or "") in {"queued", "running"} for row in children):
                continue
            if len(children) < SCIENTIST_ATTEMPTS_PER_GENERATION:
                return dict(lineage), [dict(row) for row in children], next_generation
        return None, [], 0

    async def ensure_mutation_queue(self) -> int:
        queued = await self.repo.count_by_status("mutation_candidates", "queued")

        # A reserved Scientist child may temporarily take the queue one above the
        # normal floor. Its priority is deliberately above legacy mutation work,
        # so the atomic claim RPC takes it first on the next mutation claim.
        if queued <= self.settings.lineage_queue_floor:
            lineage, existing, generation = await self._scientist_lineage_needing_progression()
            if lineage is not None:
                memory = await self.repo.mutation_memory()
                lineage_key = str(lineage.get("lineage_key") or lineage.get("id") or "lineage")
                existing_keys = {str(row.get("mutation_key") or "") for row in existing}
                slot = len(existing) + 1
                created: list[dict[str, Any]] = []

                for attempt in range(32):
                    batch = mutation_batch(
                        lineage,
                        count=1,
                        generation=generation,
                        seed=self._scientist_seed(lineage_key, generation, slot, attempt),
                        memory=memory,
                    )
                    if not batch:
                        continue
                    candidate = dict(batch[0])
                    key = str(candidate.get("mutation_key") or "")
                    if key and key not in existing_keys:
                        candidate["priority"] = max(
                            SCIENTIST_MUTATION_PRIORITY,
                            int(candidate.get("priority") or 0),
                        )
                        created = [candidate]
                        break

                if created:
                    await self.repo.seed_mutations(created)
                    await self.repo.event(
                        "success",
                        "scientist_progression",
                        (
                            f"Reserved Scientist Generation-{generation} mutation {slot}/"
                            f"{SCIENTIST_ATTEMPTS_PER_GENERATION} for "
                            f"{lineage.get('name') or lineage_key}; current M5 research has priority over legacy evolution."
                        ),
                        {
                            "scheduler_version": SCIENTIST_PRIORITY_SCHEDULER_VERSION,
                            "research_dataset": SCIENTIST_DATASET,
                            "lineage_id": lineage.get("id"),
                            "lineage_key": lineage_key,
                            "generation": generation,
                            "attempt_slot": slot,
                            "attempt_limit": SCIENTIST_ATTEMPTS_PER_GENERATION,
                            "reserved_priority": SCIENTIST_MUTATION_PRIORITY,
                            "minimum_generation_before_final": self.settings.minimum_generations_before_final,
                            "queue_before": queued,
                            "queue_floor": self.settings.lineage_queue_floor,
                            "confirmation_holdout": "sealed",
                        },
                    )
                    self.last_action = (
                        f"Reserved Scientist Generation-{generation} mutation for "
                        f"{lineage.get('name') or lineage_key}"
                    )
                    return 1

        return await super().ensure_mutation_queue()

    def _dataset_for_rows(self, rows: list[dict[str, Any]]) -> str:
        if rows is getattr(self, "_fabric_rows_cache", None):
            return SCIENTIST_DATASET
        if rows and (
            rows[0].get("fabric_version")
            or rows[0].get("mtf_context") is not None
            or rows[0].get("mtf_context_complete") is not None
        ):
            return SCIENTIST_DATASET
        return LEGACY_DATASET

    async def _final_exam_available(self, rows: list[dict[str, Any]]) -> tuple[bool, str, int]:
        epoch = self._holdout_epoch(rows)
        research_dataset = self._dataset_for_rows(rows)
        existing = await self.repo.client.get(
            "final_exam_registry",
            params={
                "select": "id,details",
                "holdout_epoch": f"eq.{epoch}",
                "limit": "1000",
            },
        )
        used = 0
        for row in existing:
            details = dict(row.get("details") or {})
            recorded_dataset = str(details.get("research_dataset") or LEGACY_DATASET)
            if recorded_dataset == research_dataset:
                used += 1
        remaining = max(0, self.final_exams_per_epoch - used)
        self.final_exam_budget_status = {
            "epoch": epoch,
            "research_dataset": research_dataset,
            "used": used,
            "limit": self.final_exams_per_epoch,
            "remaining": remaining,
            "budget_scope": "per_research_dataset",
        }
        return used < self.final_exams_per_epoch, epoch, used

    async def _open_final_exam(self, mutation: dict[str, Any], selection: dict[str, Any], epoch: str) -> str | None:
        rules = dict(mutation.get("rules") or {})
        research_dataset = _research_dataset_from_rules(rules)
        rule_hash = hashlib.sha256(canonical(rules).encode()).hexdigest()
        rows = await self.repo.client.insert(
            "final_exam_registry",
            {
                "holdout_epoch": epoch,
                "lineage_id": mutation.get("lineage_id"),
                "mutation_id": mutation.get("id"),
                "rule_hash": rule_hash,
                "dataset_version": selection.get("dataset_version"),
                "status": "opened",
                "details": {
                    "name": mutation.get("name"),
                    "generation": mutation.get("generation"),
                    "research_integrity_version": orchestrator_v3.research.RESEARCH_INTEGRITY_VERSION,
                    "research_dataset": research_dataset,
                    "budget_scope": "per_research_dataset",
                },
            },
            return_rows=True,
        )
        return str(rows[0].get("id")) if rows else None

    def runtime_status(self) -> dict[str, Any]:
        status = super().runtime_status()
        status["scientist_priority_scheduler_version"] = SCIENTIST_PRIORITY_SCHEDULER_VERSION
        status["scientist_priority_scheduler"] = {
            "research_dataset": SCIENTIST_DATASET,
            "mutation_priority": SCIENTIST_MUTATION_PRIORITY,
            "attempts_per_generation": SCIENTIST_ATTEMPTS_PER_GENERATION,
            "progress_until_generation": self.settings.minimum_generations_before_final,
            "final_exam_budget_scope": "per_research_dataset",
            "selection_quality_gates": "unchanged",
            "checked_at": datetime.now(timezone.utc).isoformat(),
        }
        return status


# fair_lineage_scheduler has already replaced orchestrator_v3.DiscoveryOrchestrator
# during app package initialisation. Replace that exported class once more with
# this narrow Scientist-priority extension so app.main gets the final production
# orchestrator without changing its import surface.
orchestrator_v3.DiscoveryOrchestrator = ScientistPriorityDiscoveryOrchestrator
