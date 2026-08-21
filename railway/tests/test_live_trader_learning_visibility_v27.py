from datetime import datetime, timezone

from app.services.live_trader_learning_visibility_v27 import summarise_learning_rows


def test_learning_summary_counts_open_and_resolved_progress() -> None:
    rows = [
        {
            "status": "open",
            "observed_at": "2026-08-21T13:06:00+00:00",
            "horizon_minutes": 60,
            "setup_family": "family-a",
            "episode_key": "episode-1",
            "learning_success": None,
            "direction_correct": None,
            "trade_outcome": None,
        },
        {
            "status": "resolved",
            "observed_at": "2026-08-21T12:00:00+00:00",
            "horizon_minutes": 60,
            "setup_family": "family-b",
            "episode_key": "episode-2",
            "learning_success": True,
            "direction_correct": True,
            "trade_outcome": "target",
        },
    ]

    summary = summarise_learning_rows(rows, 60)

    assert summary["recorded"] == 2
    assert summary["open"] == 1
    assert summary["resolved"] == 1
    assert summary["scored"] == 1
    assert summary["correct"] == 1
    assert summary["accuracy"] == 1.0
    assert summary["families_seen"] == 2
    assert summary["independent_episodes"] == 2
    assert summary["next_due_at"] == "2026-08-21T14:06:00+00:00"


def test_learning_summary_uses_earliest_open_due_time() -> None:
    rows = [
        {
            "status": "open",
            "observed_at": datetime(2026, 8, 21, 13, 16, tzinfo=timezone.utc).isoformat(),
            "horizon_minutes": 60,
            "setup_family": "family-b",
            "episode_key": "episode-1",
        },
        {
            "status": "open",
            "observed_at": datetime(2026, 8, 21, 13, 6, tzinfo=timezone.utc).isoformat(),
            "horizon_minutes": 60,
            "setup_family": "family-a",
            "episode_key": "episode-1",
        },
    ]

    summary = summarise_learning_rows(rows, 60)

    assert summary["recorded"] == 2
    assert summary["resolved"] == 0
    assert summary["next_due_at"] == "2026-08-21T14:06:00+00:00"
