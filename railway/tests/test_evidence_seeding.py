import random

from app.services import evidence_direction
from app.services.evidence_seeding import (
    build_seeded_proposals,
    condition_from_feature_key,
    proposal_from_signal,
    seed_eligibility,
    stored_signal_is_verified,
    verified_evidence_rows,
)


def signal(**overrides):
    row = {
        "status": "signal",
        "signature": "pair:test:30",
        "kind": "pair",
        "feature_keys": [
            "condition:range_position_low:max=0.1",
            "condition:range_expansion_min:min=1.5",
        ],
        "horizon_minutes": 30,
        "sample_count": 8718,
        "q_value": 0.00000154,
        "year_stability": 1.0,
        "direction": "up",
        "effect_pct": 0.01002071,
        "standardized_effect": 0.0712493,
        "evidence_score": 1.256247,
    }
    row.update(overrides)
    return row


def test_stale_signal_cannot_teach_or_seed():
    stale = signal(q_value=1.0)
    assert not stored_signal_is_verified(stale)
    assert verified_evidence_rows([stale]) == []
    assert seed_eligibility(stale)[0] is False


def test_feature_key_round_trips_to_executable_condition():
    assert condition_from_feature_key("condition:range_position_low:max=0.1") == {
        "type": "range_position_low",
        "max": 0.1,
    }
    assert condition_from_feature_key("condition:break_prior_12_low") == {
        "type": "break_prior_12_low",
    }


def test_up_anomaly_becomes_explicit_long_30_minute_hypothesis():
    proposal = proposal_from_signal(
        signal(),
        random.Random(7),
        symbol="XAU/USD",
        timeframe="M5",
        snapshot_interval="5min",
        source_interval="5min",
        research_dataset="every_m5_fabric",
        fabric_version="test-fabric",
    )
    assert proposal is not None
    rules = proposal["rules"]
    assert rules["entry"]["direction_rule"] == "evidence_long"
    assert rules["risk"]["horizon_minutes"] == 30
    assert rules["risk"]["max_hold_minutes"] == 30
    assert rules["market"]["mt5_export_gate"] == "advanced_rule_parity_required"
    assert proposal["hypothesis"].startswith("Evidence-seeded UP 30m")


def test_down_london_anomaly_preserves_session_and_direction():
    row = signal(
        signature="pair:london:60",
        feature_keys=["condition:range_position_high:min=0.9", "schedule:session:london"],
        horizon_minutes=60,
        direction="down",
        q_value=0.0000002,
        standardized_effect=-0.062,
        evidence_score=1.21,
    )
    proposal = proposal_from_signal(
        row,
        random.Random(9),
        symbol="XAU/USD",
        timeframe="M5",
        snapshot_interval="5min",
        source_interval="5min",
        research_dataset="every_m5_fabric",
    )
    assert proposal is not None
    assert proposal["rules"]["entry"]["direction_rule"] == "evidence_short"
    assert proposal["rules"]["schedule"]["sessions"] == ["london"]
    assert proposal["rules"]["risk"]["horizon_minutes"] == 60


def test_120_minute_close_only_evidence_is_not_directly_seeded():
    row = signal(horizon_minutes=120)
    assert seed_eligibility(row) == (False, "unsupported_trade_horizon")


def test_explicit_evidence_direction_is_deterministic():
    assert evidence_direction.candidate_direction({}, {"entry": {"direction_rule": "evidence_long"}}) == 1
    assert evidence_direction.candidate_direction({}, {"entry": {"direction_rule": "evidence_short"}}) == -1


def test_seeding_summary_preserves_exploration_budget_boundary():
    proposals, summary = build_seeded_proposals(
        [signal()],
        set(),
        target=20,
        seed=11,
        symbol="XAU/USD",
        timeframe="M5",
        snapshot_interval="5min",
        source_interval="5min",
        research_dataset="every_m5_fabric",
    )
    assert len(proposals) == 1
    assert summary["verified_signals"] == 1
    assert summary["seeded_hypotheses"] == 1
    assert summary["seed_share_cap"] == 0.55
    assert summary["confirmation_holdout_access"] == "forbidden"
