from __future__ import annotations

from typing import Any

from app.services import live_trader as core
from app.services import live_trader_clear_bias_gate_v45 as clear_gate
from app.services import live_trader_execution_integrity_v39 as integrity
from app.services import live_trader_london_session_gate_v46 as session_gate
from app.services import live_trader_trade_lock_v28 as lock
from app.services import live_trader_zone_target_guard_v49 as v49

RUNTIME_VERSION = "eve-live-zone-target-runtime-v1"
_v49_trade_idea = v49._trade_idea_v49
# v49 captured the genuine v46 session wrapper before later compatibility aliases
# were redirected to the newest runtime. Keep that stable function for delegation.
_session_trade_idea = v49._current_trade_idea


def _is_v49_campaign(campaign: dict[str, Any]) -> bool:
    return "source_zone_required" in campaign or isinstance(campaign.get("target_policy"), dict)


def _trade_idea_v51(
    self: core.LiveTrader,
    price: float,
    atr: float,
    bias: dict[str, Any],
    zones: dict[str, list[dict[str, Any]]],
    liquidity: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, Any]]:
    campaign = getattr(self, "_live_campaign", None)
    status = str((campaign or {}).get("status") or "").lower() if isinstance(campaign, dict) else ""

    if isinstance(campaign, dict) and status == "pending":
        # Campaigns published before v49 did not record an exact source-zone
        # identity. Preserve the established session/lock behaviour instead of
        # retrospectively manufacturing a zone relationship from today's market.
        if not _is_v49_campaign(campaign):
            return _session_trade_idea(self, price, atr, bias, zones, liquidity)

        # Existing session safety remains stronger than the new age/zone checks.
        # If the idea was created outside the London window or the window has
        # since closed, let v46 own the cancellation reason and audit record.
        if clear_gate._is_modern_structural_bias(dict(bias or {})):
            session = session_gate._session_status()
            created_inside = session_gate._campaign_created_inside_session(campaign)
            if created_inside is False or not bool(session.get("open")):
                return _session_trade_idea(self, price, atr, bias, zones, liquidity)

    return _v49_trade_idea(self, price, atr, bias, zones, liquidity)


def _runtime_status_v51(self: core.LiveTrader) -> dict[str, Any]:
    state = dict(v49._runtime_status_v49(self))
    state.update(
        {
            "zone_target_runtime_version": RUNTIME_VERSION,
            "legacy_pending_campaigns_preserve_prior_chain": True,
            "session_gate_precedes_v49_pending_revalidation": True,
        }
    )
    return state


core.LiveTrader._trade_idea = _trade_idea_v51  # type: ignore[method-assign]
core.LiveTrader.runtime_status = _runtime_status_v51  # type: ignore[method-assign]
# Maintain the repository's established alias-identity contract: legacy modules
# expose the newest audited production wrapper, not a superseded implementation.
integrity._trade_idea_v39 = _trade_idea_v51
lock._trade_idea_v28 = _trade_idea_v51
session_gate._trade_idea_v46 = _trade_idea_v51

# Install diagnostic-only profit-protection replay after all live execution wrappers
# are fixed in place. This changes stored learning evidence, not live stops.
from app.services import live_trader_management_learning_v52 as _management_learning_v52  # noqa: E402,F401
# Use explicit directional breakout wording so EVE says what actually failed:
# failed bullish breakout when an upside break fails; failed bearish breakout when a downside break fails.
from app.services import live_trader_breakout_wording_v53 as _breakout_wording_v53  # noqa: E402,F401
# Final user-language boundary: remove fakeout terminology from labels/explanations
# while preserving internal event classes and learning confirmation codes.
from app.services import live_trader_breakout_language_boundary_v54 as _breakout_language_boundary_v54  # noqa: E402,F401
# Keep a separate always-on directional opinion for the current session without
# granting it authority over the hardened trade-entry gate.
from app.services import live_trader_session_outlook_v55 as _live_trader_session_outlook_v55  # noqa: E402,F401
