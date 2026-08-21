from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone

from app.services import live_trader as core
from app.services import live_trader_audit_hardening_v26 as hardening


class FakeClient:
    def __init__(self) -> None:
        self.inserted: list[dict] = []
        self.rows: list[dict] = []

    async def get(self, _table: str, *, params: dict | None = None, **_kwargs):
        return list(self.rows)

    async def insert(self, _table: str, payload: dict, **_kwargs):
        self.inserted.append(payload)
        return []


class FakeRepo:
    def __init__(self) -> None:
        self.client = FakeClient()


class FakeSettings:
    live_trader_learning_horizon_minutes = 60


def state(*, connected: bool = True) -> dict:
    return {
        "symbol": "XAU/USD",
        "as_of": "2026-08-21T12:43:00+00:00",
        "price": 4580.0,
        "feed": {"connected": connected, "last_tick_at": "2026-08-21T12:43:00+00:00"},
        "bias": {"overall": "bearish", "confidence": 64},
        "market": {"session": "new_york", "regime": "trend_down", "atr": 6.0},
        "liquidity": {},
        "zones": {},
        "trade": {
            "action": "SELL STOP",
            "order_type": "sell_stop",
            "side": "SELL",
            "entry": 4578.0,
            "stop": 4586.0,
            "target": 4562.0,
            "risk_reward": 2.0,
        },
        "setup_family": "family-abc",
        "setup_signature": "family-abc",
        "setup_family_descriptor": {"bias": "bearish", "session": "new_york"},
        "opinion": "shadow",
        "learning_governor": {"decision": "insufficient_evidence"},
    }


def trader() -> core.LiveTrader:
    item = core.LiveTrader.__new__(core.LiveTrader)
    item.repo = FakeRepo()
    item.settings = FakeSettings()
    item.symbol = "XAU/USD"
    item._last_recorded_signature = None
    item._last_opinion_at = None
    item._last_resolution_at = None
    return item


def test_market_time_not_wall_clock_is_learning_clock(monkeypatch) -> None:
    engine = trader()
    monkeypatch.setattr(hardening.core, "utc_now", lambda: datetime(2026, 8, 21, 12, 43, 7, tzinfo=timezone.utc))

    asyncio.run(hardening._record_v26(engine, state()))

    assert len(engine.repo.client.inserted) == 1
    payload = engine.repo.client.inserted[0]
    assert payload["observed_at"] == "2026-08-21T12:43:00+00:00"
    assert payload["learning_version"] == hardening.LEARNING_NAMESPACE
    clock = payload["market_state"]["learning_observation"]
    assert clock["market_observed_at"] == "2026-08-21T12:43:00+00:00"
    assert clock["recorded_at"] == "2026-08-21T12:43:07+00:00"


def test_stale_or_disconnected_feed_cannot_create_learning_sample(monkeypatch) -> None:
    engine = trader()
    monkeypatch.setattr(hardening.core, "utc_now", lambda: datetime(2026, 8, 21, 12, 43, 7, tzinfo=timezone.utc))

    asyncio.run(hardening._record_v26(engine, state(connected=False)))

    assert engine.repo.client.inserted == []


def m1(minute: int, close: float = 100.0) -> dict:
    return {
        "candle_time": datetime(2026, 8, 21, 10, minute, tzinfo=timezone.utc).isoformat(),
        "open": close,
        "high": close + 0.5,
        "low": close - 0.5,
        "close": close,
    }


def test_aligned_observation_uses_first_full_m1_bar() -> None:
    observed = datetime(2026, 8, 21, 10, 0, tzinfo=timezone.utc)
    horizon = observed + timedelta(minutes=3)
    path = hardening._causal_m1_path([m1(0), m1(1), m1(2)], observed, horizon)

    assert len(path["bars"]) == 3
    assert path["initial_gap_seconds"] == 0.0
    assert path["gap_count"] == 0
    assert path["endpoint_time"] == horizon


def test_partial_pre_observation_m1_is_excluded_and_flagged() -> None:
    observed = datetime(2026, 8, 21, 10, 0, 30, tzinfo=timezone.utc)
    horizon = datetime(2026, 8, 21, 10, 3, 0, tzinfo=timezone.utc)
    path = hardening._causal_m1_path([m1(0), m1(1), m1(2)], observed, horizon)

    assert [row["candle_time"] for row in path["bars"]] == [m1(1)["candle_time"], m1(2)["candle_time"]]
    assert path["initial_gap_seconds"] == 30.0


def test_missing_m1_minute_is_detected() -> None:
    observed = datetime(2026, 8, 21, 10, 0, tzinfo=timezone.utc)
    horizon = observed + timedelta(minutes=3)
    path = hardening._causal_m1_path([m1(0), m1(2)], observed, horizon)

    assert path["gap_count"] == 1


class FreshnessProbe:
    def __init__(self, fresh: bool) -> None:
        self.fresh = fresh

    def _feed_is_fresh(self) -> bool:
        return self.fresh


def test_socket_respects_configured_feed_freshness_not_old_30_second_rule() -> None:
    connected_at = datetime(2026, 8, 21, 10, 0, tzinfo=timezone.utc)
    after_60_seconds = connected_at + timedelta(seconds=60)

    assert hardening._socket_should_reconnect(FreshnessProbe(True), connected_at, now=after_60_seconds) is False
    assert hardening._socket_should_reconnect(FreshnessProbe(False), connected_at, now=after_60_seconds) is True


def test_governor_still_runs_with_stable_namespace() -> None:
    engine = trader()
    pending = state()
    engine._learning_governor_pending_state = pending
    engine._learning_descriptor_v22 = {}

    learning = asyncio.run(hardening._calibration_v26(engine, "family-abc"))

    assert learning["learning_version"] == hardening.LEARNING_NAMESPACE
    assert learning["active"] is False
    assert pending["learning_governor"]["decision"] == "insufficient_evidence"


def test_runtime_is_actually_patched_to_hardened_loop() -> None:
    assert core.LiveTrader.run_forever is hardening._run_forever_v26
    assert core.LiveTrader._maybe_record_opinion is hardening._record_v26
    assert core.LiveTrader._maybe_resolve_opinions is hardening._resolve_v26
