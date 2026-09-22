from __future__ import annotations

from types import SimpleNamespace

from app.services import live_trader_evidence_identity as identity
from app.services import live_trader_policy_lab_v85 as v85
from app.services import live_trader_zone_retrace_current_policy_academy_v71 as v71


def settings() -> SimpleNamespace:
    return SimpleNamespace(
        live_trader_learning_horizon_minutes=60,
        live_trader_manual_delay_seconds=15,
        live_trader_cost_spread_price=0.30,
        live_trader_cost_entry_slippage_price=0.10,
        live_trader_cost_exit_slippage_price=0.10,
        live_trader_cost_commission_price_equivalent=0.07,
    )


def explicit_scorer(version: str) -> dict:
    return {"scorer_contract_version": version, "metric": "net_r"}


def build(policy_version: str, scorer_version: str, stage: str = "forward") -> dict:
    return identity.build_identity(
        policy_kind="test_policy",
        policy_key="test",
        policy_definition={"version": policy_version, "rule": "same exact rule"},
        settings=settings(),
        learning_version="test-learning-v1",
        evaluation_stage=stage,
        scorer_definition=explicit_scorer(scorer_version),
    )


def test_identical_contracts_produce_identical_content_addressed_ids() -> None:
    left = build("p1", "s1")
    right = build("p1", "s1")
    assert left["policy_id"] == right["policy_id"]
    assert left["scorer_id"] == right["scorer_id"]
    assert left["cohort_id"] == right["cohort_id"]


def test_policy_change_forces_new_policy_and_new_cohort() -> None:
    before = build("p1", "s1")
    after = build("p2", "s1")
    assert before["policy_id"] != after["policy_id"]
    assert before["scorer_id"] == after["scorer_id"]
    assert before["cohort_id"] != after["cohort_id"]


def test_scorer_change_forces_new_scorer_and_new_cohort() -> None:
    before = build("p1", "s1")
    after = build("p1", "s2")
    assert before["policy_id"] == after["policy_id"]
    assert before["scorer_id"] != after["scorer_id"]
    assert before["cohort_id"] != after["cohort_id"]


def test_evaluation_stage_change_starts_new_cohort_without_relabelling_policy() -> None:
    research = build("p1", "s1", "research")
    published = build("p1", "s1", "published")
    assert research["policy_id"] == published["policy_id"]
    assert research["scorer_id"] == published["scorer_id"]
    assert research["cohort_id"] != published["cohort_id"]


def test_policy_lab_old_positive_cohort_cannot_qualify_current_cohort() -> None:
    rows = []
    for index in range(30):
        rows.append(
            {
                "observed_at": f"2026-08-{(index % 20) + 1:02d}T10:00:00+00:00",
                "entry_triggered": True,
                "realised_r": 1.5,
                "gross_realised_r": 1.5,
                "net_realised_r": 1.3,
                "cost_model_version": v85.cost_model.COST_MODEL_VERSION,
                "timing_contract_version": v85.hardening.TIMING_CONTRACT_VERSION,
                "cohort_id": "coh_old",
                "trade_idea": {"policy_lab": {"policy_key": "candidate"}},
            }
        )
    for index in range(30):
        rows.append(
            {
                "observed_at": f"2026-09-{(index % 20) + 1:02d}T10:00:00+00:00",
                "entry_triggered": True,
                "realised_r": -1.0,
                "gross_realised_r": -1.0,
                "net_realised_r": -1.2,
                "cost_model_version": v85.cost_model.COST_MODEL_VERSION,
                "timing_contract_version": v85.hardening.TIMING_CONTRACT_VERSION,
                "cohort_id": "coh_current",
                "trade_idea": {"policy_lab": {"policy_key": "candidate"}},
            }
        )

    stats = v85._policy_stats(rows, {"candidate": "coh_current"})
    leader = stats["leader"]
    assert leader is not None
    assert leader["triggered"] == 30
    assert leader["net_expectancy_r"] == -1.2
    assert leader["forward_candidate"] is False
    assert stats["legacy_unverified_resolved"] == 30


def test_current_policy_opportunity_key_is_cohort_specific() -> None:
    from datetime import datetime, timezone

    observed = datetime(2026, 9, 22, 10, 0, tzinfo=timezone.utc)
    old = v71._opportunity_key("XAU/USD", observed, "BUY", "coh_old")
    new = v71._opportunity_key("XAU/USD", observed, "BUY", "coh_new")
    assert old != new
