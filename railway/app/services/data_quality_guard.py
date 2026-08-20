from __future__ import annotations

import math
from datetime import datetime, timedelta, timezone
from typing import Any

from app.services import repository as repository_module

DATA_QUALITY_GUARD_VERSION = "eve-zero-atr-ingress-guard-v1"
ZERO_ATR_REASON = "Non-positive ATR is not a usable volatility state; quarantine rather than impute."


def usable_atr(value: Any) -> bool:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return False
    return math.isfinite(parsed) and parsed > 0.0


OriginalSourceRepository = repository_module.SourceRepository


class GuardedSourceRepository(OriginalSourceRepository):
    """Read-only source adapter that exposes only ATR-usable learning snapshots.

    Raw candle access remains untouched because the Every-M5 fabric computes its
    own ATR from candles. Legacy market-learning snapshots are filtered at the
    source query so zero-ATR market-closure rows never enter Discovery memory.
    """

    async def latest_snapshot_time(self) -> str | None:
        rows = await self.client.get(
            "market_learning_snapshots",
            params={
                "select": "candle_time",
                "symbol": f"eq.{self.settings.source_symbol}",
                "snapshot_interval": f"eq.{self.settings.source_snapshot_interval}",
                "source_interval": f"eq.{self.settings.source_candle_interval}",
                "outcome_complete": "eq.true",
                "atr_14": "gt.0",
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
                "atr_14": "gt.0",
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


repository_module.SourceRepository = GuardedSourceRepository

# Import the fabric builder only after installing the guarded source class, so its
# module-level SourceRepository reference also resolves to the guarded adapter.
from app.services import fabric_builder as fabric_builder_module  # noqa: E402

OriginalFabricBuilder = fabric_builder_module.FabricBuilder


class GuardedFabricBuilder(OriginalFabricBuilder):
    """Every-M5 builder that refuses to persist non-positive ATR observations."""

    async def _quarantine_invalid_snapshots(self, rows: list[dict[str, Any]]) -> None:
        if not rows:
            return
        payloads = []
        for row in rows:
            symbol = str(row.get("symbol") or self.settings.source_symbol)
            candle_time = str(row.get("candle_time") or "")
            payloads.append(
                {
                    "source_table": "m5_research_snapshots",
                    "record_key": f"{symbol}|{candle_time}",
                    "symbol": symbol,
                    "candle_time": candle_time or None,
                    "reason": ZERO_ATR_REASON,
                    "payload": row,
                    "quarantined_at": datetime.now(timezone.utc).isoformat(),
                }
            )
        await self.repo.client.upsert(
            "research_data_quarantine",
            payloads,
            on_conflict="source_table,record_key",
        )
        await self.repo.event(
            "warning",
            "data_integrity",
            f"Quarantined {len(rows)} Every-M5 observation(s) with non-positive ATR before persistence.",
            {
                "guard_version": DATA_QUALITY_GUARD_VERSION,
                "policy": "quarantine_not_impute",
                "rows": len(rows),
                "times": [str(row.get("candle_time") or "") for row in rows[:20]],
            },
        )

    def runtime_status(self) -> dict[str, Any]:
        status = super().runtime_status()
        status["data_quality_guard_version"] = DATA_QUALITY_GUARD_VERSION
        status["zero_atr_policy"] = "quarantine_not_impute"
        return status

    async def build_once(self) -> dict[str, Any]:
        fb = fabric_builder_module
        latest = await self._source_boundary("5min", newest=True)
        earliest = await self._source_boundary("5min", newest=False)
        if latest is None or earliest is None:
            return {"ok": False, "reason": "no_source_m5"}

        state = await self.state()
        cursor = fb.as_utc(state.get("cursor_time"))
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
        load_start = max(earliest, target_start - timedelta(days=7))
        m5_end = min(latest + timedelta(minutes=5), target_end + timedelta(minutes=5 * fb.MAX_FUTURE_BARS))
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
        m30_rows = fb.aggregate_m30(m5_rows)

        m15_index = fb.CompletedCandleIndex(m15_rows, "15min")
        m30_index = fb.CompletedCandleIndex(m30_rows, "30min")
        h1_index = fb.CompletedCandleIndex(h1_rows, "1h")
        h4_index = fb.CompletedCandleIndex(h4_rows, "4h")
        d1_index = fb.CompletedCandleIndex(d1_rows, "1day")
        m1_by_m5 = self._m1_buckets(m1_rows)

        m5_rows = sorted(m5_rows, key=lambda row: str(row.get("candle_time") or ""))
        snapshots: list[dict[str, Any]] = []
        quarantined: list[dict[str, Any]] = []
        last_signal: datetime | None = None
        for index, current in enumerate(m5_rows):
            signal_time = fb.as_utc(current.get("candle_time"))
            if signal_time is None or signal_time < target_start or signal_time >= target_end or signal_time > latest:
                continue
            previous = m5_rows[max(0, index - fb.LOOKBACK_BARS) : index]
            if len(previous) < fb.LOOKBACK_BARS:
                continue
            future = m5_rows[index + 1 : index + 1 + fb.MAX_FUTURE_BARS]
            fabric = fb.build_fabric_context(
                current,
                m1_rows=m1_by_m5.get(signal_time, []),
                m15_index=m15_index,
                m30_index=m30_index,
                h1_index=h1_index,
                h4_index=h4_index,
                d1_index=d1_index,
            )
            snapshot = fb.build_m5_snapshot(self.settings.source_symbol, previous, current, future, fabric)
            last_signal = signal_time
            if not usable_atr(snapshot.get("atr_14")):
                quarantined.append(snapshot)
                continue
            snapshots.append(snapshot)

        if quarantined:
            await self._quarantine_invalid_snapshots(quarantined)

        for start in range(0, len(snapshots), 250):
            await self.repo.client.upsert(
                "m5_research_snapshots",
                snapshots[start : start + 250],
                on_conflict="symbol,snapshot_interval,source_interval,candle_time",
            )

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
                "fabric_version": fb.FABRIC_VERSION,
                "rows": len(snapshots),
                "quarantined_non_positive_atr": len(quarantined),
                "data_quality_guard_version": DATA_QUALITY_GUARD_VERSION,
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
            "quarantined_non_positive_atr": len(quarantined),
            "complete_rows": completed,
            "m1_available_rows": m1_available,
            "cursor": cursor_out.isoformat(),
            "source_latest": latest.isoformat(),
        }


fabric_builder_module.FabricBuilder = GuardedFabricBuilder
