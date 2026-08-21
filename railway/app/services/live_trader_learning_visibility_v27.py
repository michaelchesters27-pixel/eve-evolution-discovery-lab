from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from app.services import live_trader as core
from app.services.live_trader_audit_hardening_v26 import (
    ENGINE_VERSION,
    LEARNING_NAMESPACE,
    OBSERVATION_POLICY,
    OUTCOME_SCHEMA,
)

VISIBILITY_VERSION = "eve-live-learning-visibility-v1"


def _parse_time(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def summarise_learning_rows(rows: list[dict[str, Any]], default_horizon_minutes: int) -> dict[str, Any]:
    resolved = [row for row in rows if str(row.get("status") or "") == "resolved"]
    open_rows = [row for row in rows if str(row.get("status") or "") == "open"]
    scored = [bool(row.get("learning_success")) for row in resolved if row.get("learning_success") is not None]
    directional = [bool(row.get("direction_correct")) for row in resolved if row.get("direction_correct") is not None]
    actionable = [
        row
        for row in resolved
        if row.get("trade_outcome") not in {None, "not_triggered", "invalid", "insufficient_m1_path"}
    ]
    trade_scored = [bool(row.get("learning_success")) for row in actionable if row.get("learning_success") is not None]

    due_times: list[datetime] = []
    for row in open_rows:
        observed = _parse_time(row.get("observed_at"))
        if observed is None:
            continue
        horizon = int(core.number(row.get("horizon_minutes"), default_horizon_minutes))
        due_times.append(observed + timedelta(minutes=max(horizon, 1)))

    observed_times = [parsed for parsed in (_parse_time(row.get("observed_at")) for row in rows) if parsed is not None]
    return {
        "recorded": len(rows),
        "open": len(open_rows),
        "resolved": len(resolved),
        "scored": len(scored),
        "correct": sum(scored),
        "accuracy": round(sum(scored) / len(scored), 3) if scored else None,
        "directional_accuracy": round(sum(directional) / len(directional), 3) if directional else None,
        "actionable_trades": len(actionable),
        "trade_accuracy": round(sum(trade_scored) / len(trade_scored), 3) if trade_scored else None,
        "independent_episodes": len({str(row.get("episode_key")) for row in rows if row.get("episode_key")}),
        "families_seen": len({str(row.get("setup_family")) for row in rows if row.get("setup_family")}),
        "independent_days": len({parsed.date().isoformat() for parsed in observed_times}),
        "first_observed_at": min(observed_times).isoformat() if observed_times else None,
        "last_observed_at": max(observed_times).isoformat() if observed_times else None,
        "next_due_at": min(due_times).isoformat() if due_times else None,
    }


async def _learning_summary_v27(self: core.LiveTrader) -> dict[str, Any]:
    try:
        rows = await self.repo.client.get(
            "live_trader_opinions",
            params={
                "select": (
                    "status,learning_success,direction_correct,trade_outcome,realised_r,observed_at,horizon_minutes,"
                    "setup_family,episode_key"
                ),
                "learning_version": f"eq.{LEARNING_NAMESPACE}",
                "independent_sample": "eq.true",
                "order": "observed_at.desc",
                "limit": "5000",
            },
        )
    except Exception:
        rows = []

    summary = summarise_learning_rows(rows, self.settings.live_trader_learning_horizon_minutes)
    summary.update(
        {
            "horizon_minutes": self.settings.live_trader_learning_horizon_minutes,
            "version": LEARNING_NAMESPACE,
            "engine_version": ENGINE_VERSION,
            "outcome_schema": OUTCOME_SCHEMA,
            "visibility_version": VISIBILITY_VERSION,
            "policy": OBSERVATION_POLICY,
        }
    )
    return summary


core.LiveTrader.learning_summary = _learning_summary_v27  # type: ignore[method-assign]
