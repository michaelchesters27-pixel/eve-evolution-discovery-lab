from __future__ import annotations

from typing import Any

from app.services import live_trader as core
from app.services import live_trader_learning_v2 as v2

GOVERNOR_VERSION = "eve-live-learning-governor-v1"
BAD_POSTERIOR_MAX = 0.44
MIN_ACTIVE_SAMPLES = 12

_current_signature = v2.LiveTrader._signature
_current_calibration = v2.LiveTrader._calibration
_current_record = v2.LiveTrader._maybe_record_opinion
_current_runtime_status = v2.LiveTrader.runtime_status


def apply_learning_governor(state: dict[str, Any], learning: dict[str, Any]) -> dict[str, Any]:
    trade = dict(state.get("trade") or {})
    order_type = str(trade.get("order_type") or "none")
    active = bool(learning.get("active"))
    samples = int(core.number(learning.get("samples")))
    posterior = core.number(learning.get("posterior_accuracy"), 0.5)

    governor = {
        "version": GOVERNOR_VERSION,
        "active": active,
        "decision": "observe",
        "posterior_accuracy": round(posterior, 3),
        "samples": samples,
        "veto_threshold": BAD_POSTERIOR_MAX,
    }

    if order_type == "none":
        governor["decision"] = "no_candidate"
        state["learning_governor"] = governor
        return state

    if not active or samples < MIN_ACTIVE_SAMPLES:
        governor["decision"] = "insufficient_evidence"
        state["learning_governor"] = governor
        return state

    if posterior > BAD_POSTERIOR_MAX:
        governor["decision"] = "allow"
        state["learning_governor"] = governor
        return state

    candidate = dict(trade)
    governor.update(
        {
            "decision": "veto",
            "reason": (
                "This mature setup family has performed poorly enough that EVE will not execute the current candidate. "
                "The rejected candidate is still shadow-scored so the family can recover if its behaviour improves."
            ),
            "candidate_trade": candidate,
        }
    )

    setup = dict(state.get("setup") or {})
    setup["status"] = "WATCHING"
    setup["reason"] = (
        f"Learning veto: this setup family has posterior accuracy {posterior:.1%} across {samples} independent outcomes."
    )
    state["setup"] = setup
    state["trade"] = {
        "action": "WAIT",
        "order_type": "none",
        "side": candidate.get("side"),
        "reason": (
            f"EVE rejected the {candidate.get('action') or candidate.get('order_type')} because this mature family "
            f"is below the {BAD_POSTERIOR_MAX:.0%} learning threshold."
        ),
        "manual_only": True,
        "automatic_order_placement": False,
        "learning_veto": True,
    }
    state["learning_governor"] = governor
    return state


def _signature_v25(self: v2.LiveTrader, state: dict[str, Any]) -> str:
    self._learning_governor_pending_state = state
    return _current_signature(self, state)


async def _calibration_v25(self: v2.LiveTrader, signature: str) -> dict[str, Any]:
    learning = await _current_calibration(self, signature)
    state = getattr(self, "_learning_governor_pending_state", None)
    if isinstance(state, dict):
        apply_learning_governor(state, learning)
    return learning


async def _record_v25(self: v2.LiveTrader, state: dict[str, Any]) -> None:
    governor = dict(state.get("learning_governor") or {})
    if governor.get("decision") != "veto":
        await _current_record(self, state)
        return

    candidate = governor.get("candidate_trade")
    if not isinstance(candidate, dict) or str(candidate.get("order_type") or "none") == "none":
        return

    # Keep learning in shadow mode: production state remains WAIT, but the
    # rejected candidate is scored as though it had been allowed. This prevents
    # a bad family from being permanently frozen by its own veto.
    shadow_state = dict(state)
    shadow_state["trade"] = dict(candidate)
    shadow_state["opinion"] = (
        f"Shadow candidate rejected by {GOVERNOR_VERSION}: "
        f"{candidate.get('action') or candidate.get('order_type')} retained for outcome learning only."
    )
    await _current_record(self, shadow_state)


def _runtime_status_v25(self: v2.LiveTrader) -> dict[str, Any]:
    state = dict(_current_runtime_status(self))
    state.update(
        {
            "learning_governor_version": GOVERNOR_VERSION,
            "learning_governor_veto_threshold": BAD_POSTERIOR_MAX,
            "learning_governor_shadow_scoring": True,
        }
    )
    return state


v2.LiveTrader._signature = _signature_v25  # type: ignore[method-assign]
v2.LiveTrader._calibration = _calibration_v25  # type: ignore[method-assign]
v2.LiveTrader._maybe_record_opinion = _record_v25  # type: ignore[method-assign]
v2.LiveTrader.runtime_status = _runtime_status_v25  # type: ignore[method-assign]
