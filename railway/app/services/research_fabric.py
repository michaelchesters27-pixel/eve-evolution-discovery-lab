from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

LEGACY_DATASET = "legacy_15m"
FABRIC_DATASET = "every_m5_fabric"
FABRIC_VERSION = "eve-multitimeframe-fabric-v1"
FABRIC_SNAPSHOT_INTERVAL = "5min"
FABRIC_SOURCE_INTERVAL = "5min"

# Keep the large six-year in-memory research set compact. The full mtf_context
# remains stored in Supabase and is read for the live/latest window, but the
# current Scientist v2 grammar only needs these deterministic research fields.
FABRIC_RESEARCH_COLUMNS = (
    "symbol,snapshot_interval,source_interval,candle_time,open,high,low,close,volume,weekday,month,quarter,"
    "hour_utc,week_of_month,session,direction,range_price,body_price,upper_wick,lower_wick,close_location,"
    "atr_14,average_range_12,volatility_12,compression_ratio,return_1_pct,return_3_pct,return_12_pct,"
    "return_48_pct,return_288_pct,context_m15_return_pct,context_h1_return_pct,context_h4_return_pct,"
    "context_d1_return_pct,trend_12_atr,trend_48_atr,streak,regime,alignment_score,outcomes,"
    "outcome_horizons,outcome_complete,feature_version,fabric_version"
)


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def normalise_rpc_json(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return dict(value)
    if isinstance(value, list) and value:
        first = value[0]
        if isinstance(first, dict) and set(first) == {"get_fabric_audit"}:
            inner = first.get("get_fabric_audit")
            return dict(inner) if isinstance(inner, dict) else {}
        if isinstance(first, dict) and set(first) == {"audit"}:
            inner = first.get("audit")
            return dict(inner) if isinstance(inner, dict) else {}
        return dict(first) if isinstance(first, dict) else {}
    return {}


def hard_integrity_passes(audit: dict[str, Any]) -> bool:
    gates = dict(audit.get("gates") or {})
    required = (
        "audit_current",
        "enough_history",
        "m1_coverage",
        "higher_timeframe_coverage",
        "historical_outcomes",
        "zero_lookahead",
        "feature_parity",
    )
    return all(bool(gates.get(key)) for key in required)


def initial_cutover_passes(audit: dict[str, Any]) -> bool:
    return bool(audit.get("ready_for_scientist_cutover")) and hard_integrity_passes(audit)


def rules_use_fabric(rules: dict[str, Any]) -> bool:
    market = dict(rules.get("market") or {})
    return (
        str(market.get("snapshot_interval") or "") == FABRIC_SNAPSHOT_INTERVAL
        and str(market.get("source_interval") or "") == FABRIC_SOURCE_INTERVAL
        and str(market.get("research_dataset") or "") == FABRIC_DATASET
    )


async def fabric_audit(repo: Any) -> dict[str, Any]:
    return normalise_rpc_json(await repo.client.rpc("get_fabric_audit", {}))


async def dataset_state(repo: Any, scientist_version: str) -> dict[str, Any]:
    rows = await repo.client.get(
        "scientist_dataset_state",
        params={"select": "*", "scientist_version": f"eq.{scientist_version}", "limit": "1"},
    )
    return dict(rows[0]) if rows else {}


async def resolve_dataset_state(repo: Any, scientist_version: str, audit: dict[str, Any]) -> dict[str, Any]:
    """Persist a one-way verified cutover while allowing integrity suspension.

    `caught_up` is required for the first cutover. After activation, a newly
    arriving source candle may briefly make the fabric one bar behind; that does
    not send the scientist back to the legacy dataset. Hard integrity failures do.
    """
    current = await dataset_state(repo, scientist_version)
    was_fabric = str(current.get("active_dataset") or "") == FABRIC_DATASET
    hard_ok = hard_integrity_passes(audit)
    can_activate = initial_cutover_passes(audit)

    if was_fabric:
        active_dataset = FABRIC_DATASET
        status = "active" if hard_ok else "suspended_integrity"
        cutover_at = current.get("cutover_at") or utc_now_iso()
    elif can_activate:
        active_dataset = FABRIC_DATASET
        status = "active"
        cutover_at = utc_now_iso()
    else:
        active_dataset = LEGACY_DATASET
        status = "pending_cutover"
        cutover_at = current.get("cutover_at")

    payload = {
        "scientist_version": scientist_version,
        "active_dataset": active_dataset,
        "status": status,
        "fabric_version": str(audit.get("fabric_version") or FABRIC_VERSION),
        "cutover_at": cutover_at,
        "last_verified_at": utc_now_iso() if hard_ok else current.get("last_verified_at"),
        "audit_snapshot": audit,
        "updated_at": utc_now_iso(),
    }
    await repo.client.upsert("scientist_dataset_state", payload, on_conflict="scientist_version")
    return payload


async def load_fabric_rows(
    repo: Any,
    symbol: str,
    *,
    complete_only: bool = True,
    after: str | None = None,
) -> list[dict[str, Any]]:
    """Load the research fabric with bounded keyset pagination.

    `after` makes cache refreshes incremental: once Scientist v2 has loaded the
    six-year history it asks only for newly completed M5 rows. This avoids
    re-downloading hundreds of thousands of historical rows every cache cycle.
    """
    rows: list[dict[str, Any]] = []
    cursor: str | None = after
    page = 1000

    while True:
        params = {
            "select": FABRIC_RESEARCH_COLUMNS,
            "symbol": f"eq.{symbol}",
            "snapshot_interval": f"eq.{FABRIC_SNAPSHOT_INTERVAL}",
            "source_interval": f"eq.{FABRIC_SOURCE_INTERVAL}",
            "order": "candle_time.asc",
            "limit": str(page),
        }
        if complete_only:
            params["outcome_complete"] = "eq.true"
        if cursor:
            params["candle_time"] = f"gt.{cursor}"

        batch = await repo.client.get("m5_research_snapshots", params=params)
        if not batch:
            break

        rows.extend(batch)
        next_cursor = str(batch[-1].get("candle_time") or "")
        if not next_cursor or next_cursor == cursor:
            raise RuntimeError("M5 fabric keyset scan did not advance candle_time cursor")
        cursor = next_cursor

        if len(batch) < page:
            break

    return rows


async def latest_fabric_rows(repo: Any, symbol: str, *, limit: int = 120) -> list[dict[str, Any]]:
    return await repo.client.get(
        "m5_research_snapshots",
        params={
            "select": "*",
            "symbol": f"eq.{symbol}",
            "snapshot_interval": f"eq.{FABRIC_SNAPSHOT_INTERVAL}",
            "source_interval": f"eq.{FABRIC_SOURCE_INTERVAL}",
            "order": "candle_time.desc",
            "limit": str(max(1, min(500, int(limit)))),
        },
    )
