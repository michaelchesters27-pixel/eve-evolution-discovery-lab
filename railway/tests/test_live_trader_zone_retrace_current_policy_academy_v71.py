from app.services import live_trader_zone_retrace_current_policy_academy_v71 as v71


def academy_state(*, caught_up: bool, promoted: bool, opportunities: int = 100, scorable: int = 98, triggered: int = 50, expectancy: float = 0.15) -> dict:
    return {
        "academy_version": v71.ACADEMY_VERSION,
        "status": "caught_up_promoted" if caught_up and promoted else "scanning",
        "rows_scanned": 10000,
        "opportunities_found": opportunities,
        "scorable_opportunities": scorable,
        "unscorable_opportunities": opportunities - scorable,
        "triggered": triggered,
        "wins": 30,
        "losses": 20,
        "breakeven": 0,
        "total_r": expectancy * scorable,
        "expectancy_per_opportunity_r": expectancy,
        "expectancy_per_triggered_r": 0.3,
        "trigger_rate": triggered / scorable,
        "caught_up": caught_up,
        "promoted": promoted,
    }


def test_legacy_compatibility_replay_cannot_promote_current_live_policy() -> None:
    payload = {
        "execution_evidence": {"market": {"opportunities": 173, "expectancy_per_opportunity_r": 0.1261}},
        "best_execution": "market",
        "promoted_execution": "market",
        "live_policy_replay": {
            "completed": True,
            "promoted": True,
            "eligible_episodes": 173,
            "scorable_episodes": 173,
        },
    }

    specialist = v71._current_policy_contract(payload)

    assert specialist["compatibility_replay_authoritative_for_promotion"] is False
    assert specialist["live_promotion_authority"] == v71.ACADEMY_VERSION
    assert specialist["live_promoted_execution"] is None
    assert specialist["promoted_execution"] is None
    assert specialist["promotion_blocked"] is True


def test_current_policy_academy_can_promote_only_when_caught_up_and_verified() -> None:
    payload = {
        "execution_evidence": {"market": {"opportunities": 173}},
        "current_policy_academy": academy_state(caught_up=True, promoted=True),
    }

    specialist = v71._current_policy_contract(payload)

    assert specialist["live_policy_expectancy_verified"] is True
    assert specialist["live_promoted_execution"] == "market_after_zone_confirmation"
    assert specialist["promoted_execution"] == "market_after_zone_confirmation"
    assert specialist["promotion_blocked"] is False
    assert specialist["live_entry_execution_edge_supported"] is True
    assert specialist["live_strategy_edge_proven"] is False


def test_current_policy_academy_cannot_promote_before_archive_catchup() -> None:
    payload = {
        "execution_evidence": {"market": {"opportunities": 173}},
        "current_policy_academy": academy_state(caught_up=False, promoted=True),
    }

    specialist = v71._current_policy_contract(payload)

    assert specialist["live_policy_expectancy_verified"] is False
    assert specialist["live_promoted_execution"] is None
    assert specialist["promotion_blocked"] is True
    assert specialist["phase"] == "CURRENT-POLICY ACADEMY SCANNING"


def test_current_policy_academy_requires_95_percent_scorable_coverage() -> None:
    payload = {
        "current_policy_academy": academy_state(caught_up=True, promoted=True, opportunities=100, scorable=94),
    }

    specialist = v71._current_policy_contract(payload)

    assert specialist["live_policy_expectancy_verified"] is False
    assert specialist["live_promoted_execution"] is None
    assert specialist["promotion_blocked"] is True
