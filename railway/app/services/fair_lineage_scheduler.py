from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from typing import Any

from app.services import orchestrator_v3
from app.services.composer import mutation_batch

FAIR_LINEAGE_SCHEDULER_VERSION = "eve-lineage-fairness-v2"
FIRST_GENERATION_TARGET = 4
FIRST_GENERATION_PRIORITY = 120
UNSTARTED_SCAN_LIMIT = 100


OriginalDiscoveryOrchestrator = orchestrator_v3.DiscoveryOrchestrator


class FairLineageDiscoveryOrchestrator(OriginalDiscoveryOrchestrator):
    """Prevent promising lineages and mutation work from being starved.

    The normal queue remains fitness-driven after a fair first generation. A
    Generation-0 active lineage that has fewer than four Generation-1 children
    receives one reserved high-priority child whenever the queue is at or below
    its configured floor. Worker cycles also alternate candidate-first and
    mutation-first processing when both queues have work.
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
        # one reserved child may temporarily make floor+1; a mutation-first cycle
        # claims that priority-120 child and returns the queue to its normal floor.
        if queued <= self.settings.lineage_queue_floor:
            lineage, existing = await self._lineage_needing_first_generation()
            if lineage is not None:
                memory = await self.repo.mutation_memory()
                lineage_key = str(lineage.get("lineage_key") or lineage.get("id") or "lineage")
                existing_keys = {str(row.get("mutation_key") or "") for row in existing}
                slot = len(existing) + 1
                created: list[dict[str, Any]] = []

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

    async def run_once(self) -> dict[str, Any]:
        """Run one autonomous cycle with bounded candidate/mutation fairness."""
        self.cycle_count += 1
        self.last_cycle_at = datetime.now(timezone.utc).isoformat()
        self.last_error = None
        actions: list[str] = []
        try:
            synced = await self.sync_source()
            if synced:
                actions.append(f"synced:{synced}")

            rows = await self.rows(force=bool(synced))
            if len(rows) < 5000:
                actions.append("waiting_for_data")
                self.last_action = f"Waiting for source bridge ({len(rows):,} research states local)"
                self.last_successful_cycle_at = datetime.now(timezone.utc).isoformat()
                return {"ok": True, "actions": actions, "rows": len(rows)}

            if await self.profile_legacy_package(rows):
                actions.append("profiled_legacy_package")
                self.last_successful_cycle_at = datetime.now(timezone.utc).isoformat()
                return {"ok": True, "actions": actions, "rows": len(rows)}

            if await self.generate_pending_package():
                actions.append("generated_package")
                self.last_successful_cycle_at = datetime.now(timezone.utc).isoformat()
                return {"ok": True, "actions": actions, "rows": len(rows)}

            # Give a new promising lineage access to Generation 1 before claiming
            # the next unit of research work. This is intentionally bounded to one
            # reserved child per cycle.
            reserved = await self.ensure_mutation_queue()
            if reserved:
                actions.append(f"mutations:{reserved}")

            # The legacy loop always claimed a normal candidate first, which could
            # starve a non-empty mutation queue forever. Alternate the preferred
            # queue every cycle and fall back to the other queue if it is empty.
            mutation_first = self.cycle_count % 2 == 0
            if mutation_first:
                mutation = await self.repo.claim_mutation(self.worker_id)
                if mutation:
                    await self.process_mutation(mutation, rows)
                    actions.append("tested_mutation")
                    self.last_successful_cycle_at = datetime.now(timezone.utc).isoformat()
                    return {"ok": True, "actions": actions, "rows": len(rows)}
                candidate = await self.repo.claim_candidate(self.worker_id)
                if candidate:
                    await self.process_candidate(candidate, rows)
                    actions.append("tested_candidate")
                    self.last_successful_cycle_at = datetime.now(timezone.utc).isoformat()
                    return {"ok": True, "actions": actions, "rows": len(rows)}
            else:
                candidate = await self.repo.claim_candidate(self.worker_id)
                if candidate:
                    await self.process_candidate(candidate, rows)
                    actions.append("tested_candidate")
                    self.last_successful_cycle_at = datetime.now(timezone.utc).isoformat()
                    return {"ok": True, "actions": actions, "rows": len(rows)}
                mutation = await self.repo.claim_mutation(self.worker_id)
                if mutation:
                    await self.process_mutation(mutation, rows)
                    actions.append("tested_mutation")
                    self.last_successful_cycle_at = datetime.now(timezone.utc).isoformat()
                    return {"ok": True, "actions": actions, "rows": len(rows)}

            seeded = await self.ensure_candidate_queue()
            if seeded:
                actions.append(f"seeded:{seeded}")
            if not reserved:
                mutations = await self.ensure_mutation_queue()
                if mutations:
                    actions.append(f"mutations:{mutations}")
            if not actions:
                self.last_action = "All research queues healthy; waiting for next cycle"
                actions.append("idle")
            self.last_successful_cycle_at = datetime.now(timezone.utc).isoformat()
            return {"ok": True, "actions": actions, "rows": len(rows)}
        except Exception as exc:
            self.last_error = str(exc)
            self.last_action = "Cycle failed safely"
            try:
                await self.repo.event(
                    "error",
                    "orchestrator",
                    "Discovery cycle failed safely.",
                    {"error": str(exc), "scheduler_version": FAIR_LINEAGE_SCHEDULER_VERSION},
                )
            except Exception:
                pass
            return {"ok": False, "error": str(exc), "actions": actions}

    def runtime_status(self) -> dict[str, Any]:
        status = super().runtime_status()
        status["lineage_scheduler_version"] = FAIR_LINEAGE_SCHEDULER_VERSION
        status["lineage_scheduler"] = {
            "policy": "guaranteed first-generation access, then alternating candidate/mutation work and normal fitness competition",
            "first_generation_target": FIRST_GENERATION_TARGET,
            "reserved_priority": FIRST_GENERATION_PRIORITY,
            "queue_floor": self.settings.lineage_queue_floor,
            "work_allocation": "alternate candidate-first and mutation-first cycles",
            "checked_at": datetime.now(timezone.utc).isoformat(),
        }
        return status


# app.main imports orchestrator_v3 after the app package initializer. Replacing
# the exported class here keeps the production import stable while installing the
# fairness policy as a narrow, testable extension of the v3 integrity orchestrator.
orchestrator_v3.DiscoveryOrchestrator = FairLineageDiscoveryOrchestrator
