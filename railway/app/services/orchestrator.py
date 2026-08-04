from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import socket
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

from app.settings import Settings
from app.services.backtest import (
    RESEARCH_INTEGRITY_VERSION,
    compare_child_to_parent,
    evaluate_strategy,
    number,
    selection_ready_for_final,
)
from app.services.composer import compose_batch, mutation_batch
from app.services.m1_replay import validate_with_m1
from app.services.mt5_generator import package_payload
from app.services.passport import PROFILE_VERSION, build_trading_passport, passport_completeness, passport_is_complete
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
    decision = dict((result.get("evidence") or {}).get("decision") or {})
    failed = [str(item).replace("_", " ") for item in decision.get("failed_gates") or []]
    return ", ".join(failed[:4]) if failed else "all gates passed"


class DiscoveryOrchestrator:
    """Autonomous worker for the isolated Discovery Lab.

    The selection stage may use development and validation only. Confirmation and
    final holdout are opened once, after a promoted lineage has reached the minimum
    generation. That lineage is then retired whether the finalist passes or fails,
    preventing repeated exposure to the holdout.
    """

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
        self.last_cycle_at: str | None = None
        self.last_successful_cycle_at: str | None = None
        self.cycle_count = 0

    async def stop(self) -> None:
        self._stop.set()
        self._wake.set()

    async def wake(self) -> None:
        self._wake.set()

    async def rows(self, force: bool = False) -> list[dict[str, Any]]:
        fresh_until = (self._cache_at or datetime.min.replace(tzinfo=timezone.utc)) + timedelta(
            minutes=self.settings.row_cache_minutes
        )
        if force or not self._rows_cache or utc_now() >= fresh_until:
            self._rows_cache = await self.repo.all_snapshots(
                self.settings.source_symbol,
                self.settings.source_snapshot_interval,
                self.settings.source_candle_interval,
            )
            self._cache_at = utc_now()
        return self._rows_cache

    async def sync_source(self) -> int:
        local = await self.repo.latest_local_snapshot_time(
            self.settings.source_symbol,
            self.settings.source_snapshot_interval,
            self.settings.source_candle_interval,
        )
        source_latest = await self.source.latest_snapshot_time()
        if source_latest is None or (local is not None and local >= source_latest):
            return 0
        fetched = await self.source.fetch_snapshots_after(local, limit=self.settings.bridge_batch_limit)
        if not fetched:
            return 0
        for start in range(0, len(fetched), 500):
            await self.repo.upsert_snapshots(fetched[start : start + 500])
        self._cache_at = None
        await self.repo.event(
            "success",
            "source_bridge",
            f"Research memory advanced through {str(fetched[-1].get('candle_time') or '')[:19]} (+{len(fetched):,} market states).",
            {
                "imported": len(fetched),
                "from": local,
                "to": fetched[-1].get("candle_time"),
                "source_latest": source_latest,
                "caught_up": len(fetched) < self.settings.bridge_batch_limit,
                "source_credential_mode": self.source.credential_mode,
            },
        )
        self.last_action = f"Synced {len(fetched):,} source market states"
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
            symbol=self.settings.source_symbol,
            timeframe=self.settings.research_timeframe,
            snapshot_interval=self.settings.source_snapshot_interval,
            source_interval=self.settings.source_candle_interval,
        )
        await self.repo.seed_candidates(batch)
        await self.repo.event(
            "info",
            "composer",
            f"Composed {len(batch)} {self.settings.source_symbol} {self.settings.research_timeframe} research candidates.",
            {
                "generation": generation,
                "timeframe": self.settings.research_timeframe,
                "snapshot_interval": self.settings.source_snapshot_interval,
                "source_candle_interval": self.settings.source_candle_interval,
                "confirmation_holdout": "sealed",
            },
        )
        self.last_action = f"Composed {len(batch)} new selection candidates"
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
            created.extend(
                mutation_batch(
                    lineage,
                    count=min(4, needed - len(created)),
                    generation=generation,
                    seed=(int(utc_now().timestamp()) // 60) + index + generation * 997,
                    memory=memory,
                )
            )
        await self.repo.seed_mutations(created)
        if created:
            await self.repo.event(
                "info",
                "evolution",
                f"Queued {len(created)} one-gene child mutations; confirmation and holdout remain sealed.",
                {"lineages_considered": len(lineages)},
            )
            self.last_action = f"Queued {len(created)} controlled mutations"
        return len(created)

    def ready_to_freeze(self, result: dict[str, Any]) -> bool:
        metrics = dict(result.get("metrics") or {})
        confirmation = dict(metrics.get("confirmation") or {})
        holdout = dict(metrics.get("holdout") or {})
        robustness = dict(result.get("robustness") or {})
        final_robustness = dict(robustness.get("final") or robustness)
        m1 = dict(result.get("m1_replay") or {})
        return (
            result.get("research_stage") == "final"
            and result.get("result_status") in {"validated", "elite"}
            and bool(m1.get("passed"))
            and number(confirmation.get("trades")) >= self.settings.minimum_locked_trades
            and number(holdout.get("trades")) >= max(20, self.settings.minimum_locked_trades // 3)
            and number(confirmation.get("profit_factor")) >= 1.15
            and number(confirmation.get("expectancy_r")) >= 0.04
            and number(holdout.get("profit_factor")) >= 1.00
            and number(holdout.get("expectancy_r")) >= -0.01
            and number(final_robustness.get("pass_rate")) >= 0.50
        )

    async def maybe_freeze(self, source_kind: str, source: dict[str, Any], result: dict[str, Any]) -> bool:
        if not self.ready_to_freeze(result):
            return False
        rules = dict(source.get("rules") or {})
        market = dict(rules.get("market") or {})
        rule_hash = hashlib.sha256(canonical(rules).encode()).hexdigest()
        code = f"EVE-DISC-{rule_hash[:12].upper()}"
        frozen: dict[str, Any] = {
            "frozen_key": f"frozen-{rule_hash[:28]}",
            "strategy_code": code,
            "name": source.get("name") or code,
            "family": source.get("family") or rules.get("family"),
            "symbol": source.get("symbol") or market.get("symbol") or self.settings.source_symbol,
            "timeframe": source.get("timeframe") or market.get("timeframe") or self.settings.research_timeframe,
            "research_stage": "final",
            "result_status": result.get("result_status"),
            "research_integrity_version": result.get("research_integrity_version") or RESEARCH_INTEGRITY_VERSION,
            "dataset_version": result.get("dataset_version"),
            "source_kind": source_kind,
            "source_id": source.get("id"),
            "rule_hash": rule_hash,
            "rules": rules,
            "metrics": result.get("metrics") or {},
            "walk_forward": result.get("walk_forward") or {},
            "robustness": result.get("robustness") or {},
            "monte_carlo": result.get("monte_carlo") or {},
            "execution_costs": result.get("execution_costs") or {},
            "m1_replay": result.get("m1_replay") or {},
            "evidence": result.get("evidence") or {},
            "stability_score": result.get("stability_score") or 0,
            "fitness_score": result.get("fitness_score") or 0,
            "compile_status": "required",
            "package_status": "pending",
            "status": "frozen",
        }
        frozen["trading_passport"] = build_trading_passport(frozen, profile_origin="automatic_finalist_profile")
        completeness = passport_completeness(frozen["trading_passport"])
        if not completeness.get("complete"):
            await self.repo.event(
                "warning",
                "strategy_profiler",
                f"{frozen['name']} passed research but its operator profile was incomplete, so no package was allowed.",
                {"missing_fields": completeness.get("missing_fields") or [], "strategy_code": code},
            )
            self.last_action = f"Profile incomplete for {frozen['name']} — package blocked"
            return False
        frozen.update({
            "profile_status": "complete",
            "profile_version": PROFILE_VERSION,
            "profile_reason": "Finalist profile completed before package generation.",
            "profiled_at": frozen["trading_passport"].get("profiled_at"),
            "profile_attempts": 1,
            "legacy_survivor": False,
        })
        await self.repo.freeze_strategy(frozen)
        await self.repo.event(
            "success",
            "promotion",
            f"Frozen {frozen['name']} after final holdout and M1 replay. MT5 source package is now permitted.",
            {
                "strategy_code": code,
                "source_kind": source_kind,
                "rule_hash": rule_hash,
                "dataset_version": result.get("dataset_version"),
                "timeframe": frozen["timeframe"],
            },
        )
        self.last_action = f"Frozen final survivor {code}"
        return True

    async def process_candidate(self, candidate: dict[str, Any], rows: list[dict[str, Any]]) -> None:
        try:
            result = evaluate_strategy(
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
            await self.repo.event(
                "success" if result["result_status"] == "promising" else "info",
                "candidate_test",
                (
                    f"{candidate.get('name')} → {result['result_status']} in selection. "
                    f"Validation PF {number(validation.get('profit_factor')):.2f}, expectancy "
                    f"{number(validation.get('expectancy_r')):+.3f}R, {int(number(validation.get('trades')))} trades. "
                    "Confirmation and final holdout were not opened."
                ),
                {
                    "fitness": result.get("fitness_score"),
                    "decision": result.get("evidence", {}).get("decision"),
                    "candidate_key": candidate.get("candidate_key"),
                    "dataset_version": result.get("dataset_version"),
                },
            )
            self.last_action = f"Candidate {result['result_status']}: {candidate.get('name')}"
        except Exception as exc:
            await self.repo.fail_candidate(str(candidate["id"]), str(exc))
            raise

    async def process_mutation(self, mutation: dict[str, Any], rows: list[dict[str, Any]]) -> None:
        try:
            child_result = evaluate_strategy(
                mutation,
                rows,
                min_validation_trades=self.settings.minimum_validation_trades,
                min_locked_trades=self.settings.minimum_locked_trades,
                stage="selection",
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

            finalist = (
                bool(selection.get("promoted"))
                and int(number(mutation.get("generation"))) >= self.settings.minimum_generations_before_final
                and selection_ready_for_final(selection)
            )
            frozen = False
            final_result: dict[str, Any] | None = None
            if finalist:
                final_result = evaluate_strategy(
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
                frozen = await self.maybe_freeze("mutation", mutation, final_result)
                await self.repo.finalize_lineage(str(mutation["lineage_id"]), final_result, frozen=frozen)
                await self.repo.event(
                    "success" if frozen else "warning",
                    "final_research",
                    (
                        f"Final research opened once for {mutation.get('name')}. "
                        f"Result: {final_result.get('result_status')}; M1 replay: "
                        f"{final_result.get('m1_replay', {}).get('status')}. "
                        f"Lineage retired {'after freezing the survivor' if frozen else 'without a survivor'}."
                    ),
                    {
                        "lineage_id": mutation.get("lineage_id"),
                        "dataset_version": final_result.get("dataset_version"),
                        "final_failed_gates": final_result.get("evidence", {}).get("decision", {}).get("failed_gates"),
                        "m1_failed_gates": final_result.get("m1_replay", {}).get("failed_gates"),
                        "frozen": frozen,
                    },
                )

            change = mutation_change_text(mutation)
            await self.repo.event(
                "success" if selection.get("promoted") else "info",
                "mutation_test",
                (
                    f"{'PROMOTED' if selection.get('promoted') else 'REJECTED'} mutation — {change}. "
                    f"Selection fitness {number(selection.get('fitness_delta')):+.2f}; validation expectancy "
                    f"{number(selection.get('validation_expectancy_delta')):+.3f}R. "
                    + ("Final research was opened once." if finalist else "Confirmation and holdout stayed sealed.")
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
                    "finalist": finalist,
                    "frozen": frozen,
                },
            )
            if final_result:
                self.last_action = f"Finalist {'frozen' if frozen else 'retired'}: {mutation.get('name')}"
            else:
                self.last_action = f"Mutation {'promoted' if selection.get('promoted') else 'rejected'}: {mutation.get('name')}"
        except Exception as exc:
            await self.repo.fail_mutation(str(mutation["id"]), str(exc))
            raise

    async def profile_legacy_package(self, rows: list[dict[str, Any]]) -> bool:
        """Bring one pre-v2.1 package through the current profiling gates.

        Legacy packages remain visible, but download is locked until EVE can recover
        the linked frozen rules, re-run current final research, complete M1 replay
        and produce a complete Trading Passport. A failed re-profile is recorded
        rather than silently filling the passport with guessed values.
        """
        package = await self.repo.package_needing_profile()
        if not package:
            return False

        package_id = str(package.get("id") or "")
        frozen_id = str(package.get("frozen_strategy_id") or "")
        await self.repo.mark_package_profiling(package_id, int(number(package.get("profile_attempts"))))
        self.last_action = f"Profiling legacy survivor {package.get('strategy_name') or package_id}"

        if not frozen_id:
            reason = "This legacy package has no linked frozen strategy record, so EVE cannot verify or describe its rules safely."
            await self.repo.mark_profile_failed(package_id, None, reason)
            await self.repo.event("warning", "strategy_profiler", reason, {"package_id": package_id})
            return True

        frozen = await self.repo.frozen_strategy(frozen_id)
        if not frozen or not frozen.get("rules"):
            reason = "The linked legacy survivor does not contain recoverable frozen rules, so its download remains blocked."
            await self.repo.mark_profile_failed(package_id, frozen_id, reason)
            await self.repo.event("warning", "strategy_profiler", reason, {"package_id": package_id, "frozen_id": frozen_id})
            return True

        try:
            result = evaluate_strategy(
                frozen,
                rows,
                min_validation_trades=self.settings.minimum_validation_trades,
                min_locked_trades=self.settings.minimum_locked_trades,
                stage="final",
            )
            if self.settings.m1_replay_enabled:
                result["m1_replay"] = await validate_with_m1(self.source, frozen, rows)
            else:
                result["m1_replay"] = {
                    "status": "failed",
                    "passed": False,
                    "failed_gates": ["m1_replay_disabled"],
                    "message": "M1 replay is mandatory for package profiling and is disabled.",
                }
            result.setdefault("evidence", {})["m1_replay"] = result["m1_replay"]

            if not self.ready_to_freeze(result):
                failed = [str(value).replace("_", " ") for value in (result.get("evidence", {}).get("decision", {}).get("failed_gates") or [])]
                failed += [str(value).replace("_", " ") for value in (result.get("m1_replay", {}).get("failed_gates") or [])]
                reason = (
                    "Legacy survivor did not pass the current final research and M1 execution standards. "
                    + ("Failed checks: " + ", ".join(dict.fromkeys(failed)) if failed else "It no longer meets the package promotion rules.")
                )
                await self.repo.mark_profile_failed(package_id, frozen_id, reason)
                await self.repo.event(
                    "warning",
                    "strategy_profiler",
                    f"Legacy package blocked after current-standard review: {package.get('strategy_name') or package_id}.",
                    {"package_id": package_id, "failed_checks": list(dict.fromkeys(failed)), "dataset_version": result.get("dataset_version")},
                )
                self.last_action = f"Legacy survivor failed current standards: {package.get('strategy_name') or package_id}"
                return True

            rules = dict(frozen.get("rules") or {})
            market = dict(rules.get("market") or {})
            enriched = {
                **frozen,
                "symbol": frozen.get("symbol") or market.get("symbol") or self.settings.source_symbol,
                "timeframe": frozen.get("timeframe") or market.get("timeframe") or self.settings.research_timeframe,
                "research_stage": "final",
                "result_status": result.get("result_status"),
                "research_integrity_version": result.get("research_integrity_version") or RESEARCH_INTEGRITY_VERSION,
                "dataset_version": result.get("dataset_version"),
                "metrics": result.get("metrics") or {},
                "walk_forward": result.get("walk_forward") or {},
                "robustness": result.get("robustness") or {},
                "monte_carlo": result.get("monte_carlo") or {},
                "execution_costs": result.get("execution_costs") or {},
                "m1_replay": result.get("m1_replay") or {},
                "evidence": result.get("evidence") or {},
                "stability_score": result.get("stability_score") or 0,
                "fitness_score": result.get("fitness_score") or 0,
                "profile_attempts": int(number(package.get("profile_attempts"))) + 1,
                "legacy_survivor": True,
            }
            enriched["trading_passport"] = build_trading_passport(enriched, profile_origin="legacy_survivor_revalidated")
            if not passport_is_complete(enriched["trading_passport"]):
                missing = passport_completeness(enriched["trading_passport"]).get("missing_fields") or []
                reason = "Legacy survivor passed research, but its Trading Passport remained incomplete: " + ", ".join(missing)
                await self.repo.mark_profile_failed(package_id, frozen_id, reason)
                await self.repo.event("warning", "strategy_profiler", reason, {"package_id": package_id, "missing_fields": missing})
                return True

            payload = package_payload(enriched)
            stored = await self.repo.store_package({**payload, "frozen_strategy_id": frozen_id})
            stored_id = str(stored[0].get("id") or package_id) if stored else package_id
            await self.repo.update_frozen_profile(
                frozen_id,
                {
                    "symbol": enriched["symbol"],
                    "timeframe": enriched["timeframe"],
                    "research_stage": "final",
                    "result_status": enriched["result_status"],
                    "research_integrity_version": enriched["research_integrity_version"],
                    "dataset_version": enriched["dataset_version"],
                    "metrics": enriched["metrics"],
                    "walk_forward": enriched["walk_forward"],
                    "robustness": enriched["robustness"],
                    "monte_carlo": enriched["monte_carlo"],
                    "execution_costs": enriched["execution_costs"],
                    "m1_replay": enriched["m1_replay"],
                    "evidence": enriched["evidence"],
                    "stability_score": enriched["stability_score"],
                    "fitness_score": enriched["fitness_score"],
                    "trading_passport": enriched["trading_passport"],
                    "profile_status": "complete",
                    "profile_version": PROFILE_VERSION,
                    "profile_reason": "Legacy survivor recovered and passed current final research, M1 replay and passport checks.",
                    "profiled_at": enriched["trading_passport"].get("profiled_at"),
                    "profile_attempts": enriched["profile_attempts"],
                    "legacy_survivor": True,
                    "package_status": "ready",
                    "mt5_package_id": stored_id,
                },
            )
            await self.repo.event(
                "success",
                "strategy_profiler",
                f"Legacy survivor recovered: {enriched.get('name')}. Its Trading Passport is complete and the rebuilt package is available.",
                {"package_id": stored_id, "frozen_id": frozen_id, "dataset_version": enriched.get("dataset_version"), "profile_version": PROFILE_VERSION},
            )
            self.last_action = f"Completed Trading Passport for {enriched.get('name')}"
            return True
        except Exception as exc:
            attempts = int(number(package.get("profile_attempts"))) + 1
            reason = f"Legacy profiling hit a temporary processing error: {str(exc)[:1500]}"
            if attempts >= self.settings.legacy_profile_max_attempts:
                final_reason = (
                    f"Legacy profiling could not complete after {attempts} attempts. "
                    "The package remains blocked until its frozen record or data access is repaired. "
                    f"Last error: {str(exc)[:1000]}"
                )
                await self.repo.mark_profile_failed(package_id, frozen_id, final_reason)
                await self.repo.event("error", "strategy_profiler", final_reason, {"package_id": package_id, "frozen_id": frozen_id, "attempts": attempts})
                self.last_action = f"Legacy profile blocked after repeated errors: {package.get('strategy_name') or package_id}"
            else:
                await self.repo.mark_profile_retry(package_id, reason, attempts)
                await self.repo.event("warning", "strategy_profiler", reason, {"package_id": package_id, "frozen_id": frozen_id, "attempts": attempts})
                self.last_action = f"Legacy profile will retry: {package.get('strategy_name') or package_id}"
            return True

    async def generate_pending_package(self) -> bool:
        if not self.settings.mt5_generation_enabled:
            return False
        pending = await self.repo.frozen_without_package(1)
        if not pending:
            return False
        frozen = pending[0]
        passport = dict(frozen.get("trading_passport") or {})
        if str(frozen.get("profile_status") or "") != "complete" or not passport_is_complete(passport):
            await self.repo.event(
                "warning",
                "mt5_generator",
                f"Package generation blocked for {frozen.get('name')}: Trading Passport is not complete.",
                {"frozen_id": frozen.get("id"), "missing_fields": passport_completeness(passport).get("missing_fields") or []},
            )
            return False
        payload = package_payload(frozen)
        rows = await self.repo.store_package({**payload, "frozen_strategy_id": frozen.get("id")})
        package_id = str(rows[0]["id"]) if rows else ""
        if package_id:
            await self.repo.mark_frozen_packaged(str(frozen["id"]), package_id)
        await self.repo.event(
            "success",
            "mt5_generator",
            f"Created {payload['file_name']} with Trading Passport and Algo Lab telemetry inputs.",
            {
                "sha256": payload["sha256"],
                "size_bytes": payload["size_bytes"],
                "compile_status": payload.get("compile_status"),
                "timeframe": payload.get("manifest", {}).get("timeframe"),
            },
        )
        self.last_action = f"Generated MT5 package {payload['file_name']}"
        return True

    async def run_once(self) -> dict[str, Any]:
        self.cycle_count += 1
        self.last_cycle_at = utc_now().isoformat()
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
                self.last_successful_cycle_at = utc_now().isoformat()
                return {"ok": True, "actions": actions, "rows": len(rows)}

            if await self.profile_legacy_package(rows):
                actions.append("profiled_legacy_package")
                self.last_successful_cycle_at = utc_now().isoformat()
                return {"ok": True, "actions": actions, "rows": len(rows)}

            if await self.generate_pending_package():
                actions.append("generated_package")
                self.last_successful_cycle_at = utc_now().isoformat()
                return {"ok": True, "actions": actions, "rows": len(rows)}

            candidate = await self.repo.claim_candidate(self.worker_id)
            if candidate:
                await self.process_candidate(candidate, rows)
                actions.append("tested_candidate")
                self.last_successful_cycle_at = utc_now().isoformat()
                return {"ok": True, "actions": actions, "rows": len(rows)}

            mutation = await self.repo.claim_mutation(self.worker_id)
            if mutation:
                await self.process_mutation(mutation, rows)
                actions.append("tested_mutation")
                self.last_successful_cycle_at = utc_now().isoformat()
                return {"ok": True, "actions": actions, "rows": len(rows)}

            seeded = await self.ensure_candidate_queue()
            if seeded:
                actions.append(f"seeded:{seeded}")
            mutations = await self.ensure_mutation_queue()
            if mutations:
                actions.append(f"mutations:{mutations}")
            if not actions:
                self.last_action = "All research queues healthy; waiting for next cycle"
                actions.append("idle")
            self.last_successful_cycle_at = utc_now().isoformat()
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
            "last_cycle_at": self.last_cycle_at,
            "last_successful_cycle_at": self.last_successful_cycle_at,
            "autonomous_enabled": self.settings.autonomous_enabled,
            "research_integrity_version": RESEARCH_INTEGRITY_VERSION,
            "source_symbol": self.settings.source_symbol,
            "research_timeframe": self.settings.research_timeframe,
            "snapshot_interval": self.settings.source_snapshot_interval,
            "source_candle_interval": self.settings.source_candle_interval,
            "m1_replay_enabled": self.settings.m1_replay_enabled,
            "source_credential_mode": self.source.credential_mode,
            "source_boundary_enforced": self.source.credential_mode == "read_only_key",
            "source_access_label": (
                "Dedicated read-only source access"
                if self.source.credential_mode == "read_only_key"
                else "Connected through the existing migration credential"
            ),
            "research_source_summary": (
                f"{self.settings.source_symbol} {self.settings.research_timeframe} research · "
                f"{self.settings.source_snapshot_interval} market states"
            ),
            "profile_version": PROFILE_VERSION,
            "production_write_surface": "none",
            "package_downloads_require_admin": self.settings.package_downloads_require_admin,
            "research_api_requires_admin": self.settings.research_api_requires_admin,
        }
