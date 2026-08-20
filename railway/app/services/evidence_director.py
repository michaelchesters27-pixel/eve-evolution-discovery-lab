from __future__ import annotations

import asyncio
from datetime import timedelta
from typing import Any

from app.services import intelligence as v1
from app.services import intelligence_v2 as scientist
from app.services.evidence_miner import EVIDENCE_MINER_VERSION, evidence_priors, mine_evidence
from app.services.multitimeframe import as_utc
from app.services.research_director import ResearchDirectedIntelligenceDirector

EVIDENCE_REFRESH_HOURS = 6


def _float_or(value: Any, default: float) -> float:
    """Convert numeric persistence values without treating a genuine zero as missing."""
    if value is None:
        return default
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


class EvidenceDirectedIntelligenceDirector(ResearchDirectedIntelligenceDirector):
    """Research Director that seeds hypothesis generation from measured anomalies."""

    def __init__(self, settings: Any, repo: Any, row_provider: Any) -> None:
        super().__init__(settings, repo, row_provider)
        self.evidence_scores: dict[str, float] = {}
        self.evidence_miner_summary: dict[str, Any] = {
            "version": EVIDENCE_MINER_VERSION,
            "signals": 0,
            "features_screened": 0,
            "single_tests": 0,
            "pair_tests": 0,
            "status": "waiting_for_first_scan",
            "data_access": "development_only",
            "confirmation_holdout_access": "forbidden",
        }
        self._evidence_last_updated = None

    async def _load_evidence(self) -> None:
        try:
            rows = await self.repo.client.get(
                "scientist_evidence_miner",
                params={
                    "select": "feature_keys,evidence_score,status,horizon_minutes,sample_count,q_value,year_stability,direction,effect_pct,standardized_effect,updated_at,signature,kind",
                    "scientist_version": f"eq.{scientist.INTELLIGENCE_VERSION}",
                    "research_dataset": f"eq.{self.active_dataset}",
                    "status": "eq.signal",
                    "order": "evidence_score.desc",
                    "limit": "500",
                },
            )
        except Exception:
            rows = []

        self.evidence_scores = evidence_priors(rows)
        latest = None
        for row in rows:
            parsed = as_utc(row.get("updated_at"))
            if parsed is not None and (latest is None or parsed > latest):
                latest = parsed
        self._evidence_last_updated = latest
        self.evidence_miner_summary = {
            "version": EVIDENCE_MINER_VERSION,
            "status": "active" if rows else "waiting_for_first_scan",
            "signals": len(rows),
            "priors": len(self.evidence_scores),
            "top_signals": rows[:12],
            "last_mined_at": latest.isoformat() if latest else None,
            "refresh_hours": EVIDENCE_REFRESH_HOURS,
            "data_access": "development_only",
            "validation_access": "forbidden",
            "confirmation_holdout_access": "forbidden",
        }

    async def _load_memory(self) -> dict[str, float]:
        memory = await super()._load_memory()
        await self._load_evidence()
        # Evidence Miner only influences hypothesis generation. Selection-stage
        # memory remains the stronger source and all sealed stages stay excluded.
        for feature_key, score in self.evidence_scores.items():
            memory[feature_key] = v1.clamp(float(memory.get(feature_key, 0.0)) + float(score) * 0.65, -4.0, 6.0)
        return memory

    async def _persist_evidence(self, result: dict[str, Any]) -> None:
        now = v1.utc_now().isoformat()
        rows: list[dict[str, Any]] = []
        for item in result.get("rows") or []:
            rows.append(
                {
                    "scientist_version": scientist.INTELLIGENCE_VERSION,
                    "research_dataset": self.active_dataset,
                    "signature": item.get("signature"),
                    "kind": item.get("kind"),
                    "feature_keys": item.get("feature_keys") or [],
                    "horizon_minutes": int(item.get("horizon_minutes") or 0),
                    "sample_count": int(item.get("sample_count") or 0),
                    "baseline_count": int(item.get("baseline_count") or 0),
                    "occurrence_rate": _float_or(item.get("occurrence_rate"), 0.0),
                    "mean_return_pct": _float_or(item.get("mean_return_pct"), 0.0),
                    "baseline_mean_return_pct": _float_or(item.get("baseline_mean_return_pct"), 0.0),
                    "effect_pct": _float_or(item.get("effect_pct"), 0.0),
                    "standardized_effect": _float_or(item.get("standardized_effect"), 0.0),
                    "p_value": _float_or(item.get("p_value"), 1.0),
                    "q_value": _float_or(item.get("q_value"), 1.0),
                    "year_stability": _float_or(item.get("year_stability"), 0.0),
                    "direction": str(item.get("direction") or "flat"),
                    "status": str(item.get("status") or "screened"),
                    "evidence_score": _float_or(item.get("evidence_score"), 0.0),
                    "metadata": {
                        "miner_version": EVIDENCE_MINER_VERSION,
                        "year_effects": item.get("year_effects") or {},
                        "fdr_gate": result.get("fdr_gate"),
                        "year_stability_gate": result.get("year_stability_gate"),
                        "development_rows": result.get("development_rows"),
                        "generation_data": "development_only",
                        "validation_access": "forbidden",
                        "confirmation_holdout_access": "forbidden",
                    },
                    "updated_at": now,
                }
            )
        for start in range(0, len(rows), 200):
            await self.repo.client.upsert(
                "scientist_evidence_miner",
                rows[start : start + 200],
                on_conflict="scientist_version,research_dataset,signature",
            )

    def _evidence_due(self) -> bool:
        if self._evidence_last_updated is None:
            return True
        return v1.utc_now() >= self._evidence_last_updated + timedelta(hours=EVIDENCE_REFRESH_HOURS)

    async def run_science_once(self, rows: list[dict[str, Any]] | None = None) -> dict[str, Any]:
        selected_rows = await self._select_science_rows(rows)
        segments = v1.chronological_segments(selected_rows)
        development = list(segments.get("development") or [])

        await self._load_evidence()
        mined: dict[str, Any] | None = None
        if self.active_dataset == scientist.FABRIC_DATASET and len(development) >= 1000 and self._evidence_due():
            mined = await asyncio.to_thread(mine_evidence, development)
            await self._persist_evidence(mined)
            await self._load_evidence()
            self.evidence_miner_summary.update(
                {
                    "status": "active",
                    "features_screened": mined.get("features_screened", 0),
                    "single_tests": mined.get("single_tests", 0),
                    "pair_tests": mined.get("pair_tests", 0),
                    "signals": mined.get("signals", 0),
                    "horizons": mined.get("horizons") or [],
                    "development_rows": mined.get("development_rows", 0),
                }
            )
            await self.repo.event(
                "success" if int(mined.get("signals") or 0) else "info",
                "evidence_miner",
                (
                    f"Evidence Miner screened {mined.get('features_screened', 0)} observable features across "
                    f"{mined.get('single_tests', 0)} single and {mined.get('pair_tests', 0)} pair tests; "
                    f"{mined.get('signals', 0)} anomalies survived FDR and cross-year stability gates."
                ),
                {
                    "miner_version": EVIDENCE_MINER_VERSION,
                    "research_dataset": self.active_dataset,
                    "development_rows": len(development),
                    "features_screened": mined.get("features_screened", 0),
                    "single_tests": mined.get("single_tests", 0),
                    "pair_tests": mined.get("pair_tests", 0),
                    "signals": mined.get("signals", 0),
                    "horizons": mined.get("horizons") or [],
                    "data_access": "development_only",
                    "validation_access": "forbidden",
                    "confirmation_holdout_access": "forbidden",
                },
            )

        result = await super().run_science_once(selected_rows)
        result["evidence_miner"] = self.evidence_miner_summary
        return result

    def runtime_status(self) -> dict[str, Any]:
        status = super().runtime_status()
        capabilities = list(status.get("capabilities") or [])
        for capability in (
            "development_only_evidence_mining",
            "false_discovery_rate_control",
            "cross_year_anomaly_stability",
            "anomaly_guided_hypothesis_generation",
        ):
            if capability not in capabilities:
                capabilities.append(capability)
        status["capabilities"] = capabilities
        status["evidence_miner_version"] = EVIDENCE_MINER_VERSION
        status["evidence_miner"] = self.evidence_miner_summary
        return status
