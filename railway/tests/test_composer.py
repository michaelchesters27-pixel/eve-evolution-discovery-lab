from app.services.composer import compose_batch, mutate_rules
import random


def test_composer_creates_unique_valid_candidates():
    rows = compose_batch(50, generation=1, seed=42, everyday_bias=0.8)
    assert len(rows) == 50
    assert len({row["candidate_key"] for row in rows}) == 50
    for row in rows:
        rules = row["rules"]
        assert rules["family"]
        assert rules["market"]["source_interval"] == "5min"
        assert rules["market"]["timeframe"] == "M5"
        assert rules["schedule"]["weekdays"]
        assert rules["schedule"]["months"]
        assert rules["risk"]["stop_atr"] > 0
        assert rules["risk"]["target_atr"] > 0
        assert rules["risk"]["horizon_minutes"] in {15, 60, 240}


def test_mutation_changes_one_controlled_gene():
    parent = compose_batch(1, generation=1, seed=9)[0]["rules"]
    mutation = mutate_rules(parent, random.Random(10), preferred_genes=["stop_atr"])
    assert mutation.gene == "stop_atr"
    assert mutation.old != mutation.new
    assert mutation.rules["risk"]["stop_atr"] == mutation.new
    assert parent["risk"]["stop_atr"] == mutation.old
