from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone

from app.services import live_trader_execution_cost_model as cost_model
from app.services import live_trader_forward_shadow_learning_v83 as v83


def _bullish_state() -> dict:
    return {
        "symbol": "XAU/USD",
        "price": 4300.0,
        "as_of": "2026-09-14T10:15:00+00:00",
        "feed": {
            "connected": True,
            "last_tick_at": "2026-09-14T10:15:00+00:00",
        },
        "bias": {"overall": "bullish", "confidence": 72},
        "market": {"session": "london", "atr": 10.0},
        "zones": {
            "demand": [
                {
                    "low": 4282.0,
                    "high": 4290.0,
                    "quality": 74,
                    "distance_atr": 1.0,
                }
            ],
            "supply": [],
        },
        "setup_family": "abc123",
        "setup_signature": "abc123",
        "setup_family_descriptor": {"bias": "bullish"},
    }


def test_recent_observation_prefers_feed_timestamp() -> None:
    state = _bullish_state()
    state["as_of"] = "2026-09-14T09:00:00+00:00"
    now = datetime(2026, 9, 14, 10, 15, 30, tzinfo=timezone.utc)
    observed = v83._recent_observation_time(state, now=now)
    assert observed == datetime(2026, 9, 14, 10, 15, tzinfo=timezone.utc)


def test_shadow_candidates_are_research_only_and_valid() -> None:
    candidates = v83._shadow_candidates(_bullish_state())
    variants = {item["shadow_variant"] for item in candidates}
    assert variants == {"market_probe", "zone_touch_limit", "momentum_confirmation"}
    for candidate in candidates:
        assert candidate["shadow_only"] is True
        assert candidate["automatic_order_placement"] is False
        assert candidate["manual_only"] is True
        assert candidate["entry"] > 0
        assert candidate["stop"] > 0
        assert candidate["target"] > 0
        assert candidate["risk_reward"] == 1.5


def test_trade_skill_exposes_bad_forward_record() -> None:
    reviews = [
        {"triggered": True, "realised_r": -1.0, "net_realised_r": -1.1, "cost_model_version": cost_model.COST_MODEL_VERSION, "outcome": "LOSS"}
        for _ in range(7)
    ]
    skill = v83._trade_skill_from_reviews(reviews)
    assert skill["published_triggered"] == 7
    assert skill["wins"] == 0
    assert skill["losses"] == 7
    assert skill["total_r"] == -7.7
    assert skill["score"] < 1.0
    assert skill["grade"] == "UNPROVEN"


def test_trade_skill_requires_sample_before_proven() -> None:
    reviews = [
        {"triggered": True, "realised_r": 0.5, "net_realised_r": 0.4, "cost_model_version": cost_model.COST_MODEL_VERSION, "outcome": "WIN"}
        for _ in range(8)
    ]
    skill = v83._trade_skill_from_reviews(reviews)
    assert skill["grade"] == "UNPROVEN"
    assert skill["score"] <= 3.0


def test_trade_skill_never_calls_30_raw_trades_proven() -> None:
    start = datetime(2026, 7, 1, 12, 0, tzinfo=timezone.utc)
    reviews = [
        {
            "triggered": True,
            "realised_r": 1.0 if index % 2 == 0 else -1.0,
            "net_realised_r": 0.9 if index % 2 == 0 else -1.1,
            "cost_model_version": cost_model.COST_MODEL_VERSION,
            "outcome": "DONE",
            "completed_at": (start + timedelta(days=index)).isoformat(),
        }
        for index in range(40)
    ]
    skill = v83._trade_skill_from_reviews(reviews, cohort_id="coh_test")
    assert skill["published_triggered"] == 40
    assert skill["forward_net_supported"] is False
    assert skill["grade"] != "PROVEN"
    assert skill["sample_count_alone_never_proves_edge"] is True

    better = [
        {
            "triggered": True,
            "realised_r": 1.5 if index % 3 != 0 else -1.0,
            "net_realised_r": 1.4 if index % 3 != 0 else -1.1,
            "cost_model_version": cost_model.COST_MODEL_VERSION,
            "outcome": "DONE",
            "completed_at": (start + timedelta(days=index)).isoformat(),
        }
        for index in range(45)
    ]
    better_skill = v83._trade_skill_from_reviews(better, cohort_id="coh_test")
    assert better_skill["published_triggered"] == 45
    assert better_skill["score"] >= 7.5
    assert better_skill["grade"] == "FORWARD_NET_SUPPORTED"
    assert better_skill["one_sided_95pct_day_cluster_lower_bound_r"] > 0


def test_shadow_research_does_not_copy_live_zone_distance_gate() -> None:
    state = _bullish_state()
    state["zones"]["demand"][0]["distance_atr"] = 5.5
    candidates = v83._shadow_candidates(state)

    variants = {item["shadow_variant"] for item in candidates}
    assert "market_probe" in variants
    assert "momentum_confirmation" in variants
    assert all(item["shadow_only"] is True for item in candidates)
    assert all(item["automatic_order_placement"] is False for item in candidates)


def test_shadow_research_prefers_nearest_quality_matching_zone() -> None:
    state = _bullish_state()
    state["zones"]["demand"] = [
        {"low": 4260.0, "high": 4270.0, "quality": 99, "distance_atr": 4.5},
        {"low": 4282.0, "high": 4290.0, "quality": 74, "distance_atr": 1.0},
    ]
    zone = v83._matching_zone(state, "bullish")
    assert zone is not None
    assert zone["distance_atr"] == 1.0



class _ShadowResolverClient:
    def __init__(self, row: dict) -> None:
        self.row = row
        self.patched = False

    async def get(self, _table: str, *, params: dict | None = None, **_kwargs):
        return [dict(self.row)]

    async def patch(self, _table: str, _values: dict, *, filters: dict):
        self.patched = True
        return []


class _ShadowResolverSettings:
    live_trader_learning_horizon_minutes = 60


class _ShadowResolverEngine:
    def __init__(self, row: dict) -> None:
        self.repo = type("Repo", (), {"client": _ShadowResolverClient(row)})()
        self.settings = _ShadowResolverSettings()
        self._shadow_last_resolution_v83 = None


def test_shadow_resolver_never_scores_unactivated_current_timing(monkeypatch) -> None:
    row = {
        "id": "shadow-1",
        "observed_at": "2026-09-22T08:00:00+00:00",
        "price": 4300.0,
        "horizon_minutes": 60,
        "market_state": {},
        "trade_idea": {"order_type": "buy_limit", "side": "BUY", "entry": 4290.0, "stop": 4280.0, "target": 4305.0},
        "market_observed_at": "2026-09-22T08:00:00+00:00",
        "market_received_at": "2026-09-22T08:00:01+00:00",
        "decision_at": "2026-09-22T08:00:02+00:00",
        "publication_requested_at": "2026-09-22T08:00:03+00:00",
        "publication_confirmed_at": None,
        "activation_at": None,
        "execution_start_at": None,
        "timing_contract_version": v83.hardening.TIMING_CONTRACT_VERSION,
    }
    engine = _ShadowResolverEngine(row)
    monkeypatch.setattr(
        v83.core,
        "utc_now",
        lambda: datetime(2026, 9, 22, 10, 0, tzinfo=timezone.utc),
    )
    source_called = False

    async def forbidden_source(*_args, **_kwargs):
        nonlocal source_called
        source_called = True
        return []

    monkeypatch.setattr(v83.hardening, "_source_m1_rows", forbidden_source)
    result = asyncio.run(v83._resolve_shadow_outcomes(engine))

    assert result["resolved"] == 0
    assert source_called is False
    assert engine.repo.client.patched is False



def test_trade_skill_concentration_failure_never_displays_supported_grade() -> None:
    start = datetime(2026, 7, 1, 10, 0, tzinfo=timezone.utc)
    reviews = [
        {
            "triggered": True,
            "realised_r": 0.5,
            "net_realised_r": 0.4,
            "cost_model_version": cost_model.COST_MODEL_VERSION,
            "outcome": "WIN",
            "completed_at": (start + timedelta(minutes=index)).isoformat(),
        }
        for index in range(8)
    ]
    reviews.extend(
        {
            "triggered": True,
            "realised_r": 0.5,
            "net_realised_r": 0.4,
            "cost_model_version": cost_model.COST_MODEL_VERSION,
            "outcome": "WIN",
            "completed_at": (start + timedelta(days=index)).isoformat(),
        }
        for index in range(1, 23)
    )

    skill = v83._trade_skill_from_reviews(reviews, cohort_id="coh_concentrated")

    assert skill["published_triggered"] == 30
    assert skill["forward_net_supported"] is False
    assert skill["grade"] == "EVIDENCE_CONCENTRATED"
    assert skill["support_label_consistent_with_all_quality_gates"] is True
    assert skill["max_single_day_trigger_share"] > 0.25
    assert "single_day_concentration" in skill["failed_quality_gates"]



def test_trade_skill_fails_closed_if_quality_metadata_is_ever_contradictory(monkeypatch) -> None:
    monkeypatch.setattr(
        v83.quality,
        "evaluate_published_paper",
        lambda _rows, *, cohort_id: {
            "grade": "FORWARD_NET_SUPPORTED",
            "forward_net_supported": False,
            "independent_days": 30,
            "independent_weeks": 6,
            "one_sided_95pct_day_cluster_lower_bound_r": 0.2,
            "max_single_day_trigger_share": 0.10,
            "failed_quality_gates": ["single_day_concentration"],
        },
    )

    skill = v83._trade_skill_from_reviews([], cohort_id="coh_guard")

    assert skill["forward_net_supported"] is False
    assert skill["grade"] == "QUALIFICATION_INCONSISTENT"
    assert skill["support_label_consistent_with_all_quality_gates"] is False
