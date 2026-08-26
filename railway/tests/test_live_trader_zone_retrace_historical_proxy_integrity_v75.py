from app.services import live_trader_zone_retrace_historical_proxy_integrity_v75 as v75


def test_historical_m1_candidate_is_not_live_promotion() -> None:
    original = v75._prior_current_policy_contract

    def fake_contract(payload):
        return {
            "current_policy_academy": {"caught_up": True},
            "live_policy_expectancy_verified": True,
            "live_promoted_execution": "market_after_zone_confirmation",
            "promoted_execution": "market_after_zone_confirmation",
            "promotion_blocked": False,
            "live_policy_entry_geometry_verified": True,
            "live_entry_execution_edge_supported": True,
            "live_strategy_edge_proven": True,
        }

    try:
        v75._prior_current_policy_contract = fake_contract
        result = v75._current_policy_contract_v75({})
    finally:
        v75._prior_current_policy_contract = original

    assert result["historical_policy_proxy_verified"] is True
    assert result["historical_policy_proxy_candidate_execution"] == "market_after_zone_confirmation"
    assert result["historical_tick_exact"] is False
    assert result["live_promoted_execution"] is None
    assert result["promoted_execution"] is None
    assert result["live_policy_tick_exact_verified"] is False
    assert result["live_policy_entry_geometry_verified"] is False
    assert result["historical_policy_proxy_entry_geometry_verified"] is True
    assert result["historical_entry_execution_edge_supported"] is True
    assert result["live_entry_execution_edge_supported"] is False
    assert result["live_strategy_edge_proven"] is False
    assert result["forward_live_campaign_validation_required"] is True
    assert result["phase"] == "HISTORICAL M1 ENTRY CANDIDATE"
    assert result["promotion_blocked"] is True


def test_verified_proxy_without_candidate_stays_non_live() -> None:
    original = v75._prior_current_policy_contract

    def fake_contract(payload):
        return {
            "current_policy_academy": {"caught_up": True},
            "live_policy_expectancy_verified": True,
            "live_promoted_execution": None,
        }

    try:
        v75._prior_current_policy_contract = fake_contract
        result = v75._current_policy_contract_v75({})
    finally:
        v75._prior_current_policy_contract = original

    assert result["phase"] == "CURRENT-POLICY M1 PROXY VERIFIED"
    assert result["status"] == "current_policy_m1_proxy_verified_no_candidate"
    assert result["historical_entry_execution_edge_supported"] is False
    assert result["live_strategy_edge_proven"] is False


def test_scanning_proxy_is_explicitly_not_tick_exact() -> None:
    original = v75._prior_current_policy_contract

    def fake_contract(payload):
        return {
            "current_policy_academy": {"caught_up": False},
            "live_policy_expectancy_verified": False,
            "live_promoted_execution": None,
        }

    try:
        v75._prior_current_policy_contract = fake_contract
        result = v75._current_policy_contract_v75({})
    finally:
        v75._prior_current_policy_contract = original

    assert result["phase"] == "CURRENT-POLICY M1 PROXY SCANNING"
    assert result["historical_policy_proxy_resolution"] == "causal_m1_proxy"
    assert result["historical_tick_exact"] is False
    assert result["forward_live_campaign_validation_required"] is True
