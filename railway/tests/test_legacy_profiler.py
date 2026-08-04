import asyncio
from types import SimpleNamespace
from unittest.mock import patch

from app.services.orchestrator import DiscoveryOrchestrator


class FakeRepository:
    def __init__(self):
        self.package_row = {
            "id": "package-1",
            "frozen_strategy_id": "frozen-1",
            "strategy_name": "Legacy Survivor",
            "profile_attempts": 0,
        }
        self.profiled = False
        self.updated_frozen = None
        self.stored = None
        self.events = []

    async def package_needing_profile(self):
        return self.package_row

    async def mark_package_profiling(self, package_id, attempts=0):
        self.profiled = package_id == "package-1"

    async def frozen_strategy(self, frozen_id):
        return {
            "id": frozen_id,
            "frozen_key": "frozen-key",
            "strategy_code": "EVE-LEGACY",
            "name": "Legacy Survivor",
            "family": "momentum",
            "symbol": "XAU/USD",
            "timeframe": "M5",
            "rule_hash": "a" * 64,
            "rules": {
                "family": "momentum",
                "market": {"symbol": "XAU/USD", "timeframe": "M5", "snapshot_interval": "15min", "source_interval": "5min"},
                "schedule": {"sessions": ["new_york"], "weekdays": [1, 2, 3, 4, 5]},
                "environment": {},
                "entry": {"direction_rule": "candle_direction"},
                "risk": {"stop_atr": 1.0, "target_atr": 2.0, "max_hold_minutes": 60, "cooldown_minutes": 60, "max_spread_points": 100},
            },
        }

    async def store_package(self, row):
        self.stored = row
        return [{"id": "package-1"}]

    async def update_frozen_profile(self, frozen_id, values):
        self.updated_frozen = (frozen_id, values)

    async def event(self, level, component, message, details=None):
        self.events.append((level, component, message, details or {}))

    async def mark_profile_failed(self, *args, **kwargs):
        raise AssertionError("Profile should not fail")

    async def mark_profile_retry(self, *args, **kwargs):
        raise AssertionError("Profile should not retry")


def final_result():
    segment = {
        "trades": 100,
        "profit_factor": 1.30,
        "expectancy_r": 0.08,
        "trades_per_day": 2.0,
        "session_expectancy": {"new_york": 0.08},
        "session_trades": {"new_york": 100},
        "regime_expectancy": {"trend": 0.07},
        "regime_trades": {"trend": 100},
        "weekday_expectancy": {"2": 0.08},
        "weekday_trades": {"2": 100},
        "hour_expectancy": {"13": 0.09},
        "hour_trades": {"13": 100},
    }
    return {
        "research_stage": "final",
        "result_status": "validated",
        "research_integrity_version": "eve-research-integrity-v2.0",
        "dataset_version": "dataset-legacy-review",
        "metrics": {"validation": segment, "confirmation": segment, "holdout": segment, "locked": segment, "recent": segment},
        "walk_forward": {"stability": 0.8},
        "robustness": {"pass_rate": 0.8, "final": {"pass_rate": 0.8}},
        "monte_carlo": {"pass_rate": 0.9},
        "execution_costs": {"elevated": {"expectancy_r": 0.04}},
        "evidence": {"decision": {"failed_gates": []}, "dataset": {"version": "dataset-legacy-review"}},
        "stability_score": 80,
        "fitness_score": 20,
    }


def test_legacy_package_is_reprofiled_before_download():
    settings = SimpleNamespace(
        minimum_validation_trades=60,
        minimum_locked_trades=80,
        m1_replay_enabled=True,
        source_symbol="XAU/USD",
        research_timeframe="M5",
        source_snapshot_interval="15min",
        source_candle_interval="5min",
        legacy_profile_max_attempts=3,
    )
    repo = FakeRepository()
    orchestrator = DiscoveryOrchestrator(settings, object(), repo)

    async def fake_m1(*_args, **_kwargs):
        return {"status": "passed", "passed": True, "failed_gates": []}

    def fake_package(enriched):
        assert enriched["trading_passport"]["completeness"]["complete"] is True
        return {
            "package_key": "package-key",
            "profile_status": "complete",
            "download_eligible": True,
            "trading_passport": enriched["trading_passport"],
        }

    with patch("app.services.orchestrator.evaluate_strategy", return_value=final_result()), \
         patch("app.services.orchestrator.validate_with_m1", side_effect=fake_m1), \
         patch("app.services.orchestrator.package_payload", side_effect=fake_package):
        completed = asyncio.run(orchestrator.profile_legacy_package([{"candle_time": "2020-01-01T00:00:00Z"}]))

    assert completed is True
    assert repo.profiled is True
    assert repo.stored["download_eligible"] is True
    frozen_id, values = repo.updated_frozen
    assert frozen_id == "frozen-1"
    assert values["profile_status"] == "complete"
    assert values["trading_passport"]["market"] == "XAU/USD"
    assert any(component == "strategy_profiler" and level == "success" for level, component, *_ in repo.events)
