from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

import httpx

from app.settings import Settings


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class RepositoryError(RuntimeError):
    pass


@dataclass
class ReadOnlyRestClient:
    """HTTP client whose public surface can only perform GET requests."""

    base_url: str
    key: str
    timeout: float = 90.0

    @property
    def headers(self) -> dict[str, str]:
        return {
            "apikey": self.key,
            "Authorization": f"Bearer {self.key}",
            "Content-Type": "application/json",
        }

    async def get(
        self,
        table: str,
        *,
        params: dict[str, str] | None = None,
        range_start: int | None = None,
        range_end: int | None = None,
    ) -> list[dict[str, Any]]:
        headers = dict(self.headers)
        if range_start is not None and range_end is not None:
            headers["Range"] = f"{range_start}-{range_end}"
            headers["Prefer"] = "count=exact"
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            response = await client.get(f"{self.base_url}/rest/v1/{table}", headers=headers, params=params or {})
        if response.status_code not in {200, 206}:
            raise RepositoryError(f"GET {table} failed {response.status_code}: {response.text[:500]}")
        payload = response.json()
        return payload if isinstance(payload, list) else []


@dataclass
class RestClient(ReadOnlyRestClient):
    """Read/write client used only for the separate Discovery Supabase."""

    async def insert(
        self,
        table: str,
        rows: list[dict[str, Any]] | dict[str, Any],
        *,
        return_rows: bool = True,
    ) -> list[dict[str, Any]]:
        headers = {**self.headers, "Prefer": "return=representation" if return_rows else "return=minimal"}
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            response = await client.post(
                f"{self.base_url}/rest/v1/{table}",
                headers=headers,
                content=json.dumps(rows, default=str),
            )
        if response.status_code not in {200, 201, 204}:
            raise RepositoryError(f"INSERT {table} failed {response.status_code}: {response.text[:500]}")
        if response.status_code == 204 or not response.text:
            return []
        payload = response.json()
        return payload if isinstance(payload, list) else []

    async def upsert(
        self,
        table: str,
        rows: list[dict[str, Any]] | dict[str, Any],
        *,
        on_conflict: str,
        return_rows: bool = False,
    ) -> list[dict[str, Any]]:
        headers = {
            **self.headers,
            "Prefer": f"resolution=merge-duplicates,return={'representation' if return_rows else 'minimal'}",
        }
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            response = await client.post(
                f"{self.base_url}/rest/v1/{table}",
                headers=headers,
                params={"on_conflict": on_conflict},
                content=json.dumps(rows, default=str),
            )
        if response.status_code not in {200, 201, 204}:
            raise RepositoryError(f"UPSERT {table} failed {response.status_code}: {response.text[:500]}")
        if response.status_code == 204 or not response.text:
            return []
        payload = response.json()
        return payload if isinstance(payload, list) else []

    async def patch(self, table: str, values: dict[str, Any], *, filters: dict[str, str]) -> list[dict[str, Any]]:
        headers = {**self.headers, "Prefer": "return=representation"}
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            response = await client.patch(
                f"{self.base_url}/rest/v1/{table}",
                headers=headers,
                params=filters,
                content=json.dumps(values, default=str),
            )
        if response.status_code not in {200, 204}:
            raise RepositoryError(f"PATCH {table} failed {response.status_code}: {response.text[:500]}")
        if response.status_code == 204 or not response.text:
            return []
        payload = response.json()
        return payload if isinstance(payload, list) else []

    async def rpc(self, function: str, payload: dict[str, Any] | None = None) -> Any:
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            response = await client.post(
                f"{self.base_url}/rest/v1/rpc/{function}",
                headers=self.headers,
                content=json.dumps(payload or {}, default=str),
            )
        if response.status_code not in {200, 201, 204}:
            raise RepositoryError(f"RPC {function} failed {response.status_code}: {response.text[:500]}")
        if not response.text:
            return None
        return response.json()


class SourceRepository:
    """Strict read adapter for EVE Algo Lab.

    This object exposes only read methods. It prefers SOURCE_SUPABASE_READ_ONLY_KEY
    when supplied; the legacy service-role variable remains accepted so existing
    deployments can migrate without an outage.
    """

    SNAPSHOT_COLUMNS = (
        "symbol,snapshot_interval,source_interval,candle_time,open,high,low,close,volume,weekday,month,quarter,"
        "hour_utc,week_of_month,session,direction,range_price,body_price,upper_wick,lower_wick,close_location,"
        "atr_14,average_range_12,volatility_12,compression_ratio,return_1_pct,return_3_pct,return_12_pct,"
        "return_48_pct,return_288_pct,context_m15_return_pct,context_h1_return_pct,context_h4_return_pct,"
        "context_d1_return_pct,trend_12_atr,trend_48_atr,streak,regime,alignment_score,outcomes,"
        "outcome_horizons,outcome_complete,feature_version"
    )

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.client = ReadOnlyRestClient(settings.source_supabase_url, settings.source_read_key)

    @property
    def credential_mode(self) -> str:
        return self.settings.source_credential_mode

    async def latest_snapshot_time(self) -> str | None:
        rows = await self.client.get(
            "market_learning_snapshots",
            params={
                "select": "candle_time",
                "symbol": f"eq.{self.settings.source_symbol}",
                "snapshot_interval": f"eq.{self.settings.source_snapshot_interval}",
                "source_interval": f"eq.{self.settings.source_candle_interval}",
                "order": "candle_time.desc",
                "limit": "1",
            },
        )
        return str(rows[0]["candle_time"]) if rows else None

    async def fetch_snapshots_after(self, after: str | None, *, limit: int) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        cursor = after
        page_size = min(self.settings.source_page_size, limit)
        while len(rows) < limit:
            current_limit = min(page_size, limit - len(rows))
            params = {
                "select": self.SNAPSHOT_COLUMNS,
                "symbol": f"eq.{self.settings.source_symbol}",
                "snapshot_interval": f"eq.{self.settings.source_snapshot_interval}",
                "source_interval": f"eq.{self.settings.source_candle_interval}",
                "outcome_complete": "eq.true",
                "order": "candle_time.asc",
                "limit": str(current_limit),
            }
            if cursor:
                params["candle_time"] = f"gt.{cursor}"
            batch = await self.client.get("market_learning_snapshots", params=params)
            if not batch:
                break
            rows.extend(batch)
            cursor = str(batch[-1].get("candle_time"))
            if len(batch) < current_limit:
                break
        return rows

    async def fetch_candles_page(
        self,
        symbol: str,
        interval: str,
        *,
        after: str | None = None,
        date_from: str | None = None,
        date_to: str | None = None,
        limit: int = 1000,
    ) -> list[dict[str, Any]]:
        safe_limit = max(1, min(1000, int(limit)))
        params = {
            "select": "candle_time,open,high,low,close,volume",
            "symbol": f"eq.{symbol}",
            "interval": f"eq.{interval}",
            "order": "candle_time.asc",
            "limit": str(safe_limit),
        }
        if after:
            params["candle_time"] = f"gt.{after}"
        elif date_from:
            params["candle_time"] = f"gte.{date_from}"
        if date_to:
            # PostgREST accepts repeated filters only in URL syntax, so combine
            # date bounds with an `and` expression when both are present.
            if after:
                params["and"] = f"(candle_time.lte.{date_to})"
            elif date_from:
                params.pop("candle_time", None)
                params["and"] = f"(candle_time.gte.{date_from},candle_time.lte.{date_to})"
            else:
                params["candle_time"] = f"lte.{date_to}"
        return await self.client.get("market_candles", params=params)


class DiscoveryRepository:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.client = RestClient(settings.discovery_supabase_url, settings.discovery_supabase_service_role_key)

    async def dashboard(self) -> dict[str, Any]:
        result = await self.client.rpc("get_discovery_dashboard", {})
        if isinstance(result, list):
            return dict(result[0]) if result else {}
        return dict(result or {})

    async def data_health(self) -> dict[str, Any]:
        result = await self.client.rpc("get_discovery_data_health", {})
        if isinstance(result, list):
            return dict(result[0]) if result else {}
        return dict(result or {})

    async def latest_local_snapshot_time(
        self,
        symbol: str | None = None,
        snapshot_interval: str | None = None,
        source_interval: str | None = None,
    ) -> str | None:
        params = {"select": "candle_time", "order": "candle_time.desc", "limit": "1"}
        if symbol:
            params["symbol"] = f"eq.{symbol}"
        if snapshot_interval:
            params["snapshot_interval"] = f"eq.{snapshot_interval}"
        if source_interval:
            params["source_interval"] = f"eq.{source_interval}"
        rows = await self.client.get("source_snapshots", params=params)
        return str(rows[0]["candle_time"]) if rows else None

    async def upsert_snapshots(self, rows: list[dict[str, Any]]) -> None:
        if rows:
            await self.client.upsert("source_snapshots", rows, on_conflict="symbol,source_interval,snapshot_interval,candle_time")

    async def all_snapshots(
        self,
        symbol: str | None = None,
        snapshot_interval: str | None = None,
        source_interval: str | None = None,
    ) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        start = 0
        page = 1000
        params = {"select": "*", "order": "candle_time.asc"}
        if symbol:
            params["symbol"] = f"eq.{symbol}"
        if snapshot_interval:
            params["snapshot_interval"] = f"eq.{snapshot_interval}"
        if source_interval:
            params["source_interval"] = f"eq.{source_interval}"
        while True:
            batch = await self.client.get(
                "source_snapshots",
                params=params,
                range_start=start,
                range_end=start + page - 1,
            )
            rows.extend(batch)
            if len(batch) < page:
                break
            start += page
        return rows

    async def count_by_status(self, table: str, status: str) -> int:
        rows = await self.client.get(table, params={"select": "id", "status": f"eq.{status}", "limit": "10000"})
        return len(rows)

    async def seed_candidates(self, rows: list[dict[str, Any]]) -> None:
        if rows:
            await self.client.upsert("strategy_candidates", rows, on_conflict="candidate_key")

    async def seed_mutations(self, rows: list[dict[str, Any]]) -> None:
        if rows:
            await self.client.upsert("mutation_candidates", rows, on_conflict="mutation_key")

    async def claim_candidate(self, worker_id: str) -> dict[str, Any] | None:
        result = await self.client.rpc("claim_next_discovery_candidate", {"p_worker_id": worker_id})
        return dict(result[0]) if isinstance(result, list) and result else None

    async def claim_mutation(self, worker_id: str) -> dict[str, Any] | None:
        result = await self.client.rpc("claim_next_mutation_candidate", {"p_worker_id": worker_id})
        return dict(result[0]) if isinstance(result, list) and result else None

    async def finish_candidate(self, candidate_id: str, result: dict[str, Any]) -> None:
        await self.client.patch(
            "strategy_candidates",
            {**result, "status": "complete", "finished_at": utc_now_iso(), "heartbeat_at": utc_now_iso(), "error": None},
            filters={"id": f"eq.{candidate_id}"},
        )

    async def fail_candidate(self, candidate_id: str, error: str) -> None:
        await self.client.patch(
            "strategy_candidates",
            {"status": "failed", "error": error[:2000], "finished_at": utc_now_iso(), "heartbeat_at": utc_now_iso()},
            filters={"id": f"eq.{candidate_id}"},
        )

    async def finish_mutation(self, mutation_id: str, result: dict[str, Any]) -> None:
        await self.client.patch(
            "mutation_candidates",
            {**result, "status": "complete", "finished_at": utc_now_iso(), "heartbeat_at": utc_now_iso(), "error": None},
            filters={"id": f"eq.{mutation_id}"},
        )

    async def fail_mutation(self, mutation_id: str, error: str) -> None:
        await self.client.patch(
            "mutation_candidates",
            {"status": "failed", "error": error[:2000], "finished_at": utc_now_iso(), "heartbeat_at": utc_now_iso()},
            filters={"id": f"eq.{mutation_id}"},
        )

    async def promising_candidates(self, limit: int = 50) -> list[dict[str, Any]]:
        return await self.client.get(
            "strategy_candidates",
            params={
                "select": "*",
                "result_status": "in.(promising,validated,elite)",
                "order": "fitness_score.desc",
                "limit": str(limit),
            },
        )

    async def active_lineages(self, limit: int = 50) -> list[dict[str, Any]]:
        return await self.client.get(
            "mutation_lineages",
            params={"select": "*", "status": "eq.active", "order": "champion_fitness.desc", "limit": str(limit)},
        )

    async def ensure_lineage_for_candidate(self, candidate: dict[str, Any]) -> None:
        row = {
            "lineage_key": f"lineage-{str(candidate.get('candidate_key')).replace('candidate-', '')}",
            "family": candidate.get("family"),
            "name": candidate.get("name"),
            "symbol": candidate.get("symbol") or (candidate.get("rules", {}).get("market") or {}).get("symbol") or "XAU/USD",
            "timeframe": candidate.get("timeframe") or (candidate.get("rules", {}).get("market") or {}).get("timeframe") or "M5",
            "status": "active",
            "generation": 0,
            "root_candidate_id": candidate.get("id"),
            "champion_kind": "seed",
            "champion_id": candidate.get("id"),
            "champion_rules": candidate.get("rules") or {},
            "champion_metrics": candidate.get("metrics") or {},
            "champion_fitness": candidate.get("fitness_score") or 0,
            "champion_result_status": candidate.get("result_status"),
            "dataset_version": candidate.get("dataset_version"),
            "last_result": "Seeded from a strategy that passed selection validation. Confirmation and final holdout remain sealed.",
        }
        await self.client.upsert("mutation_lineages", row, on_conflict="lineage_key")

    async def update_lineage_from_mutation(self, lineage_id: str, mutation: dict[str, Any], result: dict[str, Any]) -> None:
        if not result.get("promoted"):
            await self.client.patch(
                "mutation_lineages",
                {"last_result": result.get("selection_reason"), "updated_at": utc_now_iso()},
                filters={"id": f"eq.{lineage_id}"},
            )
            return
        await self.client.patch(
            "mutation_lineages",
            {
                "generation": mutation.get("generation"),
                "family": mutation.get("family") or mutation.get("rules", {}).get("family"),
                "symbol": mutation.get("symbol") or (mutation.get("rules", {}).get("market") or {}).get("symbol") or "XAU/USD",
                "timeframe": mutation.get("timeframe") or (mutation.get("rules", {}).get("market") or {}).get("timeframe") or "M5",
                "champion_kind": "mutation",
                "champion_id": mutation.get("id"),
                "champion_rules": mutation.get("rules") or {},
                "champion_metrics": result.get("metrics") or {},
                "champion_fitness": result.get("fitness_score") or 0,
                "champion_result_status": result.get("result_status"),
                "dataset_version": result.get("dataset_version"),
                "last_result": result.get("selection_reason"),
                "updated_at": utc_now_iso(),
            },
            filters={"id": f"eq.{lineage_id}"},
        )

    async def finalize_lineage(self, lineage_id: str, result: dict[str, Any], *, frozen: bool) -> None:
        await self.client.patch(
            "mutation_lineages",
            {
                "status": "retired",
                "final_result_status": result.get("result_status"),
                "final_metrics": result.get("metrics") or {},
                "final_evidence": result.get("evidence") or {},
                "holdout_opened_at": utc_now_iso(),
                "last_result": (
                    "Final confirmation, holdout and M1 replay passed; champion frozen."
                    if frozen
                    else "Final confirmation or M1 replay failed; lineage retired to prevent holdout reuse."
                ),
                "updated_at": utc_now_iso(),
            },
            filters={"id": f"eq.{lineage_id}"},
        )

    async def record_mutation_memory(self, family: str, gene: str, promoted: bool, delta: float) -> None:
        await self.client.rpc(
            "record_mutation_memory",
            {"p_family": family, "p_gene": gene, "p_promoted": promoted, "p_delta": delta},
        )

    async def mutation_memory(self) -> list[dict[str, Any]]:
        return await self.client.get("mutation_memory", params={"select": "*", "order": "score.desc"})

    async def freeze_strategy(self, row: dict[str, Any]) -> list[dict[str, Any]]:
        existing = await self.client.get(
            "frozen_strategies",
            params={"select": "*", "frozen_key": f"eq.{row.get('frozen_key')}", "limit": "1"},
        )
        if existing:
            return existing
        return await self.client.insert("frozen_strategies", row, return_rows=True)

    async def frozen_without_package(self, limit: int = 5) -> list[dict[str, Any]]:
        return await self.client.get(
            "frozen_strategies",
            params={"select": "*", "package_status": "eq.pending", "order": "created_at.asc", "limit": str(limit)},
        )

    async def store_package(self, row: dict[str, Any]) -> list[dict[str, Any]]:
        return await self.client.upsert("mt5_packages", row, on_conflict="package_key", return_rows=True)

    async def mark_frozen_packaged(self, frozen_id: str, package_id: str) -> None:
        await self.client.patch(
            "frozen_strategies",
            {"package_status": "ready", "mt5_package_id": package_id, "updated_at": utc_now_iso()},
            filters={"id": f"eq.{frozen_id}"},
        )

    async def package(self, package_id: str) -> dict[str, Any] | None:
        rows = await self.client.get("mt5_packages", params={"select": "*", "id": f"eq.{package_id}", "limit": "1"})
        return dict(rows[0]) if rows else None

    async def list_candidates(self, limit: int = 100) -> list[dict[str, Any]]:
        return await self.client.get("strategy_candidates", params={"select": "*", "order": "requested_at.desc", "limit": str(limit)})

    async def list_lineages(self, limit: int = 100) -> list[dict[str, Any]]:
        return await self.client.get("mutation_lineages", params={"select": "*", "order": "champion_fitness.desc", "limit": str(limit)})

    async def list_mutations(self, limit: int = 100) -> list[dict[str, Any]]:
        return await self.client.get("mutation_candidates", params={"select": "*", "order": "requested_at.desc", "limit": str(limit)})

    async def list_frozen(self, limit: int = 100) -> list[dict[str, Any]]:
        return await self.client.get("frozen_strategies", params={"select": "*", "order": "created_at.desc", "limit": str(limit)})

    async def list_packages(self, limit: int = 100) -> list[dict[str, Any]]:
        return await self.client.get(
            "mt5_packages",
            params={
                "select": "id,package_key,strategy_name,family,version,file_name,sha256,manifest,trading_passport,compile_status,size_bytes,created_at",
                "order": "created_at.desc",
                "limit": str(limit),
            },
        )

    async def event(self, level: str, component: str, message: str, details: dict[str, Any] | None = None) -> None:
        await self.client.insert(
            "system_events",
            {"level": level, "component": component, "message": message, "details": details or {}},
            return_rows=False,
        )
