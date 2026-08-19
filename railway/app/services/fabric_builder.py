from __future__ import annotations

import asyncio
import logging
import math
from datetime import datetime, timedelta, timezone
from typing import Any

from app.services.m5_foundation import LOOKBACK_BARS, MAX_FUTURE_BARS, build_m5_snapshot
from app.services.multitimeframe import (
    FABRIC_VERSION,
    CompletedCandleIndex,
    aggregate_m30,
    as_utc,
    build_fabric_context,
)
from app.services.repository import DiscoveryRepository, SourceRepository
from app.settings import Settings

logger = logging.getLogger(__name__)

PARITY_FLOAT_FIELDS = (
    "open",
    "high",
    "low",
    "close",
    "atr_14",
    "average_range_12",
    "volatility_12",
    "compression_ratio",
    "return_1_pct",
    "return_3_pct",
    "return_12_pct",
    "return_48_pct",
    "return_288_pct",
    "trend_12_atr",
    "trend_48_atr",
)
PARITY_EXACT_FIELDS = ("direction", "streak", "session", "regime")
PARITY_SELECT = "candle_time," + ",".join((*PARITY_FLOAT_FIELDS, *PARITY_EXACT_FIELDS))


def _finite_number(value: Any) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return 0.0
    return result if math.isfinite(result) else 0.0


class FabricBuilder:
    """Resumable Discovery-only builder for the six-year every-M5 research fabric."""

    def __init__(self, settings: Settings, source: SourceRepository, repo: DiscoveryRepository) -> None:
        self.settings = settings
        self.source = source
        self.repo = repo
        self._stop = asyncio.Event()
        self.last_run_at: str | None = None
        self.last_error: str | None = None
        self.last_batch_rows = 0
        self.total_runtime_rows = 0

    async def stop(self) -> None:
        self._stop.set()

    def runtime_status(self) -> dict[str, Any]:
        return {
            "enabled": self.settings.fabric_enabled,
            "fabric_version": FABRIC_VERSION,
            "batch_days": self.settings.fabric_batch_days,
            "cycle_seconds": self.settings.fabric_cycle_seconds,
            "last_run_at": self.last_run_at,
            "last_error": self.last_error,
            "last_batch_rows": self.last_batch_rows,
            "runtime_rows_written": self.total_runtime_rows,
        }

    async def state(self) -> dict[str, Any]:
        rows = await self.repo.client.get(
            "fabric_build_state",
            params={"select": "*", "symbol": f"eq.{self.settings.source_symbol}", "limit": "1"},
        )
        return dict(rows[0]) if rows else {}

    async def _audit_state(self) -> dict[str, Any]:
        rows = await self.repo.client.get(
            "fabric_audit_state",
            params={"select": "*", "symbol": f"eq.{self.settings.source_symbol}", "limit": "1"},
        )
        return dict(rows[0]) if rows else {}

    async def _write_state(self, values: dict[str, Any]) -> None:
        payload = {
            "symbol": self.settings.source_symbol,
            "fabric_version": FABRIC_VERSION,
            "updated_at": datetime.now(timezone.utc).isoformat(),
            **values,
        }
        await self.repo.client.upsert("fabric_build_state", payload, on_conflict="symbol")

    async def _source_boundary(self, interval: str, *, newest: bool) -> datetime | None:
        rows = await self.source.client.get(
            "market_candles",
            params={
                "select": "candle_time",
                "symbol": f"eq.{self.settings.source_symbol}",
                "interval": f"eq.{interval}",
                "order": f"candle_time.{'desc' if newest else 'asc'}",
                "limit": "1",
            },
        )
        return as_utc(rows[0].get("candle_time")) if rows else None

    async def _fetch_range(self, interval: str, start: datetime, end: datetime) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        cursor: str | None = None
        while True:
            page = await self.source.fetch_candles_page(
                self.settings.source_symbol,
                interval,
                after=cursor,
                date_from=start.isoformat() if cursor is None else None,
                date_to=end.isoformat(),
                limit=1000,
            )
            if not page:
                break
            rows.extend(page)
            cursor = str(page[-1].get("candle_time"))
            if len(page) < 1000:
                break
        return rows

    async def _legacy_parity_rows(self, start: datetime, end: datetime) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        offset = 0
        page_size = 1000
        params = {
            "select": PARITY_SELECT,
            "symbol": f"eq.{self.settings.source_symbol}",
            "snapshot_interval": "eq.15min",
            "source_interval": "eq.5min",
            "and": f"(candle_time.gte.{start.isoformat()},candle_time.lt.{end.isoformat()})",
            "order": "candle_time.asc",
        }
        while True:
            page = await self.repo.client.get(
                "source_snapshots",
                params=params,
                range_start=offset,
                range_end=offset + page_size - 1,
            )
            rows.extend(page)
            if len(page) < page_size:
                break
            offset += page_size
        return rows

    @staticmethod
    def _snapshot_parity_matches(current: dict[str, Any], legacy: dict[str, Any]) -> bool:
        for field in PARITY_FLOAT_FIELDS:
            if abs(_finite_number(current.get(field)) - _finite_number(legacy.get(field))) > 1e-8:
                return False
        return all(current.get(field) == legacy.get(field) for field in PARITY_EXACT_FIELDS)

    async def _update_incremental_audit(self, snapshots: list[dict[str, Any]]) -> None:
        if not snapshots:
            return
        audit = await self._audit_state()
        audited_through = as_utc(audit.get("audited_through"))
        ordered = sorted(snapshots, key=lambda row: str(row.get("candle_time") or ""))
        fresh = [
            row for row in ordered
            if (stamp := as_utc(row.get("candle_time"))) is not None and (audited_through is None or stamp > audited_through)
        ]
        if not fresh:
            return

        first_stamp = as_utc(fresh[0].get("candle_time"))
        last_stamp = as_utc(fresh[-1].get("candle_time"))
        assert first_stamp is not None and last_stamp is not None
        legacy_rows = await self._legacy_parity_rows(first_stamp, last_stamp + timedelta(minutes=5))
        legacy_by_time = {str(row.get("candle_time")): row for row in legacy_rows}

        batch_counts = {
            "complete_rows": 0,
            "m1_rows": 0,
            "m15_rows": 0,
            "m30_rows": 0,
            "h1_rows": 0,
            "h4_rows": 0,
            "d1_rows": 0,
            "m15_violations": 0,
            "m30_violations": 0,
            "h1_violations": 0,
            "h4_violations": 0,
            "d1_violations": 0,
            "parity_rows_compared": 0,
            "parity_rows_matching": 0,
        }

        key_map = {"M15": "m15", "M30": "m30", "H1": "h1", "H4": "h4", "D1": "d1"}
        for row in fresh:
            if row.get("outcome_complete"):
                batch_counts["complete_rows"] += 1
            context = dict(row.get("mtf_context") or {})
            if bool((context.get("M1") or {}).get("available")):
                batch_counts["m1_rows"] += 1
            decision = as_utc(context.get("decision_time"))
            for label, prefix in key_map.items():
                item = context.get(label)
                if item is None:
                    continue
                batch_counts[f"{prefix}_rows"] += 1
                completed = as_utc((item or {}).get("completed_at"))
                if decision is not None and completed is not None and completed > decision:
                    batch_counts[f"{prefix}_violations"] += 1

            legacy = legacy_by_time.get(str(row.get("candle_time")))
            if legacy is not None:
                batch_counts["parity_rows_compared"] += 1
                if self._snapshot_parity_matches(row, legacy):
                    batch_counts["parity_rows_matching"] += 1

        payload: dict[str, Any] = {
            "symbol": self.settings.source_symbol,
            "fabric_version": FABRIC_VERSION,
            "audited_through": last_stamp.isoformat(),
            "first_time": audit.get("first_time") or first_stamp.isoformat(),
            "last_time": last_stamp.isoformat(),
            "rows_audited": int(audit.get("rows_audited") or 0) + len(fresh),
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }
        for field, amount in batch_counts.items():
            payload[field] = int(audit.get(field) or 0) + int(amount)
        await self.repo.client.upsert("fabric_audit_state", payload, on_conflict="symbol")

    @staticmethod
    def _m1_buckets(rows: list[dict[str, Any]]) -> dict[datetime, list[dict[str, Any]]]:
        buckets: dict[datetime, list[dict[str, Any]]] = {}
        for row in rows:
            stamp = as_utc(row.get("candle_time"))
            if stamp is None:
                continue
            bucket = stamp.replace(minute=(stamp.minute // 5) * 5, second=0, microsecond=0)
            buckets.setdefault(bucket, []).append(row)
        return buckets

    async def build_once(self) -> dict[str, Any]:
        latest = await self._source_boundary("5min", newest=True)
        earliest = await self._source_boundary("5min", newest=False)
        if latest is None or earliest is None:
            return {"ok": False, "reason": "no_source_m5"}

        state = await self.state()
        cursor = as_utc(state.get("cursor_time"))
        target_start = cursor + timedelta(minutes=5) if cursor else earliest
        if target_start > latest:
            await self._write_state(
                {
                    "status": "caught_up",
                    "cursor_time": cursor.isoformat() if cursor else latest.isoformat(),
                    "source_from": earliest.isoformat(),
                    "source_to": latest.isoformat(),
                    "last_batch_rows": 0,
                    "last_error": None,
                }
            )
            return {"ok": True, "status": "caught_up", "latest": latest.isoformat(), "rows": 0}

        target_end = min(target_start + timedelta(days=self.settings.fabric_batch_days), latest + timedelta(minutes=5))
        # Calendar padding covers weekends/market closures while guaranteeing at
        # least 288 prior M5 observations for ordinary trading weeks.
        load_start = max(earliest, target_start - timedelta(days=7))
        m5_end = min(latest + timedelta(minutes=5), target_end + timedelta(minutes=5 * MAX_FUTURE_BARS))
        context_start = max(earliest - timedelta(days=2), load_start - timedelta(days=2))

        await self._write_state(
            {
                "status": "building",
                "cursor_time": cursor.isoformat() if cursor else None,
                "source_from": earliest.isoformat(),
                "source_to": latest.isoformat(),
                "last_error": None,
                "started_at": state.get("started_at") or datetime.now(timezone.utc).isoformat(),
            }
        )

        m5_rows = await self._fetch_range("5min", load_start, m5_end)
        if not m5_rows:
            return {"ok": False, "reason": "empty_m5_batch", "from": target_start.isoformat(), "to": target_end.isoformat()}
        m1_rows = await self._fetch_range("1min", target_start, target_end)
        m15_rows = await self._fetch_range("15min", context_start, target_end)
        h1_rows = await self._fetch_range("1h", context_start, target_end)
        h4_rows = await self._fetch_range("4h", context_start - timedelta(days=4), target_end)
        d1_rows = await self._fetch_range("1day", context_start - timedelta(days=7), target_end)
        m30_rows = aggregate_m30(m5_rows)

        m15_index = CompletedCandleIndex(m15_rows, "15min")
        m30_index = CompletedCandleIndex(m30_rows, "30min")
        h1_index = CompletedCandleIndex(h1_rows, "1h")
        h4_index = CompletedCandleIndex(h4_rows, "4h")
        d1_index = CompletedCandleIndex(d1_rows, "1day")
        m1_by_m5 = self._m1_buckets(m1_rows)

        m5_rows = sorted(m5_rows, key=lambda row: str(row.get("candle_time") or ""))
        snapshots: list[dict[str, Any]] = []
        last_signal: datetime | None = None
        for index, current in enumerate(m5_rows):
            signal_time = as_utc(current.get("candle_time"))
            if signal_time is None or signal_time < target_start or signal_time >= target_end or signal_time > latest:
                continue
            previous = m5_rows[max(0, index - LOOKBACK_BARS) : index]
            if len(previous) < LOOKBACK_BARS:
                continue
            future = m5_rows[index + 1 : index + 1 + MAX_FUTURE_BARS]
            fabric = build_fabric_context(
                current,
                m1_rows=m1_by_m5.get(signal_time, []),
                m15_index=m15_index,
                m30_index=m30_index,
                h1_index=h1_index,
                h4_index=h4_index,
                d1_index=d1_index,
            )
            snapshots.append(build_m5_snapshot(self.settings.source_symbol, previous, current, future, fabric))
            last_signal = signal_time

        for start in range(0, len(snapshots), 250):
            await self.repo.client.upsert(
                "m5_research_snapshots",
                snapshots[start : start + 250],
                on_conflict="symbol,snapshot_interval,source_interval,candle_time",
            )

        # Audit the in-memory batch before advancing the durable build cursor.
        # audited_through makes this idempotent if a process dies between writes.
        await self._update_incremental_audit(snapshots)

        completed = sum(1 for row in snapshots if row.get("outcome_complete"))
        m1_available = sum(1 for row in snapshots if bool((row.get("mtf_context") or {}).get("M1", {}).get("available")))
        previous_written = int(state.get("rows_written") or 0)
        previous_complete = int(state.get("complete_rows") or 0)
        previous_m1 = int(state.get("m1_available_rows") or 0)
        cursor_out = last_signal or (target_end - timedelta(minutes=5))
        caught_up = cursor_out >= latest
        await self._write_state(
            {
                "status": "caught_up" if caught_up else "building",
                "cursor_time": cursor_out.isoformat(),
                "source_from": earliest.isoformat(),
                "source_to": latest.isoformat(),
                "rows_written": previous_written + len(snapshots),
                "complete_rows": previous_complete + completed,
                "m1_available_rows": previous_m1 + m1_available,
                "last_batch_rows": len(snapshots),
                "last_error": None,
            }
        )
        self.last_run_at = datetime.now(timezone.utc).isoformat()
        self.last_error = None
        self.last_batch_rows = len(snapshots)
        self.total_runtime_rows += len(snapshots)
        await self.repo.event(
            "success" if snapshots else "info",
            "mtf_fabric",
            (
                f"Every-M5 fabric built {len(snapshots):,} observations from "
                f"{target_start.isoformat()[:10]} through {cursor_out.isoformat()[:16]}."
            ),
            {
                "fabric_version": FABRIC_VERSION,
                "rows": len(snapshots),
                "complete_outcomes": completed,
                "m1_microstructure_available": m1_available,
                "source_latest": latest.isoformat(),
                "caught_up": caught_up,
                "incremental_audit": True,
            },
        )
        return {
            "ok": True,
            "status": "caught_up" if caught_up else "building",
            "rows": len(snapshots),
            "complete_rows": completed,
            "m1_available_rows": m1_available,
            "cursor": cursor_out.isoformat(),
            "source_latest": latest.isoformat(),
        }

    async def run_forever(self) -> None:
        if self.settings.fabric_startup_delay_seconds:
            try:
                await asyncio.wait_for(self._stop.wait(), timeout=self.settings.fabric_startup_delay_seconds)
                return
            except asyncio.TimeoutError:
                pass
        while not self._stop.is_set():
            try:
                result = await self.build_once()
                self.last_error = None
                delay = max(self.settings.fabric_cycle_seconds, 60) if result.get("status") == "caught_up" else self.settings.fabric_cycle_seconds
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                logger.exception("Every-M5 fabric builder failed")
                self.last_error = str(exc)
                self.last_run_at = datetime.now(timezone.utc).isoformat()
                try:
                    await self._write_state({"status": "error", "last_error": str(exc)[:4000]})
                    await self.repo.event("error", "mtf_fabric", "Every-M5 fabric builder failed.", {"error": str(exc)[:1000]})
                except Exception:
                    logger.exception("Could not persist fabric-builder failure")
                delay = max(60, self.settings.fabric_cycle_seconds)
            try:
                await asyncio.wait_for(self._stop.wait(), timeout=delay)
            except asyncio.TimeoutError:
                pass
