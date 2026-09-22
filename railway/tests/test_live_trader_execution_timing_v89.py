from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from types import SimpleNamespace

from app.services import live_trader as core
from app.services import live_trader_audit_hardening_v26 as hardening
from app.services import live_trader_execution_timing_v89 as v89


def settings():
    return SimpleNamespace(
        live_trader_manual_delay_seconds=15,
        live_trader_cost_spread_price=0.30,
        live_trader_cost_entry_slippage_price=0.10,
        live_trader_cost_exit_slippage_price=0.10,
        live_trader_cost_commission_price_equivalent=0.07,
    )


def test_first_full_m1_starts_after_subminute_activation() -> None:
    activation = datetime(2026, 9, 22, 8, 0, 15, tzinfo=timezone.utc)
    assert hardening._first_full_m1_at_or_after(activation) == datetime(
        2026, 9, 22, 8, 1, 0, tzinfo=timezone.utc
    )


def test_exact_minute_activation_keeps_that_full_minute() -> None:
    activation = datetime(2026, 9, 22, 8, 1, 0, tzinfo=timezone.utc)
    assert hardening._first_full_m1_at_or_after(activation) == activation


def test_execution_window_excludes_pre_activation_and_partial_minute() -> None:
    observed = datetime(2026, 9, 22, 8, 0, 0, tzinfo=timezone.utc)
    row = {
        "timing_contract_version": hardening.TIMING_CONTRACT_VERSION,
        "activation_at": "2026-09-22T08:00:15+00:00",
        "execution_start_at": "2026-09-22T08:01:00+00:00",
        "market_observed_at": observed.isoformat(),
    }
    start, horizon, verified, timing = hardening._execution_window(
        row,
        fallback_observed=observed,
        horizon_minutes=60,
    )
    assert verified is True
    assert start == datetime(2026, 9, 22, 8, 1, 0, tzinfo=timezone.utc)
    assert horizon == datetime(2026, 9, 22, 9, 0, 15, tzinfo=timezone.utc)
    assert timing["pre_activation_price_events_excluded"] is True
    assert timing["partial_activation_minute_excluded"] is True


def test_new_market_campaign_is_not_triggered_before_publication_confirmation(monkeypatch) -> None:
    engine = SimpleNamespace(
        symbol="XAU/USD",
        last_tick_at="2026-09-22T08:00:00+00:00",
        last_tick_received_at="2026-09-22T08:00:05+00:00",
        _live_campaign_dirty=False,
        _live_campaign_new_v28=False,
        settings=settings(),
    )
    fixed = datetime(2026, 9, 22, 8, 0, 8, tzinfo=timezone.utc)
    monkeypatch.setattr(v89.core, "utc_now", lambda: fixed)
    trade = {
        "action": "BUY NOW",
        "side": "BUY",
        "order_type": "market",
        "entry": 100.0,
        "stop": 98.0,
        "target": 103.0,
        "risk_reward": 1.5,
        "manual_only": True,
        "automatic_order_placement": False,
    }

    campaign = v89._new_campaign_v89(engine, trade, 100.0)
    assert campaign["status"] == "active"
    assert campaign["triggered_at"] is None
    assert campaign["activation_at"] is None
    assert campaign["market_observed_at"] == "2026-09-22T08:00:00+00:00"
    assert campaign["market_received_at"] == "2026-09-22T08:00:05+00:00"

    # Even a target price cannot complete the campaign before durable activation.
    unchanged = v89._advance_campaign_v89(engine, campaign, 104.0)
    assert unchanged["status"] == "active"
    assert unchanged["result"] is None


class PatchClient:
    def __init__(self) -> None:
        self.patches: list[tuple[str, dict, dict]] = []

    async def patch(self, table: str, values: dict, *, filters: dict):
        self.patches.append((table, dict(values), dict(filters)))
        return [dict(values)]


def test_campaign_activates_only_after_successful_persistence(monkeypatch) -> None:
    async def persisted(self, campaign):
        self._live_campaign_dirty = False
        self._live_campaign_new_v28 = False
        return dict(campaign)

    monkeypatch.setattr(v89, "_current_persist_campaign", persisted)
    ticks = iter(
        [
            datetime(2026, 9, 22, 8, 0, 8, tzinfo=timezone.utc),  # publication request
            datetime(2026, 9, 22, 8, 0, 9, tzinfo=timezone.utc),  # publication confirmation / activation
        ]
    )
    monkeypatch.setattr(v89.core, "utc_now", lambda: next(ticks))

    client = PatchClient()
    engine = SimpleNamespace(
        repo=SimpleNamespace(client=client),
        _live_campaign_dirty=True,
        _live_campaign_new_v28=True,
        _live_campaign_last_persisted_fingerprint=None,
        _live_campaign=None,
        settings=settings(),
    )
    campaign = {
        "id": "c1",
        "symbol": "XAU/USD",
        "status": "active",
        "side": "BUY",
        "order_type": "market",
        "entry": 100.0,
        "stop": 98.0,
        "target": 103.0,
        "risk_reward": 1.5,
        "created_at": "2026-09-22T08:00:07+00:00",
        "triggered_at": None,
        "timing_contract_version": hardening.TIMING_CONTRACT_VERSION,
        "market_observed_at": "2026-09-22T08:00:00+00:00",
        "market_received_at": "2026-09-22T08:00:05+00:00",
        "decision_at": "2026-09-22T08:00:07+00:00",
        "publication_requested_at": None,
        "publication_confirmed_at": None,
        "activation_at": None,
    }

    result = asyncio.run(v89._persist_campaign_v89(engine, campaign))

    assert result["publication_requested_at"] == "2026-09-22T08:00:08+00:00"
    assert result["publication_confirmed_at"] == "2026-09-22T08:00:09+00:00"
    assert result["activation_at"] == "2026-09-22T08:00:24+00:00"
    assert result["triggered_at"] == result["activation_at"]
    assert client.patches
    assert client.patches[0][1]["activation_at"] == result["activation_at"]
    assert result["manual_delay_seconds"] == 15
    assert result["cost_model_version"] == "eve-live-execution-cost-model-v1"


def test_policy_lab_legacy_unverified_rows_cannot_qualify() -> None:
    from app.services import live_trader_policy_lab_v85 as v85

    rows = [
        {
            "observed_at": f"2026-09-{(index % 15) + 1:02d}T10:00:00+00:00",
            "entry_triggered": True,
            "realised_r": 1.5,
            "trade_outcome": "target",
            "trade_idea": {"policy_lab": {"policy_key": "legacy"}},
        }
        for index in range(40)
    ]
    stats = v85._policy_stats(rows)
    assert stats["legacy_unverified_resolved"] == 40
    assert len(stats["leaderboard"]) == len(v85.POLICY_KEYS)
    assert all(item["triggered"] == 0 for item in stats["leaderboard"])
    assert all(item["forward_candidate"] is False for item in stats["leaderboard"])
