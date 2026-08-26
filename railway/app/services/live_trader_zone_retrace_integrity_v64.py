from __future__ import annotations

from typing import Any

from app.services import live_trader as core
from app.services import live_trader_historical_runtime_v30 as historical_runtime
from app.services import live_trader_trade_lock_v28 as lock
from app.services import live_trader_trade_outcomes_v38 as outcomes
from app.services import live_trader_zone_retrace_audit_v60 as audit
from app.services import live_trader_zone_retrace_specialist_v58 as v58

INTEGRITY_VERSION = "eve-live-zone-retrace-integrity-v64"
COUNTER_VERSION = "cross_process_completed_cycle_v64"
CLAIM_LEASE_SECONDS = 420

_current_refresh_state = core.LiveTrader.refresh_state
_current_runtime_status = core.LiveTrader.runtime_status


def _num(value: Any, default: float = 0.0) -> float:
    return core.number(value, default)


def _row_from_rpc(payload: Any) -> dict[str, Any]:
    if isinstance(payload, list) and payload:
        return dict(payload[0] or {})
    if isinstance(payload, dict):
        return dict(payload)
    return {}


async def _load_specialist_row(self: core.LiveTrader) -> dict[str, Any]:
    try:
        rows = await self.repo.client.get(
            "live_trader_zone_retrace_learning_state",
            params={"select": "*", "symbol": f"eq.{self.symbol}", "limit": "1"},
        )
        return dict(rows[0] or {}) if rows else {}
    except Exception:
        return {}


def _audited_specialist(payload: dict[str, Any]) -> dict[str, Any]:
    specialist = dict(payload or {})
    evidence = dict(specialist.get("execution_evidence") or {})
    preferred_key = str(specialist.get("promoted_execution") or specialist.get("best_execution") or "market")
    preferred = dict(evidence.get(preferred_key) or evidence.get("market") or {})
    scored = int(_num(preferred.get("scored")))
    wins = int(_num(preferred.get("wins")))
    losses = int(_num(preferred.get("losses")))

    specialist.update(
        {
            "name": "Zone Retracement Specialist",
            "active": True,
            "strategy_key": v58.STRATEGY_KEY,
            "version": v58.SPECIALIST_VERSION,
            "integrity_version": INTEGRITY_VERSION,
            "audit_version": audit.AUDIT_VERSION,
            "evidence_scope": "independent_pullback_only",
            "breakout_examples_excluded": True,
            "independence_deduplication": True,
            "cycle_counter_version": specialist.get("cycle_counter_version") or COUNTER_VERSION,
            "phase": "MATURE CANDIDATE" if specialist.get("promoted_execution") else "DEEP LEARNING",
            "objective": "Perfect directional retracement-to-zone execution using independent historical and forward evidence without weakening the live campaign safety gates.",
            "historical_episodes": int(_num(specialist.get("relevant_episodes"))),
            "scored_examples": scored,
            "successes": wins,
            "failures": losses,
            "raw_success_rate": round(wins / scored, 4) if scored else None,
            "live_entry_policy": "market_after_zone_confirmation",
            "breakout_chasing_allowed": False,
            "blind_limit_entry_allowed": False,
            "counter_note": "cycle_count contains only successfully completed database-claimed cycles since cycle_counter_accurate_since; legacy_cycle_count preserves the pre-hardening headline for audit history only.",
        }
    )
    return specialist


async def _run_specialist_cycle_v64(self: core.LiveTrader) -> dict[str, Any]:
    now = core.utc_now()
    try:
        claim_payload = await self.repo.client.rpc(
            "claim_live_trader_zone_retrace_cycle",
            {
                "p_symbol": self.symbol,
                "p_min_interval_seconds": int(v58.LEARNING_CYCLE_SECONDS),
                "p_lease_seconds": CLAIM_LEASE_SECONDS,
            },
        )
        claim = _row_from_rpc(claim_payload)
        if not bool(claim.get("claimed")):
            current = _audited_specialist(await _load_specialist_row(self))
            current["cycle_claimed"] = False
            self._zone_retrace_learning_v58 = current
            return current

        token = str(claim.get("claim_token") or "")
        if not token:
            raise RuntimeError("database cycle claim returned no claim token")

        rows = await v58._historical_rows(self)
        relevant, evidence = v58._score_execution_evidence(rows)
        best, promoted = v58._best_execution(evidence)
        status = "learning" if promoted is None else "mature_candidate"

        completion_payload = await self.repo.client.rpc(
            "complete_live_trader_zone_retrace_cycle",
            {
                "p_symbol": self.symbol,
                "p_claim_token": token,
                "p_version": v58.SPECIALIST_VERSION,
                "p_rows_evaluated": len(rows),
                "p_relevant_episodes": relevant,
                "p_execution_evidence": evidence,
                "p_best_execution": best,
                "p_promoted_execution": promoted,
                "p_status": status,
            },
        )
        completion = _row_from_rpc(completion_payload)
        if not bool(completion.get("completed")):
            current = _audited_specialist(await _load_specialist_row(self))
            current["cycle_claimed"] = True
            current["cycle_completion_accepted"] = False
            current["last_error"] = "Specialist evaluation finished after its database claim was superseded; result was correctly discarded and not counted."
            self._zone_retrace_learning_v58 = current
            return current

        payload = _audited_specialist(
            {
                "symbol": self.symbol,
                "strategy_key": v58.STRATEGY_KEY,
                "version": v58.SPECIALIST_VERSION,
                "cycle_count": int(_num(completion.get("cycle_count"))),
                "last_cycle_at": completion.get("completed_at") or now.isoformat(),
                "legacy_cycle_count": completion.get("legacy_cycle_count"),
                "cycle_counter_accurate_since": completion.get("accurate_since"),
                "cycle_counter_version": COUNTER_VERSION,
                "rows_evaluated": len(rows),
                "relevant_episodes": relevant,
                "execution_evidence": evidence,
                "best_execution": best,
                "promoted_execution": promoted,
                "status": status,
            }
        )
        payload["cycle_claimed"] = True
        payload["cycle_completion_accepted"] = True

        await self.repo.client.insert(
            "system_events",
            {
                "level": "success",
                "component": "live_trader_zone_retrace_specialist",
                "message": (
                    f"Audited zone retracement cycle {payload['cycle_count']} completed under a database claim; "
                    f"{len(rows)} historical rows checked and {relevant} independent retracement episodes scored. "
                    f"Best execution: {best or 'not enough evidence'}."
                ),
                "details": {
                    "integrity_version": INTEGRITY_VERSION,
                    "counter_version": COUNTER_VERSION,
                    "strategy_key": v58.STRATEGY_KEY,
                    "cycle_count": payload["cycle_count"],
                    "legacy_cycle_count": payload.get("legacy_cycle_count"),
                    "rows_evaluated": len(rows),
                    "relevant_episodes": relevant,
                    "best_execution": best,
                    "promoted_execution": promoted,
                    "execution_evidence": evidence,
                },
            },
            return_rows=False,
        )
        self._zone_retrace_learning_v58 = payload
        self._zone_retrace_last_cycle_v58 = now
        return payload
    except Exception as exc:
        core.logger.warning("Zone Retracement Specialist v64 cycle failed: %s", exc)
        current = _audited_specialist(await _load_specialist_row(self))
        current["worker_error"] = True
        current["last_error"] = str(exc)[:500]
        current["integrity_version"] = INTEGRITY_VERSION
        self._zone_retrace_learning_v58 = current
        self._zone_retrace_last_cycle_v58 = now
        return current


async def _refresh_state_v64(self: core.LiveTrader, *, force_rows: bool = False) -> dict[str, Any]:
    state = dict(await _current_refresh_state(self, force_rows=force_rows))
    specialist = dict(state.get("zone_retrace_learning") or (state.get("learning") or {}).get("zone_retrace_specialist") or {})
    if not specialist:
        specialist = await _load_specialist_row(self)
    specialist = _audited_specialist(specialist)

    state["zone_retrace_learning"] = specialist
    learning = dict(state.get("learning") or {})
    learning["zone_retrace_specialist"] = specialist
    # Backward-compatible headline now points to the exact same audited evidence,
    # eliminating the stale 1,106/629 broad-sample headline from the live state.
    learning["strategy_specialist"] = specialist
    state["learning"] = learning
    self._latest_state = state
    return state


def _runtime_status_v64(self: core.LiveTrader) -> dict[str, Any]:
    status = dict(_current_runtime_status(self))
    status.update(
        {
            "zone_retrace_integrity_version": INTEGRITY_VERSION,
            "zone_retrace_cycle_counter_version": COUNTER_VERSION,
            "zone_retrace_cross_process_claim": True,
            "zone_retrace_completed_cycles_only": True,
            "zone_retrace_evidence_scope": "independent_pullback_only",
        }
    )
    return status


# _refresh_state_v58 resolves this module global at call time, so replacing the
# worker function hardens cycle execution without bypassing the established v58
# refresh, v38 outcome review, news guard, campaign lock, or historical runtime.
v58._run_specialist_cycle = _run_specialist_cycle_v64

core.LiveTrader.refresh_state = _refresh_state_v64  # type: ignore[method-assign]
core.LiveTrader.runtime_status = _runtime_status_v64  # type: ignore[method-assign]

# This project intentionally keeps historical compatibility aliases pointing at
# the newest audited runtime wrapper. Restore that invariant after v58 added its
# specialist refresh layer.
v58._refresh_state_v58 = _refresh_state_v64
lock._refresh_state_v28 = _refresh_state_v64
historical_runtime._refresh_state_v30 = _refresh_state_v64
outcomes._refresh_v38 = _refresh_state_v64
