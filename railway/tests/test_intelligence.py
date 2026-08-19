import asyncio
import random
from types import SimpleNamespace

from app.services.intelligence import (
    INTELLIGENCE_VERSION,
    IntelligenceDirector,
    condition_key,
    development_score,
    proposal_rules,
    rule_feature_keys,
)


class FakeClient:
    def __init__(self, responses=None):
        self.responses = responses or {}
        self.get_calls = []
        self.upserts = []

    async def get(self, table, *, params=None, range_start=None, range_end=None):
        self.get_calls.append((table, dict(params or {})))
        response = self.responses.get(table, [])
        return list(response)

    async def upsert(self, table, rows, *, on_conflict, return_rows=False):
        payload = list(rows) if isinstance(rows, list) else [dict(rows)]
        self.upserts.append((table, payload, on_conflict))
        return []


class FakeRepo:
    def __init__(self, client):
        self.client = client
        self.seeded = []
        self.events = []

    async def seed_candidates(self, rows):
        self.seeded.extend(rows)

    async def event(self, level, component, message, details=None):
        self.events.append((level, component, message, details or {}))


def settings():
    return SimpleNamespace(
        source_symbol="XAU/USD",
        research_timeframe="M5",
        source_snapshot_interval="15min",
        source_candle_interval="5min",
    )


async def empty_rows():
    return []


def test_condition_key_and_feature_keys_preserve_parameters():
    rules = {
        "entry": {
            "direction_rule": "trend_direction",
            "conditions": [{"type": "alignment_abs_min", "min": 3}],
        },
        "schedule": {"sessions": ["london"], "hours_utc": []},
        "environment": {
            "trend_12": "directional",
            "trend_48": "any",
            "compression": "any",
            "regimes": [],
        },
    }
    assert condition_key({"type": "alignment_abs_min", "min": 3}) == "condition:alignment_abs_min:min=3"
    features = rule_feature_keys(rules)
    assert "direction:trend_direction" in features
    assert "condition:alignment_abs_min:min=3" in features
    assert "schedule:session:london" in features
    assert "environment:trend12:directional" in features


def test_proposals_do_not_create_conflicting_or_duplicate_condition_types():
    for seed in range(100):
        rules = proposal_rules(
            random.Random(seed),
            {},
            symbol="XAU/USD",
            timeframe="M5",
            snapshot_interval="15min",
            source_interval="5min",
        )
        conditions = rules["entry"]["conditions"]
        kinds = [item["type"] for item in conditions]
        assert len(kinds) == len(set(kinds))
        assert not (
            "direction_matches_trend12" in kinds
            and "direction_opposes_trend12" in kinds
        )
        assert not (
            "alignment_matches_direction" in kinds
            and "alignment_opposes_direction" in kinds
        )


def test_development_score_rewards_real_edge():
    weak = SimpleNamespace(
        trades=300,
        profit_factor=0.95,
        expectancy_r=-0.02,
        positive_year_rate=0.33,
        max_drawdown_r=20,
    )
    strong = SimpleNamespace(
        trades=300,
        profit_factor=1.35,
        expectancy_r=0.10,
        positive_year_rate=1.0,
        max_drawdown_r=6,
    )
    assert development_score(strong) > development_score(weak)


def test_learning_memory_reads_selection_stage_only():
    candidate_rules = {
        "entry": {
            "direction_rule": "current_direction",
            "conditions": [{"type": "trend12_trend48_agree"}],
        },
        "schedule": {"sessions": [], "hours_utc": list(range(24))},
        "environment": {
            "trend_12": "any",
            "trend_48": "any",
            "compression": "any",
            "regimes": [],
        },
    }
    client = FakeClient(
        {
            "strategy_candidates": [
                {
                    "candidate_key": "candidate-test",
                    "rules": candidate_rules,
                    "result_status": "validated",
                    "fitness_score": 50,
                    "metrics": {
                        "validation": {
                            "profit_factor": 1.3,
                            "expectancy_r": 0.08,
                            "trades": 120,
                        }
                    },
                }
            ]
        }
    )
    director = IntelligenceDirector(settings(), FakeRepo(client), empty_rows)
    memory = asyncio.run(director._rebuild_memory())
    strategy_call = next(params for table, params in client.get_calls if table == "strategy_candidates")
    assert strategy_call["research_stage"] == "eq.selection"
    assert strategy_call["composer_version"] == f"eq.{INTELLIGENCE_VERSION}"
    assert "condition:trend12_trend48_agree" in memory
    assert memory["condition:trend12_trend48_agree"] > 0


def test_live_watcher_promotes_exact_validated_pattern_to_triggered():
    rules = {
        "family": "composed_signal",
        "market": {
            "symbol": "XAU/USD",
            "timeframe": "M5",
            "snapshot_interval": "15min",
            "source_interval": "5min",
        },
        "schedule": {
            "weekdays": [1, 2, 3, 4, 5],
            "months": list(range(1, 13)),
            "sessions": ["london"],
            "hours_utc": [],
        },
        "environment": {
            "regimes": [],
            "trend_12": "any",
            "trend_48": "any",
            "compression": "any",
            "min_alignment_abs": 0,
            "alignment_sign": "any",
            "streak": "any",
        },
        "entry": {
            "direction_rule": "current_direction",
            "condition_mode": "all",
            "conditions": [
                {"type": "direction_matches_trend12"},
                {"type": "alignment_matches_direction"},
            ],
        },
        "risk": {
            "stop_atr": 1.0,
            "target_atr": 2.0,
            "horizon_minutes": 60,
            "max_hold_minutes": 60,
            "cooldown_minutes": 60,
            "cost_r": 0.04,
        },
    }
    snapshot = {
        "symbol": "XAU/USD",
        "snapshot_interval": "15min",
        "source_interval": "5min",
        "candle_time": "2026-08-19T09:00:00+00:00",
        "weekday": 3,
        "month": 8,
        "hour_utc": 9,
        "session": "london",
        "regime": "trend_up",
        "direction": 1,
        "trend_12_atr": 0.4,
        "trend_48_atr": 0.3,
        "compression_ratio": 1.0,
        "alignment_score": 3,
        "return_1_pct": 0.02,
        "return_3_pct": 0.05,
        "close_location": 0.8,
        "upper_wick": 0.1,
        "lower_wick": 0.1,
        "body_price": 0.4,
    }
    client = FakeClient(
        {
            "source_snapshots": [snapshot],
            "frozen_strategies": [
                {
                    "id": "frozen-1",
                    "strategy_code": "EVE-DISC-TEST",
                    "name": "Validated Test",
                    "symbol": "XAU/USD",
                    "timeframe": "M5",
                    "status": "frozen",
                    "rules": rules,
                    "result_status": "validated",
                    "metrics": {},
                    "m1_replay": {"passed": True},
                }
            ],
            "live_setups": [],
        }
    )
    repo = FakeRepo(client)
    director = IntelligenceDirector(settings(), repo, empty_rows)
    result = asyncio.run(director.run_live_watch_once())

    assert result["ok"] is True
    assert result["status_counts"]["triggered"] == 1
    live_upsert = next(payload for table, payload, _ in client.upserts if table == "live_setups")
    assert live_upsert[0]["status"] == "triggered"
    assert live_upsert[0]["direction"] == "buy"
    assert repo.events
