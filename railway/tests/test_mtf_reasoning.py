import random

from app.services import backtest_v3 as research
from app.services import intelligence_v2 as scientist
from app.services import mtf_reasoning


def bullish_context_row():
    return {
        "direction": 1,
        "mtf_m1_available": True,
        "mtf_m1_direction": 1,
        "mtf_m1_direction_changes": 1,
        "mtf_m1_path_efficiency": 0.82,
        "mtf_m1_last_direction": -1,
        "mtf_m15_direction": -1,
        "mtf_m30_direction": -1,
        "mtf_h1_direction": 1,
        "mtf_h4_direction": 1,
        "mtf_d1_direction": 1,
        "mtf_htf_alignment_score": 1,
    }


def test_mtf_conditions_read_causal_relationship_fields():
    row = bullish_context_row()
    assert mtf_reasoning.recipe_condition_matches(row, {"type": "mtf_m1_path_efficiency_min", "min": 0.75})
    assert mtf_reasoning.recipe_condition_matches(row, {"type": "mtf_m1_direction_matches_m5"})
    assert mtf_reasoning.recipe_condition_matches(row, {"type": "mtf_m1_last_minute_opposes_m5"})
    assert mtf_reasoning.recipe_condition_matches(row, {"type": "mtf_m15_m30_agree_m5_opposes"})
    assert mtf_reasoning.recipe_condition_matches(row, {"type": "mtf_h1_h4_d1_agree"})
    assert mtf_reasoning.recipe_condition_matches(row, {"type": "mtf_context_alignment_matches_m5"})
    assert not mtf_reasoning.recipe_condition_matches(row, {"type": "mtf_h1_h4_agree_m5_opposes"})


def test_mtf_direction_rules_are_deterministic():
    row = bullish_context_row()
    assert mtf_reasoning.candidate_direction(row, {"entry": {"direction_rule": "mtf_htf_consensus_direction"}}) == 1
    assert mtf_reasoning.candidate_direction(row, {"entry": {"direction_rule": "mtf_h1_direction"}}) == 1
    assert mtf_reasoning.candidate_direction(row, {"entry": {"direction_rule": "mtf_m15_m30_consensus_direction"}}) == -1
    assert mtf_reasoning.candidate_direction(row, {"entry": {"direction_rule": "mtf_h1_h4_consensus_direction"}}) == 1


def test_advanced_mtf_rules_remain_blocked_from_mt5_export_parity():
    rules = {
        "entry": {
            "direction_rule": "mtf_htf_consensus_direction",
            "conditions": [{"type": "mtf_h1_h4_agree"}],
        }
    }
    assert research.has_structure_conditions(rules) is True


def test_every_m5_proposals_can_invent_cross_timeframe_relationships():
    mtf_rules = []
    for seed in range(40):
        rules = mtf_reasoning.proposal_rules(
            random.Random(seed),
            {},
            symbol="XAU/USD",
            timeframe="M5",
            snapshot_interval="5min",
            source_interval="5min",
        )
        assert rules["market"]["mtf_reasoning_version"] == mtf_reasoning.MTF_REASONING_VERSION
        conditions = [str(item.get("type")) for item in rules["entry"].get("conditions") or []]
        if any(kind in mtf_reasoning.MTF_CONDITION_TYPES for kind in conditions) or rules["entry"]["direction_rule"] in mtf_reasoning.MTF_DIRECTION_RULES:
            mtf_rules.append(rules)
    assert len(mtf_rules) >= 20


def test_legacy_snapshot_proposals_do_not_receive_mtf_genes():
    for seed in range(10):
        rules = mtf_reasoning.proposal_rules(
            random.Random(seed),
            {},
            symbol="XAU/USD",
            timeframe="M5",
            snapshot_interval="15min",
            source_interval="5min",
        )
        assert "mtf_reasoning_version" not in rules["market"]
        assert rules["entry"]["direction_rule"] not in mtf_reasoning.MTF_DIRECTION_RULES
        assert not any(
            str(item.get("type")) in mtf_reasoning.MTF_CONDITION_TYPES
            for item in rules["entry"].get("conditions") or []
        )


def test_scientist_module_is_patched_for_mtf_generation():
    rules = scientist._proposal_rules(
        random.Random(91),
        {},
        symbol="XAU/USD",
        timeframe="M5",
        snapshot_interval="5min",
        source_interval="5min",
    )
    assert rules["market"]["mtf_reasoning_version"] == mtf_reasoning.MTF_REASONING_VERSION
