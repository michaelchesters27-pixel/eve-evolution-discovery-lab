from datetime import datetime, timedelta, timezone

from app.services.evidence_miner import _bh_adjust, _returns_by_horizon, mine_evidence


def test_bh_adjust_is_monotone_and_bounded():
    rows = [
        {"p_value": 0.001},
        {"p_value": 0.01},
        {"p_value": 0.02},
        {"p_value": 0.20},
    ]
    _bh_adjust(rows)
    q_values = [row["q_value"] for row in rows]
    assert all(0.0 <= value <= 1.0 for value in q_values)
    assert q_values[0] <= q_values[1] <= q_values[2] <= q_values[3]


def test_120_minute_label_refuses_market_gap():
    start = datetime(2026, 1, 2, 10, 0, tzinfo=timezone.utc)
    rows = []
    for index in range(25):
        timestamp = start + timedelta(minutes=index * 5)
        if index == 24:
            timestamp += timedelta(days=2)
        rows.append({"candle_time": timestamp.isoformat(), "close": 100 + index, "outcomes": {}})
    returns = _returns_by_horizon(rows)
    assert returns[120][0] is None


def test_miner_finds_repeatable_london_outcome_shift():
    rows = []
    for year in (2021, 2022, 2023):
        start = datetime(year, 1, 4, 0, 0, tzinfo=timezone.utc)
        for index in range(360):
            is_london = index % 3 == 0
            effect = 0.30 if is_london else -0.08
            timestamp = start + timedelta(minutes=index * 5)
            rows.append(
                {
                    "candle_time": timestamp.isoformat(),
                    "open": 100.0,
                    "high": 100.2,
                    "low": 99.8,
                    "close": 100.0,
                    "direction": 1 if index % 2 == 0 else -1,
                    "session": "london" if is_london else "off_session",
                    "regime": "range",
                    "close_location": 0.5,
                    "alignment_score": 0,
                    "return_1_pct": 0.0,
                    "return_3_pct": 0.0,
                    "trend_12_atr": 0.0,
                    "trend_48_atr": 0.0,
                    "body_price": 0.05,
                    "upper_wick": 0.05,
                    "lower_wick": 0.05,
                    "outcomes": {
                        "15": {"close_return_pct": effect * 0.5},
                        "30": {"close_return_pct": effect * 0.7},
                        "60": {"close_return_pct": effect},
                        "240": {"close_return_pct": effect * 1.2},
                    },
                }
            )

    result = mine_evidence(rows)
    london_60 = [
        item
        for item in result["rows"]
        if item["feature_keys"] == ["schedule:session:london"] and item["horizon_minutes"] == 60
    ]
    assert london_60
    assert london_60[0]["status"] == "signal"
    assert london_60[0]["direction"] == "up"
    assert london_60[0]["q_value"] <= 0.10
    assert london_60[0]["year_stability"] >= 0.60
