from __future__ import annotations

import hashlib
from datetime import timedelta
from typing import Any

from app.services import live_trader as core
from app.services import live_trader_audit_hardening_v26 as hardening
from app.services import live_trader_campaign_consensus_v66 as consensus
from app.services import live_trader_execution_cost_model as cost_model
from app.services import live_trader_trade_lock_v28 as lock

TIMING_CONTRACT_VERSION = hardening.TIMING_CONTRACT_VERSION
_current_new_campaign = lock._new_campaign
_current_advance_campaign = lock._advance_campaign
_current_campaign_trade = lock._campaign_trade
_current_campaign_fingerprint = lock._campaign_fingerprint
_current_persist_campaign = consensus._persist_campaign_v66
_current_runtime_status = core.LiveTrader.runtime_status


def _new_campaign_v89(self: core.LiveTrader, trade: dict[str, Any], price: float) -> dict[str, Any]:
    campaign = dict(_current_new_campaign(self, trade, price))
    now = core.utc_now()
    campaign["timing_contract_version"] = TIMING_CONTRACT_VERSION
    campaign["market_observed_at"] = getattr(self, "last_tick_at", None)
    campaign["market_received_at"] = getattr(self, "last_tick_received_at", None)
    campaign["decision_at"] = now.isoformat()
    campaign["publication_requested_at"] = None
    campaign["publication_confirmed_at"] = None
    campaign["activation_at"] = None
    campaign["activation_price"] = None
    campaign["pre_activation_price_events_eligible"] = False
    campaign["execution_cost_model"] = cost_model.profile_from_settings(self.settings)
    campaign["cost_model_version"] = cost_model.COST_MODEL_VERSION
    campaign["manual_delay_seconds"] = int(campaign["execution_cost_model"].get("manual_delay_seconds") or 0)
    published = dict(campaign.get("published_trade") or {})
    published["execution_cost_model"] = dict(campaign["execution_cost_model"])
    published["cost_model_version"] = cost_model.COST_MODEL_VERSION
    campaign["published_trade"] = published

    # A market idea is not executable merely because the decision engine created
    # it. The trigger becomes valid only after the campaign write is confirmed.
    if str(campaign.get("order_type") or "").lower() == "market":
        campaign["triggered_at"] = None

    self._live_campaign_dirty = True
    self._live_campaign_new_v28 = True
    return campaign


def _advance_campaign_v89(
    self: core.LiveTrader,
    campaign: dict[str, Any],
    price: float,
    *,
    allow_price_events: bool = True,
) -> dict[str, Any] | None:
    if str(campaign.get("timing_contract_version") or "") == TIMING_CONTRACT_VERSION:
        activation = lock._parse_time(campaign.get("activation_at"))
        if activation is None or core.utc_now() < activation:
            # Do not expire, invalidate, trigger, hit TP or hit SL before the
            # persisted publication plus the declared manual execution delay.
            return campaign
        if allow_price_events and campaign.get("activation_price") is None and price > 0:
            campaign["activation_price"] = round(price, 3)
            campaign["activation_price_recorded_at"] = core.utc_now().isoformat()
            self._live_campaign_dirty = True
    advanced = _current_advance_campaign(self, campaign, price, allow_price_events=allow_price_events)
    if isinstance(advanced, dict) and str(advanced.get("status") or "").lower() in {"won", "lost", "invalidated", "expired"}:
        gross_r = cost_model.campaign_gross_r(advanced)
        costed = cost_model.campaign_cost_result(advanced, gross_r)
        advanced["gross_realised_r"] = costed.get("gross_realised_r")
        advanced["estimated_cost_r"] = costed.get("estimated_cost_r")
        advanced["net_realised_r"] = costed.get("net_realised_r")
        advanced["execution_costs"] = costed.get("execution_costs")
        advanced["cost_model_version"] = costed.get("cost_model_version")
        self._live_campaign_dirty = True
    return advanced


def _campaign_fingerprint_v89(campaign: dict[str, Any]) -> str:
    raw = "|".join(
        [
            _current_campaign_fingerprint(campaign),
            str(campaign.get("timing_contract_version") or ""),
            str(campaign.get("publication_requested_at") or ""),
            str(campaign.get("publication_confirmed_at") or ""),
            str(campaign.get("activation_at") or ""),
            str(campaign.get("activation_price") or ""),
            str(campaign.get("cost_model_version") or ""),
        ]
    )
    return hashlib.sha1(raw.encode()).hexdigest()


def _campaign_trade_v89(campaign: dict[str, Any]) -> dict[str, Any]:
    trade = dict(_current_campaign_trade(campaign))
    trade.update(
        {
            "timing_contract_version": campaign.get("timing_contract_version"),
            "market_observed_at": campaign.get("market_observed_at"),
            "market_received_at": campaign.get("market_received_at"),
            "decision_at": campaign.get("decision_at"),
            "publication_requested_at": campaign.get("publication_requested_at"),
            "publication_confirmed_at": campaign.get("publication_confirmed_at"),
            "activation_at": campaign.get("activation_at"),
            "activation_price": campaign.get("activation_price"),
            "manual_delay_seconds": campaign.get("manual_delay_seconds"),
            "cost_model_version": campaign.get("cost_model_version"),
            "execution_cost_model": dict(campaign.get("execution_cost_model") or {}),
            "pre_activation_price_events_eligible": False,
        }
    )
    return trade


async def _persist_campaign_v89(self: core.LiveTrader, campaign: dict[str, Any]) -> dict[str, Any]:
    if str(campaign.get("timing_contract_version") or "") != TIMING_CONTRACT_VERSION:
        return await _current_persist_campaign(self, campaign)

    candidate = dict(campaign)
    if not candidate.get("publication_requested_at"):
        candidate["publication_requested_at"] = core.utc_now().isoformat()
        self._live_campaign = candidate
        self._live_campaign_dirty = True

    persisted = await _current_persist_campaign(self, candidate)
    persisted = dict(persisted or candidate)

    # A failed write deliberately remains dirty in v66. It is not activated.
    if getattr(self, "_live_campaign_dirty", False):
        return persisted

    # A deployment race may have caused us to adopt a different authoritative
    # campaign. Only activate a campaign that belongs to this timing contract.
    if str(persisted.get("timing_contract_version") or "") != TIMING_CONTRACT_VERSION:
        return persisted
    if persisted.get("publication_confirmed_at") and persisted.get("activation_at"):
        return persisted

    confirmed = core.utc_now()
    final = dict(persisted)
    execution_cost_profile = dict(final.get("execution_cost_model") or cost_model.profile_from_settings(self.settings))
    delay_seconds = int(execution_cost_profile.get("manual_delay_seconds") or 0)
    activation = confirmed + timedelta(seconds=max(0, delay_seconds))
    final["publication_confirmed_at"] = confirmed.isoformat()
    final["activation_at"] = activation.isoformat()
    final["manual_delay_seconds"] = delay_seconds
    final["execution_cost_model"] = execution_cost_profile
    final["cost_model_version"] = cost_model.COST_MODEL_VERSION
    final["pre_activation_price_events_eligible"] = False

    order_type = str(final.get("order_type") or "").lower()
    status = str(final.get("status") or "").lower()
    if status == "pending":
        final["expires_at"] = (activation + timedelta(minutes=lock.PENDING_EXPIRY_MINUTES)).isoformat()
    if order_type == "market" and status == "active":
        final["triggered_at"] = activation.isoformat()

    try:
        await self.repo.client.patch(
            "live_trader_campaigns",
            {
                "market_observed_at": final.get("market_observed_at"),
                "market_received_at": final.get("market_received_at"),
                "decision_at": final.get("decision_at"),
                "publication_requested_at": final.get("publication_requested_at"),
                "publication_confirmed_at": final.get("publication_confirmed_at"),
                "activation_at": final.get("activation_at"),
                "timing_contract_version": TIMING_CONTRACT_VERSION,
                "cost_model_version": cost_model.COST_MODEL_VERSION,
                "execution_cost_model": execution_cost_profile,
                "manual_delay_seconds": delay_seconds,
                "activation_price": final.get("activation_price"),
                "expires_at": final.get("expires_at"),
                "triggered_at": final.get("triggered_at"),
                "campaign": final,
                "updated_at": confirmed.isoformat(),
            },
            filters={"id": f"eq.{final.get('id')}"},
        )
    except Exception as exc:
        # The first write may exist, but the campaign remains non-executable until
        # the activation patch is durably stored.
        core.logger.warning("Live Trader timing activation write failed: %s", exc)
        self._live_campaign = candidate
        self._live_campaign_dirty = True
        return candidate

    self._live_campaign = final
    self._live_campaign_dirty = False
    self._live_campaign_new_v28 = False
    self._live_campaign_last_persisted_fingerprint = _campaign_fingerprint_v89(final)
    return final


def _campaign_publication_is_current_v89(campaign: dict[str, Any], state: dict[str, Any]) -> bool:
    if str(campaign.get("timing_contract_version") or "") != TIMING_CONTRACT_VERSION:
        return _current_campaign_publication_is_current(campaign, state)
    activation = lock._parse_time(campaign.get("activation_at"))
    observed = hardening._market_observation_time(state)
    if activation is None or observed is None:
        return False
    # The market observation is allowed to precede activation, but it must be a
    # fresh input to the decision rather than an old context reconstructed later.
    return abs((activation - observed).total_seconds()) <= 120.0


def _runtime_status_v89(self: core.LiveTrader) -> dict[str, Any]:
    status = dict(_current_runtime_status(self))
    status.update(
        {
            "execution_timing_contract_version": TIMING_CONTRACT_VERSION,
            "campaign_activation_requires_persisted_publication": True,
            "pre_publication_price_credit_allowed": False,
            "forward_replay_starts_at_first_full_m1_after_activation": True,
            "manual_delay_seconds": int(getattr(self.settings, "live_trader_manual_delay_seconds", 15)),
            "execution_cost_model_version": cost_model.COST_MODEL_VERSION,
        }
    )
    return status


lock._new_campaign = _new_campaign_v89
lock._advance_campaign = _advance_campaign_v89
lock._campaign_fingerprint = _campaign_fingerprint_v89
lock._campaign_trade = _campaign_trade_v89
lock._persist_campaign = _persist_campaign_v89
consensus._persist_campaign_v66 = _persist_campaign_v89

# v39 resolves this helper dynamically when recording campaign-level forward
# evidence. Import locally to avoid changing the established wrapper chain.
from app.services import live_trader_execution_integrity_v39 as integrity  # noqa: E402

_current_campaign_publication_is_current = integrity._campaign_publication_is_current
integrity._campaign_publication_is_current = _campaign_publication_is_current_v89
core.LiveTrader.runtime_status = _runtime_status_v89  # type: ignore[method-assign]
