from __future__ import annotations

import hashlib
import os
from datetime import timedelta
from typing import Any

# Patch deterministic research semantics before importing the legacy orchestrator.
from app.services import backtest_v3 as research
from app.services import orchestrator as base
from app.services.m1_replay import validate_with_m1
from app.services.research_fabric import (
    FABRIC_DATASET,
    dataset_state,
    fabric_audit,
    hard_integrity_passes,
    load_fabric_rows,
    rules_use_fabric,
)

SCIENTIST_VERSION = "eve-autonomous-scientist-v2"


def _env_int(name: str, default: int, low: int, high: int) -> int:
    try:
        value = int(os.getenv(name, str(default)))
    except (TypeError, ValueError):
        value = default
    return max(low, min(high, value))


class DiscoveryOrchestrator(base.DiscoveryOrchestrator):
    """Research-integrity v3 orchestrator.

    Adds causal market observations, actual-entry-time selection locking, moving
    block Monte Carlo (via backtest_v3), a global final-exam spending budget,
    and dataset-consistent routing for every-M5 Scientist v2 discoveries.
    """

    def __init__(self, settings: Any, source: Any, repo: Any) -> None:
        super().__init__(settings, source, repo)
        self.final_exams_per_epoch = _env_int("EVE_FINAL_EXAMS_PER_EPOCH", 8, 1, 50)
        self.final_exam_budget_status: dict[str, Any] = {
            "epoch": None,
            "used": 0,
            "limit": self.final_exams_per_epoch,
            "remaining": self.final_exams_per_epoch,
        }
        self._fabric_rows_cache: list[dict[str, Any]] = []
        self._fabric_cache_at = None
        self.fabric_validation_rows = 0

    async def rows(self, force: bool = False) -> list[dict[str, Any]]:
        rows = await super().rows(force=force)
        research.enrich_market_observations(rows)
        return rows

    async def _authorised_fabric_rows(self, force: bool = False) -> list[dict[str, Any]]:
        state = await dataset_state(self.repo, SCIENTIST_VERSION)
        if not (
            str(state.get("active_dataset") or "") == FABRIC_DATASET
            and str(state.get("status") or "") == "active"
        ):
            raise RuntimeError("Every-M5 scientist validation requested before the verified dataset cutover is active.")

        # Re-check hard integrity whenever possible. A transient audit read outage
        # may use an already-loaded verified cache, but an actual hard-gate failure
        # is never ignored.
        try:
            audit = await fabric_audit(self.repo)
            if not hard_integrity_passes(audit):
                raise RuntimeError("Every-M5 fabric hard integrity gate is not currently satisfied.")
        except RuntimeError:
            raise
        except Exception:
            if not self._fabric_rows_cache:
                raise

        fresh_until = (self._fabric_cache_at or base.utc_now() - timedelta(days=1)) + timedelta(
            minutes=self.settings.row_cache_minutes
        )
        if force or not self._fabric_rows_cache or base.utc_now() >= fresh_until:
            self._fabric_rows_cache = await load_fabric_rows(
                self.repo,
                self.settings.source_symbol,
                complete_only=True,
            )
            research.enrich_market_observations(self._fabric_rows_cache)
            self._fabric_cache_at = base.utc_now()
        self.fabric_validation_rows = len(self._fabric_rows_cache)
        return self._fabric_rows_cache

    async def _rows_for_item(self, item: dict[str, Any], legacy_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
        rules = dict(item.get("rules") or {})
        if rules_use_fabric(rules):
            return await self._authorised_fabric_rows()
        return legacy_rows

    def runtime_status(self) -> dict[str, Any]:
        status = super().runtime_status()
        status.update(
            {
                "research_integrity_version": research.RESEARCH_INTEGRITY_VERSION,
                "observation_version": research.OBSERVATION_VERSION,
                "selection_execution_model": "signal close -> entry at next completed timeframe open; conservative max-hold lock",
                "monte_carlo_model": "moving_block_bootstrap",
                "final_exam_budget": dict(self.final_exam_budget_status),
                "fabric_validation_rows_cached": self.fabric_validation_rows,
                "dataset_routing": "rules.market.research_dataset selects legacy_15m or every_m5_fabric; cross-dataset validation is forbidden",
            }
        )
        return status

    def _holdout_epoch(self, rows: list[dict[str, Any]]) -> str:
        timestamps = [research.as_utc(row.get("candle_time")) for row in rows]
        timestamps = [value for value in timestamps if value is not None]
        if not timestamps:
            return "unknown"
        latest = max(timestamps)
        return f"{latest.year:04d}-{latest.month:02d}"

    async def _final_exam_available(self, rows: list[dict[str, Any]]) -> tuple[bool, str, int]:
        epoch = self._holdout_epoch(rows)
        existing = await self.repo.client.get(
            "final_exam_registry",
            params={"select": "id", "holdout_epoch": f"eq.{epoch}", "limit": "1000"},
        )
        used = len(existing)
        remaining = max(0, self.final_exams_per_epoch - used)
        self.final_exam_budget_status = {
            "epoch": epoch,
            "used": used,
            "limit": self.final_exams_per_epoch,
            "remaining": remaining,
        }
        return used < self.final_exams_per_epoch, epoch, used

    async def _open_final_exam(self, mutation: dict[str, Any], selection: dict[str, Any], epoch: str) -> str | None:
        rules = dict(mutation.get("rules") or {})
        rule_hash = hashlib.sha256(base.canonical(rules).encode()).hexdigest()
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
                    "research_integrity_version": research.RESEARCH_INTEGRITY_VERSION,
                },
            },
            return_rows=True,
        )
        return str(rows[0].get("id")) if rows else None

    async def _finish_final_exam(self, registry_id: str | None, result: dict[str, Any], frozen: bool) -> None:
        if not registry_id:
            return
        await self.repo.client.patch(
            "final_exam_registry",
            {
                "status": "finished",
                "result_status": result.get("result_status"),
                "m1_status": (result.get("m1_replay") or {}).get("status"),
                "frozen": frozen,
                "finished_at": base.utc_now().isoformat(),
            },
            filters={"id": f"eq.{registry_id}"},
        )

    async def maybe_freeze(self, source_kind: str, source: dict[str, Any], result: dict[str, Any]) -> bool:
        frozen = await super().maybe_freeze(source_kind, source, result)
        if not frozen:
            return False
        rules = dict(source.get("rules") or {})
        if not research.has_structure_conditions(rules):
            return True

        # Python/live recognition is valid because it uses the same causal
        # observation engine. MT5 export remains blocked until the MQL feature
        # implementation passes a golden-master parity harness.
        rule_hash = hashlib.sha256(base.canonical(rules).encode()).hexdigest()
        rows = await self.repo.client.get(
            "frozen_strategies",
            params={"select": "id", "rule_hash": f"eq.{rule_hash}", "limit": "1"},
        )
        if rows:
            await self.repo.client.patch(
                "frozen_strategies",
                {
                    "package_status": "failed",
                    "compile_status": "blocked_structure_parity",
                    "profile_reason": (
                        "Validated for Python live recognition. MT5 export is intentionally blocked until "
                        "market-structure feature parity is proven in MetaTrader."
                    ),
                },
                filters={"id": f"eq.{rows[0].get('id')}"},
            )
        await self.repo.event(
            "warning",
            "mt5_parity_guard",
            f"{source.get('name')} is validated for live recognition, but MT5 export is blocked pending structure-feature parity.",
            {"rule_hash": rule_hash, "observation_version": research.OBSERVATION_VERSION},
        )
        return True

    async def process_candidate(self, candidate: dict[str, Any], rows: list[dict[str, Any]]) -> None:
        try:
            rows = await self._rows_for_item(candidate, rows)
            result = research.evaluate_strategy(
                candidate,
                rows,
                min_validation_trades=self.settings.minimum_validation_trades,
                min_locked_trades=self.settings.minimum_locked_trades,
                stage="selection",
            )
            await self.repo.finish_candidate(str(candidate["id"]), result)
            completed = {**candidate, **result}
            if result["result_status"] == "promising":
                await self.repo.ensure_lineage_for_candidate(completed)
            validation = dict(result.get("metrics", {}).get("validation") or {})
            research_dataset = str((candidate.get("rules") or {}).get("market", {}).get("research_dataset") or "legacy_15m")
            await self.repo.event(
                "success" if result["result_status"] == "promising" else "info",
                "candidate_test",
                (
                    f"{candidate.get('name')} → {result['result_status']} in selection on {research_dataset}. "
                    f"Validation PF {research.number(validation.get('profit_factor')):.2f}, expectancy "
                    f"{research.number(validation.get('expectancy_r')):+.3f}R, {int(research.number(validation.get('trades')))} trades. "
                    "Confirmation and final holdout were not opened."
                ),
                {
                    "fitness": result.get("fitness_score"),
                    "decision": result.get("evidence", {}).get("decision"),
                    "candidate_key": candidate.get("candidate_key"),
                    "dataset_version": result.get("dataset_version"),
                    "research_dataset": research_dataset,
                },
            )
            self.last_action = f"Candidate {result['result_status']}: {candidate.get('name')}"
        except Exception as exc:
            await self.repo.fail_candidate(str(candidate["id"]), str(exc))
            raise

    async def process_mutation(self, mutation: dict[str, Any], rows: list[dict[str, Any]]) -> None:
        try:
            rows = await self._rows_for_item(mutation, rows)
            child_result = research.evaluate_strategy(
                mutation,
                rows,
                min_validation_trades=self.settings.minimum_validation_trades,
                min_locked_trades=self.settings.minimum_locked_trades,
                stage="selection",
            )
            selection = research.compare_child_to_parent(
                child_result,
                dict(mutation.get("parent_metrics") or {}),
                research.number(mutation.get("parent_fitness")),
            )
            await self.repo.finish_mutation(str(mutation["id"]), selection)
            await self.repo.update_lineage_from_mutation(str(mutation["lineage_id"]), mutation, selection)
            await self.repo.record_mutation_memory(
                str(mutation.get("family") or "unknown"),
                str(mutation.get("mutation_gene") or "unknown"),
                bool(selection.get("promoted")),
                research.number(selection.get("fitness_delta")),
            )

            finalist_candidate = (
                bool(selection.get("promoted"))
                and int(research.number(mutation.get("generation"))) >= self.settings.minimum_generations_before_final
                and research.selection_ready_for_final(selection)
            )
            finalist = False
            exam_epoch: str | None = None
            exam_registry_id: str | None = None
            if finalist_candidate:
                available, exam_epoch, used = await self._final_exam_available(rows)
                if available:
                    finalist = True
                    exam_registry_id = await self._open_final_exam(mutation, selection, exam_epoch)
                else:
                    await self.repo.event(
                        "warning",
                        "final_exam_budget",
                        (
                            f"{mutation.get('name')} reached finalist standard, but EVE kept the final holdout sealed: "
                            f"the {exam_epoch} global exam budget ({used}/{self.final_exams_per_epoch}) is exhausted."
                        ),
                        {
                            "lineage_id": mutation.get("lineage_id"),
                            "holdout_epoch": exam_epoch,
                            "used": used,
                            "limit": self.final_exams_per_epoch,
                            "action": "continue_selection_research_until_fresh_epoch",
                        },
                    )

            frozen = False
            final_result: dict[str, Any] | None = None
            if finalist:
                final_result = research.evaluate_strategy(
                    mutation,
                    rows,
                    min_validation_trades=self.settings.minimum_validation_trades,
                    min_locked_trades=self.settings.minimum_locked_trades,
                    stage="final",
                )
                if self.settings.m1_replay_enabled:
                    final_result["m1_replay"] = await validate_with_m1(self.source, mutation, rows)
                else:
                    final_result["m1_replay"] = {
                        "status": "failed",
                        "passed": False,
                        "failed_gates": ["m1_replay_disabled"],
                        "message": "M1 replay is mandatory for promotion and is disabled.",
                    }
                final_result.setdefault("evidence", {})["m1_replay"] = final_result["m1_replay"]
                final_result.setdefault("evidence", {})["global_final_exam"] = {
                    "holdout_epoch": exam_epoch,
                    "registry_id": exam_registry_id,
                    "budget_limit": self.final_exams_per_epoch,
                }
                frozen = await self.maybe_freeze("mutation", mutation, final_result)
                await self.repo.finalize_lineage(str(mutation["lineage_id"]), final_result, frozen=frozen)
                await self._finish_final_exam(exam_registry_id, final_result, frozen)
                await self.repo.event(
                    "success" if frozen else "warning",
                    "final_research",
                    (
                        f"Final research opened under global exam budget for {mutation.get('name')}. "
                        f"Result: {final_result.get('result_status')}; M1 replay: "
                        f"{final_result.get('m1_replay', {}).get('status')}."
                    ),
                    {
                        "lineage_id": mutation.get("lineage_id"),
                        "dataset_version": final_result.get("dataset_version"),
                        "holdout_epoch": exam_epoch,
                        "final_exam_registry_id": exam_registry_id,
                        "final_failed_gates": final_result.get("evidence", {}).get("decision", {}).get("failed_gates"),
                        "m1_failed_gates": final_result.get("m1_replay", {}).get("failed_gates"),
                        "frozen": frozen,
                    },
                )

            change = base.mutation_change_text(mutation)
            await self.repo.event(
                "success" if selection.get("promoted") else "info",
                "mutation_test",
                (
                    f"{'PROMOTED' if selection.get('promoted') else 'REJECTED'} mutation — {change}. "
                    f"Selection fitness {research.number(selection.get('fitness_delta')):+.2f}; validation expectancy "
                    f"{research.number(selection.get('validation_expectancy_delta')):+.3f}R. "
                    + (
                        "Final research opened under the global budget."
                        if finalist
                        else "Confirmation and holdout stayed sealed."
                    )
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
                    "holdout_used_for_selection": False,
                    "finalist_candidate": finalist_candidate,
                    "finalist": finalist,
                    "holdout_epoch": exam_epoch,
                    "frozen": frozen,
                    "research_dataset": str((mutation.get("rules") or {}).get("market", {}).get("research_dataset") or "legacy_15m"),
                },
            )
            if final_result:
                self.last_action = f"Finalist {'frozen' if frozen else 'retired'}: {mutation.get('name')}"
            elif finalist_candidate and not finalist:
                self.last_action = f"Finalist held behind global exam budget: {mutation.get('name')}"
            else:
                self.last_action = f"Mutation {'promoted' if selection.get('promoted') else 'rejected'}: {mutation.get('name')}"
        except Exception as exc:
            await self.repo.fail_mutation(str(mutation["id"]), str(exc))
            raise
