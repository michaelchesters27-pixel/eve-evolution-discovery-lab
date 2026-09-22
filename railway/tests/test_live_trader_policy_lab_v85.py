from __future__ import annotations

import asyncio
from datetime import datetime, timezone

from app.services import live_trader_policy_lab_v85 as v85


def _state() -> dict:
    return {
        "symbol": "XAU/USD",
        "price": 4300.0,
        "market": {"atr": 10.0, "session": "london"},
        "liquidity": {"primary_event": {}},
        "bias": {
            "overall": "bullish",
            "confidence": 72,
            "panel_bias_version": "eve-live-bias-v2.5-structural-panel",
            "data_quality": {"critical_stale": [], "trade_bias_blocked": False},
            "timeframes": {
                "D1": {"direction": "bullish", "method": "multi_candle_structure"},
                "H4": {"direction": "bullish", "method": "multi_candle_structure"},
                "H1": {"direction": "bullish", "method": "multi_candle_structure"},
                "M30": {"direction": "neutral", "method": "multi_candle_structure"},
                "M15": {"direction": "bullish", "method": "multi_candle_structure"},
                "M5": {"direction": "bullish", "method": "multi_candle_structure"},
            },
        },
        "zones": {
            "demand": [
                {
                    "low": 4278.0,
                    "high": 4285.0,
                    "quality": 82,
                    "distance_atr": 1.5,
                    "rank": 1,
                    "zone_role": "H1_BACKED_M5_EXECUTION",
                }
            ],
            "supply": [],
        },
        "setup_family": "family-a",
        "setup_signature": "family-a",
    }


def test_policy_lab_runs_parallel_research_without_publication_authority() -> None:
    candidates = v85._policy_candidates(_state())
    keys = {item["policy_lab"]["policy_key"] for item in candidates}
    assert "directional_quality_market" in keys
    assert "clear_bias_market" in keys
    assert "clear_bias_zone_3_5atr" in keys
    assert "clear_bias_zone_2_5atr" in keys
    assert "m5_m15_zone_3_5atr" in keys
    assert "quality_zone_touch_limit" in keys
    assert "directional_momentum_confirmation" in keys
    for item in candidates:
        assert item["shadow_only"] is True
        assert item["automatic_order_placement"] is False
        assert item["policy_lab"]["publication_authority"] is False
        assert item["policy_lab"]["live_gate_unchanged"] is True


def test_policy_lab_comparison_does_not_require_live_zone_distance() -> None:
    state = _state()
    state["zones"]["demand"][0]["distance_atr"] = 5.0
    candidates = v85._policy_candidates(state)
    keys = {item["policy_lab"]["policy_key"] for item in candidates}
    assert "directional_quality_market" in keys
    assert "clear_bias_market" in keys
    assert "clear_bias_zone_3_5atr" not in keys
    assert "clear_bias_zone_2_5atr" not in keys


def test_policy_lab_30_correlated_rows_are_only_a_screening_flag() -> None:
    rows = []
    for index in range(30):
        rows.append(
            {
                "observed_at": f"2026-09-{(index % 15) + 1:02d}T10:00:00+00:00",
                "entry_triggered": True,
                "realised_r": 1.5 if index % 2 == 0 else -1.0,
                "gross_realised_r": 1.5 if index % 2 == 0 else -1.0,
                "net_realised_r": 1.5 if index % 2 == 0 else -1.0,
                "cost_model_version": v85.cost_model.COST_MODEL_VERSION,
                "trade_outcome": "target" if index % 2 == 0 else "stop",
                "timing_contract_version": v85.hardening.TIMING_CONTRACT_VERSION,
                "trade_idea": {"policy_lab": {"policy_key": "directional_quality_market"}},
            }
        )
    stats = v85._policy_stats(rows)
    leader = next(item for item in stats["leaderboard"] if item["policy_key"] == "directional_quality_market")
    assert leader["triggered"] == 30
    assert leader["expectancy_r"] == 0.25
    assert leader["screening_pass_30_and_mean_only"] is True
    assert leader["forward_candidate"] is False
    assert "minimum_independent_days" in leader["failed_quality_gates"]
    assert stats["automatic_promotion"] is False
    assert stats["fresh_confirmation_required"] is True


def test_policy_lab_requires_clustered_uncertainty_and_independent_weeks() -> None:
    rows = []
    for index in range(30):
        day = index + 1
        rows.append(
            {
                "observed_at": f"2026-09-{day:02d}T10:00:00+00:00",
                "entry_triggered": True,
                "realised_r": 0.4,
                "gross_realised_r": 0.4,
                "net_realised_r": 0.3,
                "cost_model_version": v85.cost_model.COST_MODEL_VERSION,
                "trade_outcome": "expired_win",
                "timing_contract_version": v85.hardening.TIMING_CONTRACT_VERSION,
                "trade_idea": {"policy_lab": {"policy_key": "directional_quality_market"}},
            }
        )
    stats = v85._policy_stats(rows)
    candidate = next(item for item in stats["leaderboard"] if item["policy_key"] == "directional_quality_market")
    assert candidate["independent_days"] == 30
    assert candidate["independent_weeks"] >= 4
    assert candidate["multiplicity_adjusted_one_sided_lower_bound_r"] > 0
    assert candidate["fresh_confirmation_candidate"] is True
    assert candidate["forward_candidate"] is True
    assert candidate["selection_cohort_may_confirm_winner"] is False



def _complete_summary_payload(triggered: int = 6001) -> tuple[dict, dict[str, str]]:
    cohorts = {key: f"coh_{index}" for index, key in enumerate(v85.POLICY_KEYS)}
    daily = []
    remaining = triggered
    for day in range(1, 31):
        count = min(201 if day == 1 else 200, remaining)
        remaining -= count
        daily.append(
            {
                "day": f"2026-08-{day:02d}",
                "triggered": count,
                "wins": count,
                "losses": 0,
                "breakeven": 0,
                "gross_r": round(count * 0.2, 6),
                "net_r": round(count * 0.2, 6),
            }
        )
    assert remaining == 0
    rows = []
    for key in v85.POLICY_KEYS:
        cohort_id = cohorts[key]
        if key == "directional_quality_market":
            rows.append(
                {
                    "cohort_id": cohort_id,
                    "resolved": 7000,
                    "triggered": triggered,
                    "wins": triggered,
                    "losses": 0,
                    "breakeven": 0,
                    "total_gross_r": round(triggered * 0.2, 6),
                    "total_net_r": round(triggered * 0.2, 6),
                    "max_drawdown_net_r": 0.0,
                    "daily": daily,
                }
            )
        else:
            rows.append(
                {
                    "cohort_id": cohort_id,
                    "resolved": 0,
                    "triggered": 0,
                    "wins": 0,
                    "losses": 0,
                    "breakeven": 0,
                    "total_gross_r": 0.0,
                    "total_net_r": 0.0,
                    "max_drawdown_net_r": 0.0,
                    "daily": [],
                }
            )
    return (
        {
            "version": v85.SUMMARY_VERSION,
            "summary_scope": "complete_current_cohorts",
            "complete": True,
            "rolling": False,
            "api_row_cap_applies": False,
            "source": "server_side_sql_aggregation",
            "cohorts": rows,
            "excluded_unverified_resolved": 123,
            "generated_at": "2026-09-22T10:30:00+00:00",
        },
        cohorts,
    )


def test_complete_summary_does_not_freeze_at_old_5000_row_prefix() -> None:
    payload, cohorts = _complete_summary_payload(6001)
    stats = v85._policy_stats_from_complete_summary(payload, cohorts)
    target = next(item for item in stats["leaderboard"] if item["policy_key"] == "directional_quality_market")

    assert target["triggered"] == 6001
    assert target["resolved"] == 7000
    assert target["summary_complete"] is True
    assert target["summary_api_row_cap_applies"] is False
    assert stats["summary_completeness"]["complete"] is True
    assert stats["summary_completeness"]["rolling"] is False
    assert stats["legacy_unverified_resolved"] == 123


def test_complete_summary_fails_closed_when_a_current_cohort_is_missing() -> None:
    payload, cohorts = _complete_summary_payload(6001)
    payload["cohorts"] = payload["cohorts"][:-1]
    try:
        v85._policy_stats_from_complete_summary(payload, cohorts)
    except RuntimeError as exc:
        assert "cohort mismatch" in str(exc)
    else:
        raise AssertionError("Missing current cohort must not silently produce an incomplete leaderboard")


def test_daily_sql_aggregate_preserves_clustered_quality_math() -> None:
    payload, cohorts = _complete_summary_payload(6001)
    aggregate = next(
        item for item in payload["cohorts"]
        if item["cohort_id"] == cohorts["directional_quality_market"]
    )
    assessment = v85.quality.evaluate_policy_lab_daily_summary(
        aggregate["daily"],
        policy_key="directional_quality_market",
        cohort_id=aggregate["cohort_id"],
    )
    assert assessment["triggered"] == 6001
    assert assessment["independent_days"] == 30
    assert assessment["independent_weeks"] >= 4
    assert assessment["fresh_confirmation_candidate"] is True



class _PolicyResolverClient:
    def __init__(self, row: dict) -> None:
        self.row = row
        self.patched = False

    async def get(self, _table: str, *, params: dict | None = None, **_kwargs):
        return [dict(self.row)]

    async def patch(self, _table: str, _values: dict, *, filters: dict):
        self.patched = True
        return []


class _PolicyResolverSettings:
    live_trader_learning_horizon_minutes = 60


class _PolicyResolverEngine:
    def __init__(self, row: dict) -> None:
        self.repo = type("Repo", (), {"client": _PolicyResolverClient(row)})()
        self.settings = _PolicyResolverSettings()
        self._policy_lab_last_resolution_v85 = None


def test_policy_lab_resolver_never_scores_unactivated_current_timing(monkeypatch) -> None:
    row = {
        "id": "policy-1",
        "observed_at": "2026-09-22T08:00:00+00:00",
        "price": 4300.0,
        "horizon_minutes": 60,
        "market_state": {},
        "trade_idea": {
            "order_type": "buy_limit",
            "side": "BUY",
            "entry": 4290.0,
            "stop": 4280.0,
            "target": 4305.0,
            "policy_lab": {"policy_key": "directional_quality_market"},
        },
        "market_observed_at": "2026-09-22T08:00:00+00:00",
        "market_received_at": "2026-09-22T08:00:01+00:00",
        "decision_at": "2026-09-22T08:00:02+00:00",
        "publication_requested_at": "2026-09-22T08:00:03+00:00",
        "publication_confirmed_at": None,
        "activation_at": None,
        "execution_start_at": None,
        "timing_contract_version": v85.hardening.TIMING_CONTRACT_VERSION,
    }
    engine = _PolicyResolverEngine(row)
    monkeypatch.setattr(
        v85.core,
        "utc_now",
        lambda: datetime(2026, 9, 22, 10, 0, tzinfo=timezone.utc),
    )
    source_called = False

    async def forbidden_source(*_args, **_kwargs):
        nonlocal source_called
        source_called = True
        return []

    monkeypatch.setattr(v85.hardening, "_source_m1_rows", forbidden_source)
    result = asyncio.run(v85._resolve_policy_outcomes(engine))

    assert result["resolved"] == 0
    assert source_called is False
    assert engine.repo.client.patched is False
