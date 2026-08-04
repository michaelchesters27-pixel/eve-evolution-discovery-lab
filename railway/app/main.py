from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager
from typing import Any

from fastapi import Depends, FastAPI, Header, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response

from app.settings import Settings, get_settings
from app.services.orchestrator import DiscoveryOrchestrator
from app.services.repository import DiscoveryRepository, SourceRepository
from app.services.mt5_generator import decode_package

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

settings = get_settings()
source_repo = SourceRepository(settings)
discovery_repo = DiscoveryRepository(settings)
orchestrator = DiscoveryOrchestrator(settings, source_repo, discovery_repo)
worker_task: asyncio.Task[Any] | None = None


@asynccontextmanager
async def lifespan(_: FastAPI):
    global worker_task
    if settings.autonomous_enabled:
        worker_task = asyncio.create_task(orchestrator.run_forever(), name="eve-discovery-worker")
    try:
        yield
    finally:
        await orchestrator.stop()
        if worker_task:
            worker_task.cancel()
            try:
                await worker_task
            except asyncio.CancelledError:
                pass


app = FastAPI(title=settings.app_name, version="2.0.0", lifespan=lifespan)
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
    }


@app.get("/api/dashboard", dependencies=[Depends(require_research_access)])
async def dashboard() -> dict[str, Any]:
    stored = await discovery_repo.dashboard()
    return {**stored, "runtime": orchestrator.runtime_status()}


@app.get("/api/data-health", dependencies=[Depends(require_research_access)])
async def data_health() -> dict[str, Any]:
    stored = await discovery_repo.data_health()
    return {
        **stored,
        "runtime": orchestrator.runtime_status(),
        "snapshot_definition": (
            "One completed research market state at the configured snapshot interval. "
            "It contains a completed source candle, derived features and precomputed forward outcomes; it is not one raw tick."
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
    return Response(
        content=str(row.get("mq5_source") or ""),
        media_type="text/plain; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{row.get("mq5_file_name") or "EVE_Discovery.mq5"}"'},
    )


@app.post("/api/admin/run-cycle", dependencies=[Depends(require_admin)])
async def run_cycle() -> dict[str, Any]:
    return await orchestrator.run_once()


@app.post("/api/admin/wake", dependencies=[Depends(require_admin)])
async def wake() -> dict[str, Any]:
    await orchestrator.wake()
    return {"ok": True, "message": "Worker wake requested"}


@app.post("/api/admin/sync-source", dependencies=[Depends(require_admin)])
async def sync_source() -> dict[str, Any]:
    count = await orchestrator.sync_source()
    return {"ok": True, "imported": count}
