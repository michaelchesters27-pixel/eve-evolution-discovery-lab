from __future__ import annotations

from typing import Any

from app.services import live_trader as core
from app.services import live_trader_state_integrity_v65 as v65
from app.services import live_trader_trade_lock_v28 as lock

CONSENSUS_VERSION = "eve-live-campaign-consensus-v66"
_current_persist_state = core.LiveTrader._maybe_persist_state
_current_runtime_status = core.LiveTrader.runtime_status


def _authoritative_campaign_from_row(row: dict[str, Any]) -> dict[str, Any] | None:
    campaign = dict((row or {}).get("campaign") or {})
    if not campaign:
        return None
    status = str(campaign.get("status") or row.get("status") or "").lower()
    if status not in lock.OPEN_STATUSES:
        return None
    campaign["status"] = status
    return campaign


async def _read_authoritative_open_campaign(self: core.LiveTrader) -> dict[str, Any] | None:
    rows = await self.repo.client.get(
        "live_trader_campaigns",
        params={
            "select": "campaign,status,updated_at",
            "symbol": f"eq.{self.symbol}",
            "status": "in.(pending,active)",
            "order": "updated_at.desc",
            "limit": "1",
        },
    )
    return _authoritative_campaign_from_row(dict(rows[0] or {})) if rows else None


async def _persist_campaign_v66(self: core.LiveTrader, campaign: dict[str, Any]) -> dict[str, Any]:
    """Persist a campaign and converge to the database winner on open-row races.

    Railway deployments can briefly overlap old and new application processes.
    The database already has a partial UNIQUE index allowing only one pending or
    active campaign per symbol. If two processes publish at the same instant, the
    losing process must not keep following its rejected in-memory campaign.
    """

    fingerprint = lock._campaign_fingerprint(campaign)
    if (
        not getattr(self, "_live_campaign_dirty", False)
        and fingerprint == getattr(self, "_live_campaign_last_persisted_fingerprint", None)
    ):
        return campaign

    try:
        await self.repo.client.upsert(
            "live_trader_campaigns",
            {
                "id": campaign.get("id"),
                "symbol": self.symbol,
                "status": campaign.get("status"),
                "side": campaign.get("side"),
                "order_type": campaign.get("order_type"),
                "entry": campaign.get("entry"),
                "stop": campaign.get("stop"),
                "target": campaign.get("target"),
                "risk_reward": campaign.get("risk_reward"),
                "confidence": campaign.get("confidence"),
                "created_at": campaign.get("created_at"),
                "expires_at": campaign.get("expires_at"),
                "triggered_at": campaign.get("triggered_at"),
                "completed_at": campaign.get("completed_at"),
                "result": campaign.get("result"),
                "campaign": campaign,
                "updated_at": core.utc_now().isoformat(),
            },
            on_conflict="id",
        )
    except Exception as exc:
        core.logger.warning("Live Trader campaign write failed; checking DB authority: %s", exc)
        if str(campaign.get("status") or "").lower() in lock.OPEN_STATUSES:
            try:
                authoritative = await _read_authoritative_open_campaign(self)
            except Exception as read_exc:
                core.logger.warning("Live Trader could not reconcile campaign after write failure: %s", read_exc)
                return campaign
            if isinstance(authoritative, dict):
                attempted_id = str(campaign.get("id") or "")
                authoritative_id = str(authoritative.get("id") or "")
                self._live_campaign = authoritative
                self._live_campaign_dirty = False
                self._live_campaign_new_v28 = False
                self._live_campaign_last_persisted_fingerprint = lock._campaign_fingerprint(authoritative)
                self._campaign_consensus_last_v66 = {
                    "version": CONSENSUS_VERSION,
                    "reconciled": True,
                    "attempted_campaign_id": attempted_id or None,
                    "authoritative_campaign_id": authoritative_id or None,
                    "reason": "database_open_campaign_won_concurrent_publication_race",
                    "at": core.utc_now().isoformat(),
                }
                core.logger.warning(
                    "Live Trader adopted authoritative DB campaign %s instead of rejected local campaign %s",
                    authoritative_id,
                    attempted_id,
                )
                return authoritative
        return campaign

    self._live_campaign_last_persisted_fingerprint = fingerprint
    self._live_campaign_dirty = False
    self._live_campaign_new_v28 = False
    return campaign


def _apply_campaign_to_state(state: dict[str, Any], campaign: dict[str, Any]) -> None:
    state["trade_campaign"] = dict(campaign)
    state["trade_lock"] = {
        "version": lock.CAMPAIGN_VERSION,
        "one_trade_at_a_time": True,
        "status": campaign.get("status"),
        "campaign_id": campaign.get("id"),
        "new_ideas_blocked": str(campaign.get("status") or "").lower() in lock.OPEN_STATUSES,
        "database_authoritative": True,
        "consensus_version": CONSENSUS_VERSION,
    }
    state["setup"] = lock._campaign_setup(campaign)
    state["trade"] = lock._campaign_trade(campaign)


async def _maybe_persist_state_v66(self: core.LiveTrader, state: dict[str, Any]) -> None:
    before = state.get("trade_campaign")
    before_id = str((before or {}).get("id") or "") if isinstance(before, dict) else ""

    # v65 injects specialist/MTF integrity and then calls the v28 persistence path.
    # v28 resolves lock._persist_campaign at runtime, so the v66 function above is
    # used without replacing any of the established learning/state wrappers.
    await _current_persist_state(self, state)

    authoritative = getattr(self, "_live_campaign", None)
    authoritative_id = str((authoritative or {}).get("id") or "") if isinstance(authoritative, dict) else ""
    if not isinstance(authoritative, dict) or not before_id or authoritative_id == before_id:
        return

    # The just-written state still described the losing in-memory candidate. Make
    # Supabase and every local/runtime view converge immediately on the DB winner.
    _apply_campaign_to_state(state, authoritative)
    v65._inject_integrity_state(self, state)
    state["campaign_consensus"] = dict(getattr(self, "_campaign_consensus_last_v66", {}) or {})
    self._latest_state = state
    await lock._original_persist_state(self, state)


def _runtime_status_v66(self: core.LiveTrader) -> dict[str, Any]:
    status = dict(_current_runtime_status(self))
    status.update(
        {
            "campaign_consensus_version": CONSENSUS_VERSION,
            "database_authoritative_open_campaign": True,
            "campaign_race_reconciliation": dict(getattr(self, "_campaign_consensus_last_v66", {}) or {}),
        }
    )
    return status


# v28 persistence resolves this module global at runtime. Patch the exact write
# point, then wrap the newest v65 state writer so a race reconciliation is also
# reflected in the state payload within the same refresh.
lock._persist_campaign = _persist_campaign_v66
core.LiveTrader._maybe_persist_state = _maybe_persist_state_v66  # type: ignore[method-assign]
core.LiveTrader.runtime_status = _runtime_status_v66  # type: ignore[method-assign]

# Maintain the repository's compatibility-alias convention for newest wrappers.
lock._maybe_persist_state_v28 = _maybe_persist_state_v66
v65._maybe_persist_state_v65 = _maybe_persist_state_v66
