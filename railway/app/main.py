from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager
from typing import Any

from fastapi import Depends, FastAPI, Header, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response

from app.settings import Settings, get_settings
from app.services.fabric_builder import FabricBuilder
from app.services.intelligence_v2 import IntelligenceDirector
from app.services.mt5_generator import decode_package
from app.services.orchestrator_v3 import DiscoveryOrchestrator
from app.services.passport import passport_is_complete
from app.services.repository import DiscoveryRepository, SourceRepository

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

settings = get_settings()
source_repo = SourceRepository(settings)
discovery_repo = DiscoveryRepository(settings)
orchestrator = DiscoveryOrchestrator(settings, source_repo, discovery_repo)
intelligence = IntelligenceDirector(settings, discovery_repo, orchestrator.rows)
fabric = FabricBuilder(settings, source_repo, discovery_repo)
worker_task: asyncio.Task[Any] | None = None
intelligence_task: asyncio.Task[Any] | None = None
fabric_task: asyncio.Task[Any] | None = None


@asynccontextmanager
async def lifespan(_: FastAPI):
    global worker_task, intelligence_task, fabric_task
    if settings.autonomous_enabled:
        worker_task = asyncio.create_task(orchestrator.run_forever(), name="eve-discovery-worker")
        intelligence_task = asyncio.create_task(intelligence.run_forever(), name="eve-autonomous-scientist")
    if settings.fabric_enabled:
        fabric_task = asyncio.create_task(fabric.run_forever(), name="eve-m5-observation-fabric")
    try:
        yield
    finally:
        await fabric.stop()
        await intelligence.stop()
        await orchestrator.stop()
        for task in (fabric_task, intelligence_task, worker_task):
            if task:
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass


app = FastAPI(title=settings.app_name, version="2.4.1", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=False,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["*"],
)


def require_admin(
    authorization: str | None = Header(default=None),
    x_admin_token: str | None = Header(default=None),
) -> None:
    supplied = x_admin_token or (authorization.removeprefix("Bearer ").strip() if authorization else "")
    if supplied != settings.admin_token:
        raise HTTPException(status_code=401, detail="Invalid admin token")


def require_package_access(
    authorization: str | None = Header(default=None),
    x_admin_token: str | None = Header(default=None),
) -> None:
    if not settings.package_downloads_require_admin:
        return
    require_admin(authorization=authorization, x_admin_token=x_admin_token)


def package_download_ready(row: dict[str, Any]) -> tuple[bool, str]:
    profile_status = str(row.get("profile_status") or "pending")
    eligible = bool(row.get("download_eligible"))
    passport = dict(row.get("trading_passport") or {})
    if profile_status != "complete":
        reason = str(row.get("profile_reason") or "EVE has not completed this package's Trading Passport yet.")
        return False, reason
    if not eligible:
        return False, "The package is not approved for download after profiling."
    if not passport_is_complete(passport):
        return False, "The package Trading Passport is incomplete, so download is locked."
    if str(row.get("status") or "ready") != "ready":
        return False, str(row.get("profile_reason") or "The package is not ready for download.")
    return True, "ready"


def require_research_access(
    authorization: str | None = Header(default=None),
    x_admin_token: str | None = Header(default=None),
) -> None:
    if not settings.research_api_requires_admin:
        return
    require_admin(authorization=authorization, x_admin_token=x_admin_token)


@app.get("/health")
async def health() -> dict[str, Any]:
    return {
        "ok": True,
        "app": settings.app_name,
        "environment": settings.environment,
        "runtime": orchestrator.runtime_status(),
        "intelligence": intelligence.runtime_status(),
        "fabric": {**fabric.runtime_status(), "state": await fabric.state()},
    }


@app.get("/api/dashboard", dependencies=[Depends(require_research_access)])
async def dashboard() -> dict[str, Any]:
    stored = await discovery_repo.dashboard()
    return {
        **stored,
        "runtime": orchestrator.runtime_status(),
        "intelligence": intelligence.runtime_status(),
        "fabric": {**fabric.runtime_status(), "state": await fabric.state()},
    }


@app.get("/api/intelligence", dependencies=[Depends(require_research_access)])
async def intelligence_dashboard() -> dict[str, Any]:
    return await intelligence.dashboard()


@app.get("/api/fabric", dependencies=[Depends(require_research_access)])
async def fabric_status(limit: int = Query(default=5, ge=1, le=50)) -> dict[str, Any]:
    latest = await discovery_repo.client.get(
        "m5_research_snapshots",
        params={
            "select": "candle_time,outcome_complete,fabric_version,mtf_context",
            "symbol": f"eq.{settings.source_symbol}",
            "order": "candle_time.desc",
            "limit": str(limit),
        },
    )
    return {"runtime": fabric.runtime_status(), "state": await fabric.state(), "latest": latest}


@app.get("/api/fabric/audit", dependencies=[Depends(require_research_access)])
async def fabric_audit() -> dict[str, Any]:
    result = await discovery_repo.client.rpc("get_fabric_audit", {})
    return dict(result or {}) if isinstance(result, dict) else {"result": result}


@app.get("/api/live-setups", dependencies=[Depends(require_research_access)])
async def live_setups(limit: int = Query(default=100, ge=1, le=500)) -> dict[str, Any]:
    return {"items": await intelligence.live_setups(limit), "runtime": intelligence.runtime_status()}


@app.get("/api/scientist/hypotheses", dependencies=[Depends(require_research_access)])
async def scientist_hypotheses(limit: int = Query(default=100, ge=1, le=500)) -> dict[str, Any]:
    return {"items": await intelligence.recent_hypotheses(limit), "runtime": intelligence.runtime_status()}


@app.get("/api/scientist/memory", dependencies=[Depends(require_research_access)])
async def scientist_memory(limit: int = Query(default=100, ge=1, le=500)) -> dict[str, Any]:
    return {"items": await intelligence.feature_memory(limit), "runtime": intelligence.runtime_status()}


@app.get("/api/final-exams", dependencies=[Depends(require_research_access)])
async def final_exams(limit: int = Query(default=100, ge=1, le=500)) -> dict[str, Any]:
    items = await discovery_repo.client.get(
        "final_exam_registry",
        params={"select": "*", "order": "opened_at.desc", "limit": str(limit)},
    )
    return {"items": items, "budget": orchestrator.runtime_status().get("final_exam_budget")}


@app.get("/api/data-health", dependencies=[Depends(require_research_access)])
async def data_health() -> dict[str, Any]:
    stored = await discovery_repo.data_health()
    return {
        **stored,
        "runtime": orchestrator.runtime_status(),
        "intelligence": intelligence.runtime_status(),
        "fabric": {**fabric.runtime_status(), "state": await fabric.state()},
        "snapshot_definition": (
            "The legacy scientist currently consumes 15-minute research anchors. "
            "The new isolated fabric builds every completed M5 state with causal M1/M15/M30/H1/H4/D1 context. "
            "The scientist will switch only after get_fabric_audit reports ready_for_scientist_cutover=true."
        ),
    }


@app.get("/api/candidates", dependencies=[Depends(require_research_access)])
async def candidates(limit: int = Query(default=100, ge=1, le=500)) -> dict[str, Any]:
    return {"items": await discovery_repo.list_candidates(limit)}


@app.get("/api/lineages", dependencies=[Depends(require_research_access)])
async def lineages(limit: int = Query(default=100, ge=1, le=500)) -> dict[str, Any]:
    return {"items": await discovery_repo.list_lineages(limit)}


@app.get("/api/mutations", dependencies=[Depends(require_research_access)])
async def mutations(limit: int = Query(default=100, ge=1, le=500)) -> dict[str, Any]:
    return {"items": await discovery_repo.list_mutations(limit)}


@app.get("/api/frozen", dependencies=[Depends(require_research_access)])
async def frozen(limit: int = Query(default=100, ge=1, le=500)) -> dict[str, Any]:
    return {"items": await discovery_repo.list_frozen(limit)}


@app.get("/api/packages", dependencies=[Depends(require_research_access)])
async def packages(limit: int = Query(default=100, ge=1, le=500)) -> dict[str, Any]:
    return {"items": await discovery_repo.list_packages(limit)}


@app.get("/api/packages/{package_id}/download")
async def download_package(package_id: str, _: None = Depends(require_package_access)) -> Response:
    row = await discovery_repo.package(package_id)
    if not row:
        raise HTTPException(status_code=404, detail="Package not found")
    ready, reason = package_download_ready(row)
    if not ready:
        raise HTTPException(status_code=409, detail=reason)
    payload = decode_package(row)
    return Response(
        content=payload,
        media_type="application/zip",
        headers={
            "Content-Disposition": f'attachment; filename="{row.get("file_name") or "EVE-DISCOVERY-MT5.zip"}"',
            "X-Checksum-SHA256": str(row.get("sha256") or ""),
        },
    )


@app.get("/api/packages/{package_id}/mq5")
async def download_mq5(package_id: str, _: None = Depends(require_package_access)) -> Response:
    row = await discovery_repo.package(package_id)
    if not row:
        raise HTTPException(status_code=404, detail="Package not found")
    ready, reason = package_download_ready(row)
    if not ready:
        raise HTTPException(status_code=409, detail=reason)
    return Response(
        content=str(row.get("mq5_source") or ""),
        media_type="text/plain; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{row.get("mq5_file_name") or "EVE_Discovery.mq5"}"'},
    )


@app.post("/api/admin/run-cycle", dependencies=[Depends(require_admin)])
async def run_cycle() -> dict[str, Any]:
    return await orchestrator.run_once()


@app.post("/api/admin/run-scientist", dependencies=[Depends(require_admin)])
async def run_scientist() -> dict[str, Any]:
    return await intelligence.run_science_once(await orchestrator.rows())


@app.post("/api/admin/run-live-watch", dependencies=[Depends(require_admin)])
async def run_live_watch() -> dict[str, Any]:
    return await intelligence.run_live_watch_once()


@app.post("/api/admin/run-fabric", dependencies=[Depends(require_admin)])
async def run_fabric() -> dict[str, Any]:
    return await fabric.build_once()


@app.post("/api/admin/wake", dependencies=[Depends(require_admin)])
async def wake() -> dict[str, Any]:
    await orchestrator.wake()
    return {"ok": True, "message": "Worker wake requested"}


@app.post("/api/admin/sync-source", dependencies=[Depends(require_admin)])
async def sync_source() -> dict[str, Any]:
    count = await orchestrator.sync_source()
    return {"ok": True, "imported": count}
