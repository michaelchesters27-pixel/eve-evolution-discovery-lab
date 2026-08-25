from __future__ import annotations

from app.services import live_trader_management_learning_v52 as v52


def test_management_replay_conservatively_scores_profit_protection() -> None:
    campaign = {
        "side": "BUY",
        "entry": 100.0,
        "stop": 99.0,
        "target": 105.0,
        "triggered_at": "2026-08-25T12:00:30+00:00",
        "completed_at": "2026-08-25T12:05:20+00:00",
    }
    bars = [
        # Partial trigger candle: deliberately ignored by the replay.
        {"candle_time": "2026-08-25T12:00:00+00:00", "low": 99.2, "high": 102.5},
        # +1R observed. BE can only become active from the next full bar.
        {"candle_time": "2026-08-25T12:01:00+00:00", "low": 99.5, "high": 101.1},
        # +1.5R observed. 0.5R lock becomes active from the next full bar.
        {"candle_time": "2026-08-25T12:02:00+00:00", "low": 100.2, "high": 101.6},
        # 0.5R lock is stopped here; +2R rule arms for its own path.
        {"candle_time": "2026-08-25T12:03:00+00:00", "low": 100.4, "high": 102.1},
        # 1R lock is active here and is stopped conservatively.
        {"candle_time": "2026-08-25T12:04:00+00:00", "low": 100.9, "high": 102.2},
        # BE path would still be alive until this bar, then exits at entry.
        {"candle_time": "2026-08-25T12:05:00+00:00", "low": 99.8, "high": 100.8},
    ]

    replay = v52.management_replay(campaign, bars)

    assert replay["version"] == v52.MANAGEMENT_REPLAY_VERSION
    assert replay["diagnostic_only"] is True

    be = replay["results"]["be_after_1R"]
    assert be["trade_outcome"] == "protected_stop"
    assert be["realised_r"] == 0.0

    half = replay["results"]["lock_0.5R_after_1.5R"]
    assert half["trade_outcome"] == "protected_stop"
    assert half["realised_r"] == 0.5

    one = replay["results"]["lock_1R_after_2R"]
    assert one["trade_outcome"] == "protected_stop"
    assert one["realised_r"] == 1.0


def test_management_replay_sell_side_is_symmetric() -> None:
    campaign = {
        "side": "SELL",
        "entry": 100.0,
        "stop": 101.0,
        "target": 95.0,
        "triggered_at": "2026-08-25T12:00:30+00:00",
        "completed_at": "2026-08-25T12:03:20+00:00",
    }
    bars = [
        # +1R observed; BE becomes active from 12:02.
        {"candle_time": "2026-08-25T12:01:00+00:00", "low": 98.9, "high": 100.4},
        # +1.5R observed; 0.5R lock becomes active from 12:03.
        {"candle_time": "2026-08-25T12:02:00+00:00", "low": 98.3, "high": 99.8},
        # Price reaches +2R but also retraces through both protected stops.
        {"candle_time": "2026-08-25T12:03:00+00:00", "low": 98.0, "high": 100.1},
    ]

    replay = v52.management_replay(campaign, bars)

    assert replay["results"]["be_after_1R"]["trade_outcome"] == "protected_stop"
    assert replay["results"]["be_after_1R"]["realised_r"] == 0.0
    assert replay["results"]["lock_0.5R_after_1.5R"]["trade_outcome"] == "protected_stop"
    assert replay["results"]["lock_0.5R_after_1.5R"]["realised_r"] == 0.5
