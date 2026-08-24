import random

from app.services import composer
from app.services import composer_mutation_guard_v1 as guard


def _parent_rules() -> dict:
    rules = composer.compose_batch(1, generation=1, seed=17)[0]["rules"]
    rules["family"] = "composed_signal"
    rules["entry"] = {
        "direction_rule": "current_direction",
        "condition_mode": "all",
        "conditions": [],
    }
    return rules


def test_unsupported_parameterised_condition_does_not_offer_condition_parameter_gene() -> None:
    rules = _parent_rules()
    rules["entry"]["conditions"] = [
        {"type": "mtf_context_alignment_abs_min", "min": 2},
        {"type": "prev_day_low_sweep_reclaim", "lookback": 12},
    ]

    genes = composer._available_genes(rules)

    assert "condition_parameter" not in genes


def test_preferred_condition_parameter_is_safely_ignored_when_only_unsupported_conditions_exist() -> None:
    rules = _parent_rules()
    rules["entry"]["conditions"] = [
        {"type": "mtf_context_alignment_abs_min", "min": 2},
        {"type": "prev_day_low_sweep_reclaim", "lookback": 12},
    ]

    mutation = composer.mutate_rules(
        rules,
        random.Random(11),
        preferred_genes=["condition_parameter"],
        exploration_rate=0.0,
    )

    assert mutation.gene != "condition_parameter"
    assert mutation.old != mutation.new


def test_condition_parameter_mutates_only_supported_condition_when_mixed_with_new_scientist_condition() -> None:
    rules = _parent_rules()
    unsupported = {"type": "mtf_context_alignment_abs_min", "min": 2}
    supported = {"type": "wick_body_ratio_min", "ratio": 2.0}
    rules["entry"]["conditions"] = [dict(unsupported), dict(supported)]

    mutation = composer.mutate_rules(
        rules,
        random.Random(21),
        preferred_genes=["condition_parameter"],
        exploration_rate=0.0,
    )

    assert mutation.gene == "condition_parameter"
    assert mutation.old == supported
    assert mutation.new["type"] == "wick_body_ratio_min"
    assert mutation.new["ratio"] != 2.0
    assert mutation.rules["entry"]["conditions"][0] == unsupported


def test_guard_version_and_supported_types_are_explicit() -> None:
    assert guard.GUARD_VERSION == "eve-composer-mutation-guard-v1"
    assert "wick_body_ratio_min" in guard.MUTABLE_CONDITION_PARAMETER_TYPES
    assert "mtf_context_alignment_abs_min" not in guard.MUTABLE_CONDITION_PARAMETER_TYPES
