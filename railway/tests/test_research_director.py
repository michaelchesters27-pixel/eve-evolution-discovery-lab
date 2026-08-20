from types import SimpleNamespace

from app.services import research_director as director


class Metrics:
    def __init__(self, trades, pf, expectancy, positive_year_rate=1.0, drawdown=2.0):
        self.trades = trades
        self.profit_factor = pf
        self.expectancy_r = expectancy
        self.positive_year_rate = positive_year_rate
        self.max_drawdown_r = drawdown

    def as_dict(self):
        return {
            "trades": self.trades,
            "profit_factor": self.profit_factor,
            "expectancy_r": self.expectancy_r,
            "positive_year_rate": self.positive_year_rate,
            "max_drawdown_r": self.max_drawdown_r,
        }


def test_director_shrinks_single_trial_memory_and_builds_family_plan():
    memory, plan = director.build_director_memory(
        [
            {"feature_key": "condition:mtf_h1_h4_agree", "score": 2.4, "trials": 9, "positive_trials": 7},
            {"feature_key": "condition:mtf_d1_opposes_m5", "score": -3.0, "trials": 1, "positive_trials": 0},
            {"feature_key": "condition:break_prior_12_high", "score": 1.0, "trials": 5, "positive_trials": 3},
        ]
    )

    assert memory["condition:mtf_h1_h4_agree"] > 0
    assert memory["condition:mtf_d1_opposes_m5"] > -3.0
    assert plan["version"] == director.RESEARCH_DIRECTOR_VERSION
    mtf = next(item for item in plan["families"] if item["family"] == "multi_timeframe")
    assert mtf["trials"] == 10
    assert "multi_timeframe" in plan["strongest_families"]


def test_interaction_memory_shrinks_pairs_and_scores_matching_rules():
    scores, summary = director.build_interaction_memory(
        [
            {
                "feature_a": "condition:mtf_h1_h4_agree",
                "feature_b": "schedule:session:london",
                "trials": 12,
                "positive_trials": 9,
                "score": 2.0,
            },
            {
                "feature_a": "condition:mtf_d1_opposes_m5",
                "feature_b": "direction:mtf_d1_direction",
                "trials": 1,
                "positive_trials": 0,
                "score": -4.0,
            },
        ]
    )
    good_key = director.interaction_key("condition:mtf_h1_h4_agree", "schedule:session:london")
    weak_key = director.interaction_key("condition:mtf_d1_opposes_m5", "direction:mtf_d1_direction")
    assert 0 < scores[good_key] < 2.0
    assert -4.0 < scores[weak_key] < 0
    assert summary["interactions"] == 2

    rules = {
        "schedule": {"sessions": ["london"], "hours_utc": [], "weekdays": [1, 2, 3, 4, 5], "months": list(range(1, 13))},
        "environment": {"regimes": [], "trend_12": "any", "trend_48": "any", "compression": "any"},
        "entry": {"direction_rule": "current_direction", "conditions": [{"type": "mtf_h1_h4_agree"}]},
    }
    assert director.proposal_interaction_score(rules, scores) > 0


def test_interaction_score_normalises_pair_count():
    rules = {
        "schedule": {"sessions": [], "hours_utc": [], "weekdays": [1, 2, 3, 4, 5], "months": list(range(1, 13))},
        "environment": {"regimes": [], "trend_12": "any", "trend_48": "any", "compression": "any"},
        "entry": {
            "direction_rule": "current_direction",
            "conditions": [{"type": "mtf_h1_h4_agree"}, {"type": "mtf_m15_m30_agree"}, {"type": "wick_body_ratio_min", "ratio": 1.2}],
        },
    }
    features = sorted(set(director.v1.rule_feature_keys(rules)))
    scores = {}
    for i, left in enumerate(features):
        for right in features[i + 1 :]:
            scores[director.interaction_key(left, right)] = 1.0
    score = director.proposal_interaction_score(rules, scores)
    assert score > 0
    assert score <= 5.0


def test_ablation_removes_redundant_condition_without_using_sealed_data(monkeypatch):
    def fake_evaluate(_rows, rules):
        count = len(rules["entry"]["conditions"])
        if count == 3:
            return Metrics(220, 1.28, 0.090)
        if count == 2:
            return Metrics(245, 1.31, 0.100)
        return Metrics(260, 1.01, 0.005)

    monkeypatch.setattr(director.research, "evaluate_segment", fake_evaluate)
    owner = SimpleNamespace(
        minimum_development_trades=120,
        minimum_development_pf=1.03,
        minimum_development_expectancy=0.01,
    )
    rules = {
        "market": {"symbol": "XAU/USD", "timeframe": "M5", "snapshot_interval": "5min", "source_interval": "5min"},
        "family": "composed_signal",
        "schedule": {"weekdays": [1, 2, 3, 4, 5], "months": list(range(1, 13)), "sessions": [], "hours_utc": list(range(24))},
        "environment": {"regimes": [], "trend_12": "any", "trend_48": "any", "compression": "any"},
        "entry": {
            "direction_rule": "current_direction",
            "condition_mode": "all",
            "conditions": [
                {"type": "mtf_h1_h4_agree"},
                {"type": "mtf_m15_m30_agree"},
                {"type": "wick_body_ratio_min", "ratio": 1.2},
            ],
        },
        "risk": {"stop_atr": 1.0, "target_atr": 1.5, "horizon_minutes": 60, "cooldown_minutes": 60},
    }
    item = {
        "hypothesis_key": "science-parent",
        "candidate_key": "candidate-parent",
        "rules": rules,
        "hypothesis": "parent",
        "feature_keys": [],
        "development_metrics": fake_evaluate([], rules).as_dict(),
        "development_score": 10.0,
        "qualified": True,
    }

    simplified, summary = director.ablate_hypothesis(owner, [], item)

    assert len(simplified["rules"]["entry"]["conditions"]) == 2
    assert summary["removed_conditions"] == 1
    assert summary["confirmation_holdout_access"] == "forbidden"
    assert simplified["hypothesis_key"] != "science-parent"


def test_ablation_refuses_simplification_when_edge_collapses(monkeypatch):
    def fake_evaluate(_rows, rules):
        count = len(rules["entry"]["conditions"])
        return Metrics(220, 1.30, 0.10) if count == 2 else Metrics(240, 0.95, -0.02)

    monkeypatch.setattr(director.research, "evaluate_segment", fake_evaluate)
    owner = SimpleNamespace(
        minimum_development_trades=120,
        minimum_development_pf=1.03,
        minimum_development_expectancy=0.01,
    )
    rules = {
        "market": {"symbol": "XAU/USD", "timeframe": "M5", "snapshot_interval": "5min", "source_interval": "5min"},
        "family": "composed_signal",
        "schedule": {"weekdays": [1, 2, 3, 4, 5], "months": list(range(1, 13)), "sessions": [], "hours_utc": list(range(24))},
        "environment": {"regimes": [], "trend_12": "any", "trend_48": "any", "compression": "any"},
        "entry": {
            "direction_rule": "current_direction",
            "condition_mode": "all",
            "conditions": [{"type": "mtf_h1_h4_agree"}, {"type": "wick_body_ratio_min", "ratio": 1.2}],
        },
        "risk": {"stop_atr": 1.0, "target_atr": 1.5, "horizon_minutes": 60, "cooldown_minutes": 60},
    }
    item = {
        "hypothesis_key": "science-parent",
        "candidate_key": "candidate-parent",
        "rules": rules,
        "hypothesis": "parent",
        "feature_keys": [],
        "development_metrics": fake_evaluate([], rules).as_dict(),
        "development_score": 10.0,
        "qualified": True,
    }

    simplified, summary = director.ablate_hypothesis(owner, [], item)

    assert len(simplified["rules"]["entry"]["conditions"]) == 2
    assert summary["removed_conditions"] == 0
