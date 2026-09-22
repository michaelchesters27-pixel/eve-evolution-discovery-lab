from __future__ import annotations

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
