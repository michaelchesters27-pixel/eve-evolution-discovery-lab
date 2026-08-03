from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import random
import socket
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

from app.settings import Settings
from app.services.backtest import compare_child_to_parent, evaluate_strategy, number
from app.services.composer import compose_batch, mutation_batch
from app.services.mt5_generator import package_payload
from app.services.repository import DiscoveryRepository, SourceRepository

logger = logging.getLogger(__name__)


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def canonical(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)


def compact_value(value: Any, limit: int = 90) -> str:
    text = json.dumps(value, sort_keys=True, default=str) if isinstance(value, (dict, list)) else str(value)
    return text if len(text) <= limit else text[: limit - 1] + "…"


def mutation_change_text(mutation: dict[str, Any]) -> str:
    gene = str(mutation.get("mutation_gene") or "rule")
    payload = dict(mutation.get("changes") or {}).get(gene) or {}
    return f"{gene}: {compact_value(payload.get('from'))} → {compact_value(payload.get('to'))}"


def result_gate_reason(result: dict[str, Any]) -> str:
    evidence = dict(result.get("evidence") or {})
    decision = dict(evidence.get("decision") or {})
    failed = [str(item).replace("_", " ") for item in decision.get("failed_gates") or []]
    return ", ".join(failed[:3]) if failed else "all promotion gates passed"


class DiscoveryOrchestrator:
    def __init__(self, settings: Settings, source: SourceRepository, repo: DiscoveryRepository) -> None:
        self.settings = settings
        self.source = source
        self.repo = repo
        self.worker_id = f"discovery-{socket.gethostname()}-{uuid.uuid4().hex[:8]}"
        self._stop = asyncio.Event()
        self._wake = asyncio.Event()
        self._rows_cache: list[dict[str, Any]] = []
        self._cache_at: datetime | None = None
        self.last_action = "Starting"
        self.last_error: str | None = None
        self.cycle_count = 0

    async def stop(self) -> None:
        self._stop.set()
        self._wake.set()

    async def wake(self) -> None:
        self._wake.set()

    async def rows(self, force: bool = False) -> list[dict[str, Any]]:
        fresh_until = (self._cache_at or datetime.min.replace(tzinfo=timezone.utc)) + timedelta(minutes=self.settings.row_cache_minutes)
        if force or not self._rows_cache or utc_now() >= fresh_until:
            self._rows_cache = await self.repo.all_snapshots()
            self._cache_at = utc_now()
        return self._rows_cache

    async def sync_source(self) -> int:
        local = await self.repo.latest_local_snapshot_time()
        source_latest = await self.source.latest_snapshot_time()
        if source_latest is None or (local is not None and local >= source_latest):
            return 0
        fetched = await self.source.fetch_snapshots_after(local, limit=self.settings.bridge_batch_limit)
        if not fetched:
            return 0
        for start in range(0, len(fetched), 500):
            await self.repo.upsert_snapshots(fetched[start:start + 500])
        self._cache_at = None
        await self.repo.event(
            "success",
            "source_bridge",
            f"Source memory advanced through {str(fetched[-1].get('candle_time') or '')[:10]} (+{len(fetched):,} snapshots).",
            {
                "imported": len(fetched),
                "from": local,
                "to": fetched[-1].get("candle_time"),
                "source_latest": source_latest,
                "caught_up": len(fetched) < self.settings.bridge_batch_limit,
            },
        )
        self.last_action = f"Synced {len(fetched):,} source snapshots"
        return len(fetched)

    async def ensure_candidate_queue(self) -> int:
        queued = await self.repo.count_by_status("strategy_candidates", "queued")
        if queued >= self.settings.candidate_queue_floor:
            return 0
        memory = await self.repo.mutation_memory()
        generation = max(1, self.cycle_count // 100 + 1)
        seed = int(utc_now().timestamp()) // 60 + generation
        batch = compose_batch(
            self.settings.candidates_per_seed,
            generation,
            seed,
            memory,
            everyday_bias=0.75,
        )
        await self.repo.seed_candidates(batch)
        await self.repo.event(
            "info", "composer", f"Composed {len(batch)} structurally valid strategy candidates.",
            {"generation": generation, "everyday_target": sum(1 for item in batch if item["rules"]["schedule"]["everyday_target"])},
        )
        self.last_action = f"Composed {len(batch)} new candidates"
        return len(batch)

    async def ensure_mutation_queue(self) -> int:
        queued = await self.repo.count_by_status("mutation_candidates", "queued")
        if queued >= self.settings.lineage_queue_floor:
            return 0
        lineages = await self.repo.active_lineages(30)
        if not lineages:
            return 0
        memory = await self.repo.mutation_memory()
        created: list[dict[str, Any]] = []
        needed = self.settings.lineage_queue_floor - queued
        for index, lineage in enumerate(lineages):
            if len(created) >= needed:
                break
            generation = int(number(lineage.get("generation"))) + 1
            created.extend(mutation_batch(
                lineage,
                count=min(4, needed - len(created)),
                generation=generation,
                seed=(int(utc_now().timestamp()) // 60) + index + generation * 997,
                memory=memory,
            ))
        await self.repo.seed_mutations(created)
        if created:
            await self.repo.event(
                "info", "evolution", f"Queued {len(created)} controlled child mutations.",
                {"lineages_considered": len(lineages)},
            )
            self.last_action = f"Queued {len(created)} mutations"
        return len(created)

    def ready_to_freeze(self, result: dict[str, Any]) -> bool:
        metrics = dict(result.get("metrics") or {})
        validation = dict(metrics.get("validation") or {})
        locked = dict(metrics.get("locked") or {})
        recent = dict(metrics.get("recent") or {})
        robustness = dict(result.get("robustness") or {})
        return (
            result.get("result_status") in {"validated", "elite"}
            and number(validation.get("trades")) >= self.settings.minimum_validation_trades
            and number(locked.get("trades")) >= self.settings.minimum_locked_trades
            and number(validation.get("profit_factor")) >= 1.10
            and number(locked.get("profit_factor")) >= 1.18
            and number(locked.get("expectancy_r")) >= 0.04
            and number(recent.get("profit_factor")) >= 1.00
            and number(recent.get("expectancy_r")) >= -0.01
            and number(robustness.get("pass_rate")) >= 0.50
            and number(result.get("stability_score")) >= 60.0
        )

    async def maybe_freeze(self, source_kind: str, source: dict[str, Any], result: dict[str, Any]) -> None:
        if not self.ready_to_freeze(result):
            return
        rules = dict(source.get("rules") or {})
        rule_hash = hashlib.sha256(canonical(rules).encode()).hexdigest()
        code = f"EVE-DISC-{rule_hash[:12].upper()}"
        frozen = {
            "frozen_key": f"frozen-{rule_hash[:28]}",
            "strategy_code": code,
            "name": source.get("name") or code,
            "family": source.get("family") or rules.get("family"),
            "source_kind": source_kind,
            "source_id": source.get("id"),
            "rule_hash": rule_hash,
            "rules": rules,
            "metrics": result.get("metrics") or {},
            "walk_forward": result.get("walk_forward") or {},
            "robustness": result.get("robustness") or {},
            "evidence": result.get("evidence") or {},
            "stability_score": result.get("stability_score") or 0,
            "fitness_score": result.get("fitness_score") or 0,
            "package_status": "pending",
            "status": "frozen",
        }
        await self.repo.freeze_strategy(frozen)
        await self.repo.event(
            "success", "promotion", f"Frozen {frozen['name']} for MT5 source generation.",
            {"strategy_code": code, "source_kind": source_kind, "rule_hash": rule_hash},
        )
        self.last_action = f"Frozen {code}"

    async def process_candidate(self, candidate: dict[str, Any], rows: list[dict[str, Any]]) -> None:
        try:
            result = evaluate_strategy(
                candidate, rows,
                min_validation_trades=self.settings.minimum_validation_trades,
                min_locked_trades=self.settings.minimum_locked_trades,
            )
            await self.repo.finish_candidate(str(candidate["id"]), result)
            completed = {**candidate, **result}
            if result["result_status"] in {"promising", "validated", "elite"}:
                await self.repo.ensure_lineage_for_candidate(completed)
            await self.maybe_freeze("seed", candidate, result)
            locked = dict(result.get("metrics", {}).get("locked") or {})
            reason = result_gate_reason(result)
            await self.repo.event(
                "success" if result["result_status"] != "rejected" else "info",
                "candidate_test",
                (
                    f"{candidate.get('name')} → {result['result_status']}. "
                    f"Locked PF {number(locked.get('profit_factor')):.2f}, "
                    f"expectancy {number(locked.get('expectancy_r')):+.3f}R, "
                    f"{int(number(locked.get('trades')))} trades. Decision: {reason}."
                ),
                {
                    "fitness": result.get("fitness_score"),
                    "summary": result.get("evidence", {}).get("summary"),
                    "decision": result.get("evidence", {}).get("decision"),
                    "candidate_key": candidate.get("candidate_key"),
                },
            )
            self.last_action = f"Candidate {result['result_status']}: {candidate.get('name')}"
        except Exception as exc:
            await self.repo.fail_candidate(str(candidate["id"]), str(exc))
            raise

    async def process_mutation(self, mutation: dict[str, Any], rows: list[dict[str, Any]]) -> None:
        try:
            child_result = evaluate_strategy(
                mutation, rows,
                min_validation_trades=self.settings.minimum_validation_trades,
                min_locked_trades=self.settings.minimum_locked_trades,
            )
            selection = compare_child_to_parent(
                child_result,
                dict(mutation.get("parent_metrics") or {}),
                number(mutation.get("parent_fitness")),
            )
            await self.repo.finish_mutation(str(mutation["id"]), selection)
            await self.repo.update_lineage_from_mutation(str(mutation["lineage_id"]), mutation, selection)
            await self.repo.record_mutation_memory(
                str(mutation.get("family") or "unknown"),
                str(mutation.get("mutation_gene") or "unknown"),
                bool(selection.get("promoted")),
                number(selection.get("fitness_delta")),
            )
            if selection.get("promoted"):
                await self.maybe_freeze("mutation", mutation, selection)
            change = mutation_change_text(mutation)
            await self.repo.event(
                "success" if selection.get("promoted") else "info",
                "mutation_test",
                (
                    f"{'PROMOTED' if selection.get('promoted') else 'REJECTED'} mutation — {change}. "
                    f"Fitness {number(selection.get('fitness_delta')):+.2f}; "
                    f"validation expectancy {number(selection.get('validation_expectancy_delta')):+.3f}R; "
                    f"validation PF {number(selection.get('validation_pf_delta')):+.2f}."
                ),
                {
                    "mutation": mutation.get("name"),
                    "gene": mutation.get("mutation_gene"),
                    "changes": mutation.get("changes") or {},
                    "promoted": bool(selection.get("promoted")),
                    "selection_reason": selection.get("selection_reason"),
                    "fitness_delta": selection.get("fitness_delta"),
                    "validation_expectancy_delta": selection.get("validation_expectancy_delta"),
                    "validation_pf_delta": selection.get("validation_pf_delta"),
                },
            )
            self.last_action = f"Mutation {'promoted' if selection.get('promoted') else 'rejected'}: {mutation.get('name')}"
        except Exception as exc:
            await self.repo.fail_mutation(str(mutation["id"]), str(exc))
            raise

    async def generate_pending_package(self) -> bool:
        if not self.settings.mt5_generation_enabled:
            return False
        pending = await self.repo.frozen_without_package(1)
        if not pending:
            return False
        frozen = pending[0]
        payload = package_payload(frozen)
        rows = await self.repo.store_package({**payload, "frozen_strategy_id": frozen.get("id")})
        package_id = str(rows[0]["id"]) if rows else ""
        if package_id:
            await self.repo.mark_frozen_packaged(str(frozen["id"]), package_id)
        await self.repo.event(
            "success", "mt5_generator", f"Created downloadable MT5 package {payload['file_name']}.",
            {"sha256": payload["sha256"], "size_bytes": payload["size_bytes"]},
        )
        self.last_action = f"Generated MT5 package {payload['file_name']}"
        return True

    async def run_once(self) -> dict[str, Any]:
        self.cycle_count += 1
        self.last_error = None
        actions: list[str] = []
        try:
            synced = await self.sync_source()
            if synced:
                actions.append(f"synced:{synced}")

            rows = await self.rows(force=bool(synced))
            if len(rows) < 5000:
                actions.append("waiting_for_data")
                self.last_action = f"Waiting for source bridge ({len(rows):,} snapshots local)"
                return {"ok": True, "actions": actions, "rows": len(rows)}

            if await self.generate_pending_package():
                actions.append("generated_package")
                return {"ok": True, "actions": actions, "rows": len(rows)}

            candidate = await self.repo.claim_candidate(self.worker_id)
            if candidate:
                await self.process_candidate(candidate, rows)
                actions.append("tested_candidate")
                return {"ok": True, "actions": actions, "rows": len(rows)}

            mutation = await self.repo.claim_mutation(self.worker_id)
            if mutation:
                await self.process_mutation(mutation, rows)
                actions.append("tested_mutation")
                return {"ok": True, "actions": actions, "rows": len(rows)}

            seeded = await self.ensure_candidate_queue()
            if seeded:
                actions.append(f"seeded:{seeded}")
            mutations = await self.ensure_mutation_queue()
            if mutations:
                actions.append(f"mutations:{mutations}")
            if not actions:
                self.last_action = "All queues healthy; waiting for next cycle"
                actions.append("idle")
            return {"ok": True, "actions": actions, "rows": len(rows)}
        except Exception as exc:
            self.last_error = str(exc)
            self.last_action = "Cycle failed safely"
            logger.exception("Discovery cycle failed")
            try:
                await self.repo.event("error", "orchestrator", "Discovery cycle failed safely.", {"error": str(exc)})
            except Exception:
                logger.exception("Could not record failure event")
            return {"ok": False, "actions": actions, "error": str(exc)}

    async def run_forever(self) -> None:
        await asyncio.sleep(self.settings.startup_delay_seconds)
        while not self._stop.is_set():
            result = await self.run_once()
            delay = self.settings.cycle_seconds if result.get("ok") else self.settings.idle_seconds
            self._wake.clear()
            try:
                await asyncio.wait_for(self._wake.wait(), timeout=delay)
            except asyncio.TimeoutError:
                pass

    def runtime_status(self) -> dict[str, Any]:
        return {
            "worker_id": self.worker_id,
            "cycle_count": self.cycle_count,
            "last_action": self.last_action,
            "last_error": self.last_error,
            "autonomous_enabled": self.settings.autonomous_enabled,
        }
