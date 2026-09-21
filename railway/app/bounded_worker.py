from __future__ import annotations

import asyncio
import json
import logging
from typing import Any, Awaitable, Callable

from app.settings import get_settings
from app.services.fabric_builder import FabricBuilder
from app.services.evidence_director import EvidenceDirectedIntelligenceDirector as IntelligenceDirector
from app.services.live_trader import LiveTrader
from app.services.live_trader_historical_learning_v29 import LiveTraderHistoricalLearner
from app.services.live_trader_zone_retrace_live_policy_replay_v68 import ZoneRetraceLivePolicyReplayer
from app.services.live_trader_zone_retrace_current_policy_academy_v71 import CurrentPolicyZoneRetraceAcademy
from app.services.orchestrator_v3 import DiscoveryOrchestrator
from app.services.repository import DiscoveryRepository, SourceRepository
from app.services import mtf_reasoning as _mtf_reasoning  # noqa: F401

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def _summary(value: Any) -> Any:
    if isinstance(value, bool) or value is None:
        return value
    if isinstance(value, (str, int, float)):
        return value
    if isinstance(value, dict):
        keep = (
            "ok", "status", "actions", "rows", "imported", "written", "scanned",
            "signals", "hypotheses_queued", "dataset_rows", "caught_up",
            "episodes_recorded", "processed_episodes", "opportunities_found",
        )
        return {key: value.get(key) for key in keep if key in value}
    return str(type(value).__name__)


async def _stage(
    name: str,
    operation: Callable[[], Awaitable[Any]],
    repo: DiscoveryRepository,
) -> dict[str, Any]:
    try:
        result = await operation()
        logger.info("Bounded EVE stage %s complete: %s", name, _summary(result))
        return {"ok": True, "result": _summary(result)}
    except Exception as exc:
        logger.exception("Bounded EVE stage %s failed", name)
        try:
            await repo.event(
                "error",
                "bounded_worker",
                f"Bounded research stage {name} failed safely.",
                {"stage": name, "error": str(exc)[:2000]},
            )
        except Exception:
            logger.exception("Could not persist bounded-worker failure event")
        return {"ok": False, "error": str(exc)[:2000]}


async def run_once() -> dict[str, Any]:
    settings = get_settings()
    source = SourceRepository(settings)
    repo = DiscoveryRepository(settings)

    orchestrator = DiscoveryOrchestrator(settings, source, repo)
    intelligence = IntelligenceDirector(settings, repo, orchestrator.rows)
    fabric = FabricBuilder(settings, source, repo)
    live = LiveTrader(settings, repo)
    historical = LiveTraderHistoricalLearner(settings, source, repo)
    replay = ZoneRetraceLivePolicyReplayer(live)
    current_policy = CurrentPolicyZoneRetraceAcademy(live)

    results: dict[str, Any] = {}

    # Keep each expensive activity bounded to exactly one unit of work. The
    # process exits after this sequence, releasing every historical row/cache.
    results["fabric"] = await _stage("fabric", fabric.build_once, repo)
    results["discovery"] = await _stage("discovery", orchestrator.run_once, repo)

    async def scientist_cycle() -> Any:
        rows = await orchestrator.rows()
        return await intelligence.run_science_once(rows)

    results["scientist"] = await _stage("scientist", scientist_cycle, repo)
    results["historical_academy"] = await _stage("historical_academy", historical.learn_cycle, repo)
    results["zone_replay"] = await _stage("zone_replay", replay.run_batch, repo)
    results["current_policy"] = await _stage("current_policy", current_policy.run_cycle, repo)

    succeeded = sum(1 for item in results.values() if item.get("ok"))
    failed = len(results) - succeeded
    try:
        await repo.event(
            "success" if failed == 0 else "warning",
            "bounded_worker",
            f"Bounded autonomous research cycle finished: {succeeded} stages succeeded, {failed} failed.",
            {"stages": results},
        )
    except Exception:
        logger.exception("Could not persist bounded-worker completion event")

    return {"ok": failed == 0, "succeeded": succeeded, "failed": failed, "stages": results}


if __name__ == "__main__":
    result = asyncio.run(run_once())
    print(json.dumps(result, sort_keys=True, default=str))
