from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from app.services import live_trader_context_contract as contract
from app.services import live_trader_evidence_identity as identity
from app.services import live_trader_live_context_v101 as v101
from app.services import live_trader_policy_lab_v85 as v85
from app.services import live_trader_zone_retrace_current_policy_throughput_v102 as v102


def _candle(stamp: datetime, price: float) -> dict:
    return {
        "candle_time": stamp.isoformat(),
        "open": price,
        "high": price + 1.0,
        "low": price - 1.0,
        "close": price + 0.25,
        "volume": 1.0,
    }


class FakeSource:
    def __init__(self, rows_by_interval: dict[str, list[dict]]) -> None:
        self.rows_by_interval = rows_by_interval
        self.settings = SimpleNamespace(source_symbol="XAU/USD")

    async def fetch_candles_page(
        self,
        symbol: str,
        interval: str,
        *,
        after: str | None = None,
        date_from: str | None = None,
        date_to: str | None = None,
        limit: int = 1000,
    ) -> list[dict]:
        rows = list(self.rows_by_interval.get(interval) or [])
        after_dt = v101._parse_time(after)
        from_dt = v101._parse_time(date_from)
        to_dt = v101._parse_time(date_to)
        result = []
        for row in rows:
            stamp = v101._parse_time(row.get("candle_time"))
            if stamp is None:
                continue
            if after_dt is not None and stamp <= after_dt:
                continue
            if after_dt is None and from_dt is not None and stamp < from_dt:
                continue
            if to_dt is not None and stamp > to_dt:
                continue
            result.append(dict(row))
        return result[:limit]


def test_completed_m5_cutoff_uses_last_fully_closed_bar() -> None:
    now = datetime(2026, 9, 25, 8, 31, 17, tzinfo=timezone.utc)
    assert v101._completed_m5_start(now) == datetime(2026, 9, 25, 8, 25, tzinfo=timezone.utc)


def test_live_context_fails_closed_when_context_is_over_ten_minutes_stale() -> None:
    original = v101._current_bias

    def fake_bias(self, latest):
        return {
            "overall": "bearish",
            "raw_score": -0.8,
            "confidence": 85,
            "data_quality": {},
        }, -0.8

    dummy = SimpleNamespace(
        last_tick_at="2026-09-25T08:31:00+00:00",
        _feed_is_fresh=lambda: True,
    )
    latest = {
        "candle_time": "2026-09-25T08:00:00+00:00",
        "mtf_context": {"decision_time": "2026-09-25T08:05:00+00:00"},
    }
    try:
        v101._current_bias = fake_bias
        bias, score = v101._bias_v101(dummy, latest)
    finally:
        v101._current_bias = original

    assert bias["overall"] == "neutral"
    assert score == 0.0
    assert bias["data_quality"]["live_context_stale"] is True
    assert bias["data_quality"]["trade_bias_blocked"] is True


def test_live_context_does_not_block_a_fresh_completed_m5() -> None:
    original = v101._current_bias

    def fake_bias(self, latest):
        return {
            "overall": "bullish",
            "raw_score": 0.7,
            "confidence": 80,
            "data_quality": {},
        }, 0.7

    dummy = SimpleNamespace(
        last_tick_at="2026-09-25T08:31:00+00:00",
        _feed_is_fresh=lambda: True,
    )
    latest = {
        "candle_time": "2026-09-25T08:25:00+00:00",
        "mtf_context": {"decision_time": "2026-09-25T08:30:00+00:00"},
    }
    try:
        v101._current_bias = fake_bias
        bias, score = v101._bias_v101(dummy, latest)
    finally:
        v101._current_bias = original

    assert bias["overall"] == "bullish"
    assert score == 0.7
    assert bias["data_quality"]["live_context_stale"] is False
    assert bias["data_quality"].get("trade_bias_blocked") is not True


def test_overlay_builds_missing_completed_m5_without_persisting_heavy_fabric() -> None:
    start = datetime(2026, 9, 24, 7, 25, tzinfo=timezone.utc)
    seed = [_candle(start + timedelta(minutes=5 * index), 4200.0 + index * 0.1) for index in range(300)]
    # Seed ends at 2026-09-25 08:20 UTC.
    fresh_stamp = start + timedelta(minutes=5 * 300)
    assert fresh_stamp == datetime(2026, 9, 25, 8, 25, tzinfo=timezone.utc)

    rows = {
        "5min": [_candle(fresh_stamp, 4230.0)],
        "1min": [_candle(fresh_stamp + timedelta(minutes=index), 4230.0 + index * 0.05) for index in range(5)],
        "15min": [_candle(datetime(2026, 9, 25, 8, 0, tzinfo=timezone.utc), 4228.0)],
        "1h": [_candle(datetime(2026, 9, 25, 7, 0, tzinfo=timezone.utc), 4220.0)],
        "4h": [_candle(datetime(2026, 9, 25, 4, 0, tzinfo=timezone.utc), 4210.0)],
        "1day": [_candle(datetime(2026, 9, 25, 0, 0, tzinfo=timezone.utc), 4200.0)],
    }
    dummy = SimpleNamespace(
        symbol="XAU/USD",
        settings=SimpleNamespace(source_symbol="XAU/USD"),
        _live_context_source_v101=FakeSource(rows),
    )
    reference = datetime(2026, 9, 25, 8, 31, tzinfo=timezone.utc)

    merged, diagnostic = asyncio.run(
        v101._overlay_fresh_rows(
            dummy,
            seed,
            reference,
            v101._latest_row_time(seed),
        )
    )

    assert merged[-1]["candle_time"] == fresh_stamp.isoformat()
    assert merged[-1]["session"] == "london"
    assert merged[-1]["mtf_context"]["decision_time"] == "2026-09-25T08:30:00+00:00"
    assert diagnostic["overlay_rows"] == 1
    assert diagnostic["fresh"] is True
    assert diagnostic["persistent_research_fabric_required_for_live_freshness"] is False


def test_production_and_policy_lab_contracts_include_fresh_context_identity() -> None:
    production = identity.production_policy_definition()
    lab = v85._policy_definition("directional_momentum_confirmation")

    assert identity.PRODUCTION_POLICY_CONTRACT_VERSION == "eve-live-production-policy-contract-v2-fresh-context"
    assert production["live_context_contract"]["runtime_version"] == contract.LIVE_CONTEXT_VERSION
    assert production["live_context_contract"]["fail_closed_on_stale_live_context"] is True
    assert lab["live_context_contract"]["runtime_version"] == contract.LIVE_CONTEXT_VERSION


def test_bounded_current_policy_stage_runs_multiple_durable_batches() -> None:
    class Worker:
        def __init__(self) -> None:
            self.rows = 0
            self.cursor = 0

        async def _state(self):
            return {
                "rows_scanned": self.rows,
                "opportunities_found": 0,
                "cursor_time": str(self.cursor),
                "caught_up": self.rows >= 2700,
            }

        async def run_cycle(self):
            self.rows += 900
            self.cursor += 1
            return True

    original_rows = v102.BOUNDED_ROW_BUDGET
    original_seconds = v102.BOUNDED_TIME_BUDGET_SECONDS
    try:
        v102.BOUNDED_ROW_BUDGET = 2700
        v102.BOUNDED_TIME_BUDGET_SECONDS = 30.0
        result = asyncio.run(v102.run_bounded_stage(Worker()))
    finally:
        v102.BOUNDED_ROW_BUDGET = original_rows
        v102.BOUNDED_TIME_BUDGET_SECONDS = original_seconds

    assert result["rows"] == 2700
    assert result["batches"] == 3
    assert result["caught_up"] is True
    assert result["durable_checkpoint_each_batch"] is True
    assert result["trading_rules_changed"] is False
