from app.services.live_trader_intelligence_indicator_v33 import score_intelligence


def test_intelligence_index_stays_conservative_without_evidence() -> None:
    result = score_intelligence({})
    assert result["brain"] == 9.0
    assert result["experience"] == 0.0
    assert result["applied_learning"] == 0.0
    assert result["overall"] < 5.0
    assert "not a profitability score" in result["meaning"]


def test_intelligence_index_rises_with_valid_evidence_and_maturity() -> None:
    early = score_intelligence(
        {
            "forward_scored": 30,
            "forward_days": 1,
            "historical_scored": 450,
            "challenger_runs": 950,
            "combined_families": 130,
            "mature_forward_families": 0,
            "historical_seed_families": 4,
            "historically_deep_families": 9,
            "execution_discoveries": 7,
        }
    )
    mature = score_intelligence(
        {
            "forward_scored": 500,
            "forward_days": 90,
            "historical_scored": 10000,
            "challenger_runs": 25000,
            "combined_families": 320,
            "mature_forward_families": 12,
            "historical_seed_families": 24,
            "historically_deep_families": 40,
            "execution_discoveries": 18,
        }
    )
    assert mature["experience"] > early["experience"]
    assert mature["applied_learning"] > early["applied_learning"]
    assert mature["overall"] > early["overall"]


def test_historical_volume_cannot_fake_mature_applied_learning() -> None:
    result = score_intelligence(
        {
            "forward_scored": 5,
            "forward_days": 1,
            "historical_scored": 20000,
            "challenger_runs": 50000,
            "combined_families": 400,
            "mature_forward_families": 0,
            "historical_seed_families": 30,
            "historically_deep_families": 50,
            "execution_discoveries": 20,
        }
    )
    assert result["experience"] > 6.0
    assert result["applied_learning"] < 6.0
    assert "no setup family" in result["explanation"]


def test_milestones_are_exposed_for_visible_progress() -> None:
    result = score_intelligence({"forward_scored": 30, "historical_scored": 450})
    milestones = {item["label"]: item for item in result["milestones"]}
    assert milestones["Forward scored outcomes"]["target"] == 50
    assert milestones["Historical scored episodes"]["target"] == 500
