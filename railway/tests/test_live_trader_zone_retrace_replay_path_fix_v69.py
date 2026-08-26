from app.services import live_trader_zone_retrace_replay_path_fix_v69 as v69


def test_perfect_zero_gap_and_zero_lag_path_is_complete() -> None:
    assert v69._path_complete_v69(
        {
            "endpoint_price": 100.0,
            "endpoint_time": "2026-08-26T10:00:00+00:00",
            "endpoint_lag_seconds": 0,
            "initial_gap_seconds": 0,
            "gap_count": 0,
        }
    ) is True


def test_missing_endpoint_is_not_complete() -> None:
    assert v69._path_complete_v69(
        {
            "endpoint_price": None,
            "endpoint_time": None,
            "endpoint_lag_seconds": 0,
            "initial_gap_seconds": 0,
            "gap_count": 0,
        }
    ) is False


def test_real_gap_is_not_complete() -> None:
    assert v69._path_complete_v69(
        {
            "endpoint_price": 100.0,
            "endpoint_time": "2026-08-26T10:00:00+00:00",
            "endpoint_lag_seconds": 0,
            "initial_gap_seconds": 0,
            "gap_count": 1,
        }
    ) is False
