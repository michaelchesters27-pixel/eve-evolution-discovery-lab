from app.services.fabric_outcome_backfill_v1 import (
    APPLY_LIMIT,
    OUTCOME_BACKFILL_VERSION,
    build_outcome_update,
)


def _candidate():
    return {
        "candle_time": "2026-08-20T10:00:00+00:00",
        "open": 100.0,
        "high": 101.0,
        "low": 99.5,
        "close": 100.0,
        "atr_14": 1.0,
        "outcome_complete": False,
    }


def _future(count=48):
    rows = []
    for index in range(count):
        close = 100.0 + (index + 1) * 0.05
        rows.append(
            {
                "candle_time": f"future-{index}",
                "open": close - 0.02,
                "high": close + 0.10,
                "low": close - 0.10,
                "close": close,
            }
        )
    return rows


def test_mature_row_gets_all_five_original_horizons():
    update = build_outcome_update(_candidate(), _future(48))

    assert update is not None
    assert update["candle_time"] == "2026-08-20T10:00:00+00:00"
    assert update["outcome_horizons"] == [5, 15, 30, 60, 240]
    assert set(update["outcomes"]) == {"5", "15", "30", "60", "240"}


def test_row_with_fewer_than_48_actual_future_bars_stays_incomplete():
    assert build_outcome_update(_candidate(), _future(47)) is None


def test_backfill_is_bounded_and_does_not_relax_integrity_gate():
    assert APPLY_LIMIT <= 1000
    assert OUTCOME_BACKFILL_VERSION == "eve-fabric-outcome-backfill-v1"

    from pathlib import Path

    source = (Path(__file__).resolve().parents[1] / "app" / "services" / "fabric_outcome_backfill_v1.py").read_text(
        encoding="utf-8"
    )
    assert '"historical_outcome_gate": 0.995' in source
    assert '"quality_gate_relaxed": False' in source
    assert "apply_fabric_outcome_backfill" in source
    assert "resolve_dataset_state" in source
