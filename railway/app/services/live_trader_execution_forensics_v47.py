from __future__ import annotations

import asyncio
from datetime import datetime, timedelta
from typing import Any

from app.services import live_trader as core
from app.services import live_trader_audit_hardening_v26 as hardening
from app.services import live_trader_execution_integrity_v39 as integrity
from app.services import live_trader_historical_runtime_v30 as runtime
from app.services import live_trader_trade_outcomes_v38 as outcomes
from app.services.live_trader_execution_forensics_evidence_v47 import build_forensics, forward_family_summary, historical_summary
from app.services.live_trader_execution_forensics_metrics_v47 import bar_time, ceil_minute, diagnose, entry_maturity_score, parse_time, path_metrics
from app.services.repository import SourceRepository

FORENSICS_VERSION = "eve-live-execution-forensics-v1"
POST_TRADE_REVIEW_VERSION = "eve-live-post-trade-review-v2"
POST_COMPLETION_MINUTES = 60
MAX_SOURCE_BARS = 6000
BACKFILL_READ_LIMIT = 100
SUMMARY_CACHE_SECONDS = 15

_current_context_snapshot = outcomes._context_snapshot
_current_learning_summary = core.LiveTrader.learning_summary
_current_run_forever = core.LiveTrader.run_forever
_current_runtime_status = core.LiveTrader.runtime_status

# Re-export pure helpers for regression tests and future diagnostic reuse.
_path_metrics = path_metrics
_diagnosis = diagnose
_historical_challenger_summary = historical_summary
_forward_family_evidence_summary = forward_family_summary


def _context_snapshot_v47(state: dict[str, Any]) -> dict[str, Any]:
    snapshot = dict(_current_context_snapshot(state))
    liquidity = dict(state.get("liquidity") or {})
    zones = dict(state.get("zones") or {})
    snapshot.update(
        {
            "price": state.get("price"),
            "setup": dict(state.get("setup") or {}),
            "zones": {
                "demand": [dict(x or {}) for x in (zones.get("demand") or [])[:2]],
                "supply": [dict(x or {}) for x in (zones.get("supply") or [])[:2]],
            },
            "liquidity": {
                "primary_event": dict(liquidity.get("primary_event") or {}),
                **{
                    k: liquidity.get(k)
                    for k in (
                        "recent_high",
                        "recent_low",
                        "previous_day_high",
                        "previous_day_low",
                        "london_high",
                        "london_low",
                        "new_york_high",
                        "new_york_low",
                    )
                },
            },
            "execution_intelligence_capture_version": FORENSICS_VERSION,
        }
    )
    return snapshot


class ExecutionForensicsWorker:
    def __init__(self, owner: core.LiveTrader) -> None:
        self.owner = owner
        self.repo = owner.repo
        self.source = SourceRepository(owner.settings)
        self.symbol = owner.symbol
        self._stop = asyncio.Event()
        self._scan_offset = 0
        self.reviewed = 0
        self.last_error = None
        self.last_campaign_id = None
        self.last_run_at = None

    async def stop(self) -> None:
        self._stop.set()

    async def _review_page(self, offset: int) -> tuple[list[dict[str, Any]], int]:
        rows = await self.repo.client.get(
            "live_trader_trade_reviews",
            params={
                "select": "campaign_id,outcome,triggered,realised_r,setup_family,setup_family_descriptor,publication_context,completion_context,review,review_version,completed_at",
                "symbol": f"eq.{self.symbol}",
                "order": "completed_at.asc",
                "limit": str(BACKFILL_READ_LIMIT),
                "offset": str(max(0, int(offset))),
            },
        )
        pending = [
            dict(row or {})
            for row in rows
            if str(dict((row or {}).get("review") or {}).get("forensics_version") or "") != FORENSICS_VERSION
        ]
        return pending, len(rows)

    async def _campaign(self, campaign_id: str) -> dict[str, Any] | None:
        rows = await self.repo.client.get(
            "live_trader_campaigns",
            params={"select": "*", "id": f"eq.{campaign_id}", "limit": "1"},
        )
        if not rows:
            return None
        row = dict(rows[0] or {})
        return {**row, **dict(row.get("campaign") or {})}

    async def _source_path(self, campaign: dict[str, Any]) -> list[dict[str, Any]]:
        created = parse_time(campaign.get("created_at"))
        completed = parse_time(campaign.get("completed_at"))
        if not created or not completed:
            return []
        start = created - timedelta(minutes=5)
        end = completed + timedelta(minutes=POST_COMPLETION_MINUTES)
        bars: list[dict[str, Any]] = []
        cursor: str | None = None
        while len(bars) < MAX_SOURCE_BARS:
            limit = min(1000, MAX_SOURCE_BARS - len(bars))
            page = await self.source.fetch_candles_page(
                self.symbol,
                "1min",
                after=cursor,
                date_from=start.isoformat() if cursor is None else None,
                date_to=end.isoformat(),
                limit=limit,
            )
            if not page:
                break
            bars.extend(page)
            cursor = str(page[-1].get("candle_time") or "")
            if len(page) < limit:
                break
        return bars[:MAX_SOURCE_BARS]

    def _path_is_ready(self, campaign: dict[str, Any], bars: list[dict[str, Any]]) -> bool:
        created = parse_time(campaign.get("created_at"))
        completed = parse_time(campaign.get("completed_at"))
        if not created or not completed or not bars:
            return False

        stamps = sorted({stamp for stamp in (bar_time(bar) for bar in bars) if stamp is not None})
        if not stamps:
            return False

        required_start = ceil_minute(created - timedelta(minutes=5))
        required_end = (completed + timedelta(minutes=POST_COMPLETION_MINUTES)).replace(second=0, microsecond=0)
        if abs((stamps[0] - required_start).total_seconds()) > 1.0:
            return False
        if stamps[-1] < required_end:
            return False

        # A permanent forensic record is allowed only when the complete source-M1
        # path is continuous. Missing minutes could otherwise manufacture a better
        # MFE/MAE, hide a target touch, or misclassify what happened after the stop.
        for left, right in zip(stamps, stamps[1:]):
            if abs((right - left).total_seconds() - 60.0) > 1.0:
                return False
        return True

    async def _publication_opinion(self, campaign: dict[str, Any]) -> dict[str, Any] | None:
        campaign_id = str(campaign.get("id") or "")
        if not campaign_id:
            return None
        rows = await self.repo.client.get(
            "live_trader_opinions",
            params={
                "select": "observed_at,resolved_at,bias,confidence,direction_correct,trade_outcome,realised_r,learning_success",
                "trade_idea->>campaign_id": f"eq.{campaign_id}",
                "order": "observed_at.asc",
                "limit": "20",
            },
        )
        if not rows:
            return None
        created = parse_time(campaign.get("created_at"))
        if not created:
            return dict(rows[0] or {})
        return dict(
            min(
                rows,
                key=lambda row: abs(((parse_time(row.get("observed_at")) or created) - created).total_seconds()),
            )
            or {}
        )

    async def _family_rows(self, family: str | None) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        if not family:
            return [], []
        forward = await self.repo.client.get(
            "live_trader_opinions",
            params={
                "select": "observed_at,learning_success",
                "symbol": f"eq.{self.symbol}",
                "setup_family": f"eq.{family}",
                "learning_version": f"eq.{hardening.LEARNING_NAMESPACE}",
                "independent_sample": "eq.true",
                "status": "eq.resolved",
                "order": "observed_at.desc",
                "limit": "300",
            },
        )
        historical = await self.repo.client.get(
            "live_trader_historical_learning",
            params={
                "select": "best_challenger,challenger_results,market_state",
                "symbol": f"eq.{self.symbol}",
                "setup_family": f"eq.{family}",
                "path_complete": "eq.true",
                "market_state->execution_regrade->>version": f"eq.{integrity.REGRADER_VERSION}",
                "market_state->execution_regrade->>execution_schema": f"eq.{integrity.EXECUTION_SCHEMA}",
                "order": "observed_at.desc",
                "limit": "250",
            },
        )
        return [dict(row or {}) for row in forward], [dict(row or {}) for row in historical]

    async def enrich(self, row: dict[str, Any]) -> bool:
        # Challenger evidence must not be frozen into a permanent review while the
        # v39 historical execution regrader is still changing that evidence.
        if getattr(self.owner, "_execution_regrade_ready_v39", False) is not True:
            return False

        campaign_id = str(row.get("campaign_id") or "")
        campaign = await self._campaign(campaign_id) if campaign_id else None
        if not campaign:
            return False
        bars = await self._source_path(campaign)
        if not self._path_is_ready(campaign, bars):
            return False

        opinion = await self._publication_opinion(campaign)
        family = str(row.get("setup_family") or campaign.get("setup_family") or "") or None
        forward, historical = await self._family_rows(family)
        fx = build_forensics(
            campaign,
            row,
            bars,
            opinion,
            historical,
            forward,
            FORENSICS_VERSION,
            MAX_SOURCE_BARS,
        )
        fx["analysed_at"] = core.utc_now().isoformat()
        fx["source_path_integrity"] = {
            "continuous_m1": True,
            "execution_schema": integrity.EXECUTION_SCHEMA,
            "regrader_version": integrity.REGRADER_VERSION,
        }
        review = dict(row.get("review") or {})
        review.setdefault("base_lesson", review.get("lesson"))
        review["lesson"] = str((fx.get("diagnosis") or {}).get("lesson") or review.get("lesson") or "")
        review["forensics_version"] = FORENSICS_VERSION
        review["execution_forensics"] = fx
        await self.repo.client.patch(
            "live_trader_trade_reviews",
            {
                "review": review,
                "review_version": POST_TRADE_REVIEW_VERSION,
                "updated_at": core.utc_now().isoformat(),
            },
            filters={"campaign_id": f"eq.{campaign_id}"},
        )
        self.reviewed += 1
        self.last_campaign_id = campaign_id
        self.last_error = None
        self.owner._execution_forensics_cache_at_v47 = None
        return True

    async def run_forever(self) -> None:
        while not self._stop.is_set():
            progressed = False
            scan_advanced = False
            try:
                if getattr(self.owner, "_execution_regrade_ready_v39", False) is True:
                    pending, raw_count = await self._review_page(self._scan_offset)
                    if raw_count == 0:
                        if self._scan_offset:
                            self._scan_offset = 0
                            scan_advanced = True
                    else:
                        self._scan_offset += raw_count
                        scan_advanced = True
                        # Scan the whole page. A missing campaign or permanently
                        # incomplete legacy path can no longer starve later reviews.
                        for row in pending:
                            if await self.enrich(row):
                                progressed = True
                                break
                self.last_run_at = core.utc_now().isoformat()
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                self.last_error = str(exc)[:500]
                core.logger.warning("Live Trader execution forensics cycle failed: %s", exc)
            try:
                await asyncio.wait_for(
                    self._stop.wait(),
                    timeout=1.0 if progressed or scan_advanced else 60.0,
                )
            except asyncio.TimeoutError:
                pass

    def status(self) -> dict[str, Any]:
        return {
            "version": FORENSICS_VERSION,
            "running": not self._stop.is_set(),
            "diagnostic_only": True,
            "waiting_for_execution_regrade": getattr(self.owner, "_execution_regrade_ready_v39", False) is not True,
            "reviewed_this_runtime": self.reviewed,
            "last_campaign_id": self.last_campaign_id,
            "last_run_at": self.last_run_at,
            "last_error": self.last_error,
            "review_scan_offset": self._scan_offset,
            "max_temporary_m1_bars": MAX_SOURCE_BARS,
            "post_completion_minutes": POST_COMPLETION_MINUTES,
            "requires_continuous_m1_path": True,
            "execution_schema": integrity.EXECUTION_SCHEMA,
        }


async def _execution_summary(self: core.LiveTrader) -> dict[str, Any]:
    now = core.utc_now()
    cached_at = getattr(self, "_execution_forensics_cache_at_v47", None)
    cached = getattr(self, "_execution_forensics_cache_v47", None)
    if isinstance(cached_at, datetime) and isinstance(cached, dict) and (now - cached_at).total_seconds() < SUMMARY_CACHE_SECONDS:
        return dict(cached)
    try:
        rows = await self.repo.client.get(
            "live_trader_trade_reviews",
            params={
                "select": "campaign_id,outcome,completed_at,review",
                "symbol": f"eq.{self.symbol}",
                "order": "completed_at.desc",
                "limit": "100",
            },
        )
    except Exception as exc:
        return {"version": FORENSICS_VERSION, "available": False, "error": str(exc)[:240]}
    enriched: list[dict[str, Any]] = []
    counts: dict[str, int] = {}
    for row in rows:
        review = dict((row or {}).get("review") or {})
        fx = dict(review.get("execution_forensics") or {})
        if review.get("forensics_version") != FORENSICS_VERSION or not fx:
            continue
        primary = str((fx.get("diagnosis") or {}).get("primary") or "unknown")
        counts[primary] = counts.get(primary, 0) + 1
        enriched.append(
            {
                "campaign_id": row.get("campaign_id"),
                "outcome": row.get("outcome"),
                "completed_at": row.get("completed_at"),
                "forensics": fx,
            }
        )
    worker = getattr(self, "_execution_forensics_worker_v47", None)
    result = {
        "version": FORENSICS_VERSION,
        "review_version": POST_TRADE_REVIEW_VERSION,
        "available": True,
        "diagnostic_only": True,
        "reviews_enriched": len(enriched),
        "reviews_pending": max(0, len(rows) - len(enriched)),
        "diagnosis_counts": counts,
        "recent": enriched[:10],
        "worker": worker.status() if worker else {"running": False},
        "policy": "Execution Intelligence diagnoses completed campaigns and shadow-replays bounded alternatives. It cannot rewrite entries, stops, targets, confidence or governor rules automatically.",
    }
    self._execution_forensics_cache_at_v47 = now
    self._execution_forensics_cache_v47 = dict(result)
    return result


async def _learning_summary_v47(self: core.LiveTrader) -> dict[str, Any]:
    summary = dict(await _current_learning_summary(self))
    execution = await _execution_summary(self)
    summary["execution_intelligence"] = execution
    weekly = summary.get("weekly_trade_outcomes")
    if isinstance(weekly, dict) and execution.get("available"):
        by_id = {
            str(item.get("campaign_id")): dict(item.get("forensics") or {})
            for item in execution.get("recent", [])
            if item.get("campaign_id")
        }
        weekly = dict(weekly)
        weekly["recent"] = [
            {
                **dict(item or {}),
                **(
                    {"forensics": by_id[str(item.get("campaign_id"))]}
                    if str(item.get("campaign_id")) in by_id
                    else {}
                ),
            }
            for item in weekly.get("recent", []) or []
        ]
        weekly["execution_forensics_version"] = FORENSICS_VERSION
        weekly["forensic_reviews"] = execution.get("reviews_enriched", 0)
        summary["weekly_trade_outcomes"] = weekly
    return summary


def _runtime_status_v47(self: core.LiveTrader) -> dict[str, Any]:
    status = dict(_current_runtime_status(self))
    worker = getattr(self, "_execution_forensics_worker_v47", None)
    status["execution_forensics"] = (
        worker.status()
        if worker
        else {"version": FORENSICS_VERSION, "running": False, "diagnostic_only": True}
    )
    return status


async def _run_forever_v47(self: core.LiveTrader) -> None:
    worker = getattr(self, "_execution_forensics_worker_v47", None) or ExecutionForensicsWorker(self)
    self._execution_forensics_worker_v47 = worker
    task = asyncio.create_task(worker.run_forever(), name="eve-live-trader-execution-forensics")
    try:
        await _current_run_forever(self)
    finally:
        await worker.stop()
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass


outcomes._context_snapshot = _context_snapshot_v47
core.LiveTrader.learning_summary = _learning_summary_v47
core.LiveTrader.runtime_status = _runtime_status_v47
core.LiveTrader.run_forever = _run_forever_v47
hardening._run_forever_v26 = _run_forever_v47
integrity._run_forever_v39 = _run_forever_v47
runtime._run_forever_v30 = _run_forever_v47
