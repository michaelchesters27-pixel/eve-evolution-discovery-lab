from __future__ import annotations

from datetime import datetime, timedelta, timezone

from app.services import live_trader_evidence_quality_v92 as quality


def row(at: datetime, value: float) -> dict:
    return {"observed_at": at.isoformat(), "completed_at": at.isoformat(), "net_realised_r": value}


def test_one_day_thirty_trade_probe_cannot_be_confirmation_candidate() -> None:
    at = datetime(2026, 9, 22, 10, 0, tzinfo=timezone.utc)
    rows = [row(at + timedelta(minutes=index), 0.25) for index in range(30)]
    result = quality.evaluate_policy_lab_candidate(rows, policy_key="probe", cohort_id="coh_probe")
    assert result["screening_pass_30_and_mean_only"] is True
    assert result["independent_days"] == 1
    assert result["fresh_confirmation_candidate"] is False
    assert "minimum_independent_days" in result["failed_quality_gates"]
    assert "single_day_concentration" in result["failed_quality_gates"]


def test_diversified_positive_policy_passes_predeclared_quality_screen() -> None:
    start = datetime(2026, 7, 1, 10, 0, tzinfo=timezone.utc)
    rows = [row(start + timedelta(days=index), 0.30) for index in range(30)]
    result = quality.evaluate_policy_lab_candidate(rows, policy_key="probe", cohort_id="coh_probe")
    assert result["triggered"] == 30
    assert result["independent_days"] == 30
    assert result["independent_weeks"] >= 4
    assert result["multiplicity_adjusted_one_sided_lower_bound_r"] > 0
    assert result["fresh_confirmation_candidate"] is True
    assert result["fresh_confirmation_required"] is True
    assert result["selection_cohort_may_confirm_winner"] is False


def test_multiplicity_adjustment_is_declared_for_all_seven_policies() -> None:
    protocol = quality.policy_lab_protocol_definition()
    assert protocol["simultaneous_policy_count"] == 7
    assert protocol["multiplicity_method"] == "Bonferroni one-sided lower bound"
    assert abs(protocol["per_policy_alpha"] - (0.05 / 7.0)) < 1e-12


def test_published_sample_count_alone_never_supports_edge() -> None:
    at = datetime(2026, 9, 22, 10, 0, tzinfo=timezone.utc)
    rows = [row(at + timedelta(minutes=index), 1.0) for index in range(30)]
    result = quality.evaluate_published_paper(rows, cohort_id="coh_paper")
    assert result["triggered"] == 30
    assert result["independent_days"] == 1
    assert result["forward_net_supported"] is False
    assert result["grade"] == "EVIDENCE_CLUSTERED"
    assert result["sample_count_alone_never_proves_edge"] is True


def test_historical_proxy_protocol_is_screening_only() -> None:
    protocol = quality.historical_proxy_protocol_definition()
    assert protocol["prospective_validation_eligible"] is False
    assert protocol["historical_proxy_may_auto_promote"] is False
    assert protocol["fresh_forward_confirmation_required"] is True
