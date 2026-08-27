from __future__ import annotations

from datetime import timedelta
from typing import Any

from app.services.fabric_builder import FabricBuilder
from app.services.m5_foundation import HORIZON_BARS, _outcome_for_horizon
from app.services.multitimeframe import as_utc
from app.services.research_fabric import fabric_audit, resolve_dataset_state

OUTCOME_BACKFILL_VERSION = "eve-fabric-outcome-backfill-v1"
SCIENTIST_VERSION = "eve-autonomous-scientist-v2"
SCAN_LIMIT = 1000
APPLY_LIMIT = 750
RECENT_LOOKBACK_DAYS = 30


OriginalBuildOnce = FabricBuilder.build_once


def _normalise_rpc(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return dict(value)
    if isinstance(value, list) and value and isinstance(value[0], dict):
        first = dict(value[0])
        if len(first) == 1:
            inner = next(iter(first.values()))
            if isinstance(inner, dict):
                return dict(inner)
        return first
    return {}


def build_outcome_update(candidate: dict[str, Any], future: list[dict[str, Any]]) -> dict[str, Any] | None:
    """Build the exact forward labels used by the original M5 fabric builder."""
    if len(future) < max(HORIZON_BARS.values()):
        return None
    try:
        atr = float(candidate.get("atr_14") or 0.0)
    except (TypeError, ValueError):
        return None
    if atr <= 0:
        return None

    outcomes: dict[str, Any] = {}
    horizons: list[int] = []
    for horizon_minutes, horizon_bars in HORIZON_BARS.items():
        result = _outcome_for_horizon(candidate, future, horizon_bars, atr)
        if result is None:
            return None
        outcomes[str(horizon_minutes)] = result
        horizons.append(horizon_minutes)

    if len(horizons) != len(HORIZON_BARS):
        return None
    return {
        "candle_time": str(candidate.get("candle_time") or ""),
        "outcomes": outcomes,
        "outcome_horizons": horizons,
    }


async def backfill_mature_outcomes(builder: FabricBuilder) -> dict[str, Any]:
    """Complete recent M5 labels after 48 actual future M5 bars exist.

    New live fabric rows are intentionally created immediately so their causal
    features and MTF context are available. Their 240-minute outcome cannot exist
    yet. The old builder advanced its cursor and never revisited those rows, which
    made historical-outcome coverage decay until the Scientist hard gate suspended
    itself. This bounded repair revisits only the recent rolling window and uses
    the next 48 *actual* M5 bars, so weekends/market closures do not corrupt the
    horizon or require lowering the integrity threshold.
    """
    latest = await builder._source_boundary("5min", newest=True)
    if latest is None:
        return {"completed": 0, "reason": "no_source_m5"}

    cutoff = latest - timedelta(days=RECENT_LOOKBACK_DAYS)
    candidates = await builder.repo.client.get(
        "m5_research_snapshots",
        params={
            "select": "candle_time,open,high,low,close,atr_14,outcome_complete",
            "symbol": f"eq.{builder.settings.source_symbol}",
            "snapshot_interval": "eq.5min",
            "source_interval": "eq.5min",
            "outcome_complete": "eq.false",
            "candle_time": f"gte.{cutoff.isoformat()}",
            "order": "candle_time.desc",
            "limit": str(SCAN_LIMIT),
        },
    )
    if not candidates:
        audit = await fabric_audit(builder.repo)
        state = await resolve_dataset_state(builder.repo, SCIENTIST_VERSION, audit)
        return {
            "completed": 0,
            "reason": "no_recent_incomplete_rows",
            "scientist_status": state.get("status"),
            "historical_outcome_coverage": (audit.get("coverage") or {}).get("historical_outcomes"),
        }

    stamps = [as_utc(row.get("candle_time")) for row in candidates]
    stamps = [stamp for stamp in stamps if stamp is not None]
    if not stamps:
        return {"completed": 0, "reason": "candidate_times_invalid"}
    oldest = min(stamps)

    # Fetch from the oldest selected incomplete row through the current source
    # boundary. For the rolling 30-day repair this remains a bounded source read.
    source_rows = await builder._fetch_range("5min", oldest, latest + timedelta(minutes=5))
    ordered_source = sorted(
        (row for row in source_rows if as_utc(row.get("candle_time")) is not None),
        key=lambda row: as_utc(row.get("candle_time")),
    )
    index_by_time = {
        as_utc(row.get("candle_time")): index
        for index, row in enumerate(ordered_source)
        if as_utc(row.get("candle_time")) is not None
    }

    updates: list[dict[str, Any]] = []
    # Oldest first among the scanned recent rows maximises maturity while the
    # newest <48-bar rows naturally remain untouched until enough market bars exist.
    for candidate in sorted(candidates, key=lambda row: str(row.get("candle_time") or "")):
        stamp = as_utc(candidate.get("candle_time"))
        if stamp is None:
            continue
        source_index = index_by_time.get(stamp)
        if source_index is None:
            continue
        future = ordered_source[source_index + 1 : source_index + 1 + max(HORIZON_BARS.values())]
        update = build_outcome_update(candidate, future)
        if update is None:
            continue
        updates.append(update)
        if len(updates) >= APPLY_LIMIT:
            break

    if not updates:
        audit = await fabric_audit(builder.repo)
        state = await resolve_dataset_state(builder.repo, SCIENTIST_VERSION, audit)
        return {
            "completed": 0,
            "reason": "no_rows_mature_yet",
            "scientist_status": state.get("status"),
            "historical_outcome_coverage": (audit.get("coverage") or {}).get("historical_outcomes"),
        }

    applied = _normalise_rpc(
        await builder.repo.client.rpc(
            "apply_fabric_outcome_backfill",
            {
                "p_symbol": builder.settings.source_symbol,
                "p_updates": updates,
            },
        )
    )
    completed = int(applied.get("completed") or 0)

    # Re-run the real hard audit after the atomic counter update. This does not
    # bypass any gate: resolve_dataset_state returns to active only when every hard
    # integrity condition, including >=99.5% historical outcomes, genuinely passes.
    audit = await fabric_audit(builder.repo)
    state = await resolve_dataset_state(builder.repo, SCIENTIST_VERSION, audit)
    coverage = (audit.get("coverage") or {}).get("historical_outcomes")

    if completed > 0:
        await builder.repo.event(
            "success",
            "fabric_outcome_backfill",
            (
                f"Completed {completed} mature every-M5 outcome labels from actual future M5 bars; "
                f"historical outcome coverage is {float(coverage or 0) * 100:.3f}% and Scientist status is {state.get('status')}."
            ),
            {
                "version": OUTCOME_BACKFILL_VERSION,
                "completed": completed,
                "oldest": applied.get("oldest"),
                "newest": applied.get("newest"),
                "scan_limit": SCAN_LIMIT,
                "apply_limit": APPLY_LIMIT,
                "lookback_days": RECENT_LOOKBACK_DAYS,
                "future_bars_required": max(HORIZON_BARS.values()),
                "historical_outcome_coverage": coverage,
                "historical_outcome_gate": 0.995,
                "scientist_dataset": state.get("active_dataset"),
                "scientist_status": state.get("status"),
                "quality_gate_relaxed": False,
            },
        )

    return {
        "completed": completed,
        "historical_outcome_coverage": coverage,
        "scientist_status": state.get("status"),
        "oldest": applied.get("oldest"),
        "newest": applied.get("newest"),
    }


async def build_once_with_outcome_backfill(self: FabricBuilder) -> dict[str, Any]:
    result = await OriginalBuildOnce(self)
    try:
        result["outcome_backfill"] = await backfill_mature_outcomes(self)
    except Exception as exc:
        # Fabric ingestion must remain live even if the repair path has a transient
        # source/API problem. Keep the Scientist fail-closed and record the fault.
        result["outcome_backfill"] = {"completed": 0, "error": str(exc)[:500]}
        try:
            await self.repo.event(
                "error",
                "fabric_outcome_backfill",
                "M5 outcome backfill failed safely; Scientist integrity remains fail-closed.",
                {"version": OUTCOME_BACKFILL_VERSION, "error": str(exc)[:500]},
            )
        except Exception:
            pass
    return result


if not getattr(FabricBuilder, "_eve_outcome_backfill_v1", False):
    FabricBuilder.build_once = build_once_with_outcome_backfill
    FabricBuilder._eve_outcome_backfill_v1 = True
