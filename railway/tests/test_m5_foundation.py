from datetime import datetime, timedelta, timezone

from app.services.m5_foundation import LOOKBACK_BARS, build_m5_snapshot


def bar(time, o, h, l, c):
    return {
        "candle_time": time.isoformat(),
        "open": o,
        "high": h,
        "low": l,
        "close": c,
        "volume": 1,
    }


def test_every_m5_snapshot_preserves_legacy_fields_and_new_mtf_context():
    start = datetime(2026, 8, 18, 0, 0, tzinfo=timezone.utc)
    history = []
    price = 100.0
    for index in range(LOOKBACK_BARS):
        time = start + timedelta(minutes=5 * index)
        close = price + 0.05
        history.append(bar(time, price, close + 0.2, price - 0.2, close))
        price = close

    current_time = start + timedelta(minutes=5 * LOOKBACK_BARS)
    current = bar(current_time, price, price + 1.0, price - 0.5, price + 0.6)
    future = []
    future_price = current["close"]
    for index in range(48):
        time = current_time + timedelta(minutes=5 * (index + 1))
        close = future_price + 0.1
        future.append(bar(time, future_price, close + 0.2, future_price - 0.1, close))
        future_price = close

    fabric = {
        "fabric_version": "test-fabric",
        "decision_time": (current_time + timedelta(minutes=5)).isoformat(),
        "M1": {"available": True, "path_efficiency": 0.8},
        "M5": {"direction": 1, "return_pct": 0.1},
        "M15": {"direction": 1, "return_pct": 0.2},
        "M30": {"direction": 1, "return_pct": 0.3},
        "H1": {"direction": -1, "return_pct": -0.4},
        "H4": {"direction": 1, "return_pct": 0.5},
        "D1": {"direction": 1, "return_pct": 0.6},
    }
    snapshot = build_m5_snapshot("XAU/USD", history, current, future, fabric)

    assert snapshot["snapshot_interval"] == "5min"
    assert snapshot["source_interval"] == "5min"
    assert snapshot["candle_time"] == current_time.isoformat()
    assert snapshot["context_m15_return_pct"] == 0.2
    assert snapshot["context_m30_return_pct"] == 0.3
    assert snapshot["context_h1_return_pct"] == -0.4
    assert snapshot["context_h4_return_pct"] == 0.5
    assert snapshot["context_d1_return_pct"] == 0.6
    # Legacy alignment intentionally remains M15/H1/H4/D1 only: +1-1+1+1 = 2.
    assert snapshot["alignment_score"] == 2
    assert snapshot["mtf_context"]["M1"]["available"] is True
    assert snapshot["outcome_complete"] is True
    assert set(snapshot["outcomes"]) == {"5", "15", "30", "60", "240"}


def test_future_candles_only_change_labels_not_features():
    start = datetime(2026, 8, 18, 0, 0, tzinfo=timezone.utc)
    history = [bar(start + timedelta(minutes=5 * i), 100 + i * 0.01, 101 + i * 0.01, 99 + i * 0.01, 100.2 + i * 0.01) for i in range(LOOKBACK_BARS)]
    current_time = start + timedelta(minutes=5 * LOOKBACK_BARS)
    current = bar(current_time, 103, 104, 102, 103.5)
    up_future = [bar(current_time + timedelta(minutes=5 * (i + 1)), 103.5, 110 + i, 103, 109 + i) for i in range(48)]
    down_future = [bar(current_time + timedelta(minutes=5 * (i + 1)), 103.5, 104, 90 - i, 91 - i) for i in range(48)]
    fabric = {"M1": {"available": False}, "M5": {"direction": 1, "return_pct": 0.1}, "M15": None, "M30": None, "H1": None, "H4": None, "D1": None}

    up = build_m5_snapshot("XAU/USD", history, current, up_future, fabric)
    down = build_m5_snapshot("XAU/USD", history, current, down_future, fabric)
    feature_keys = [
        "atr_14", "average_range_12", "volatility_12", "compression_ratio",
        "return_1_pct", "return_3_pct", "return_12_pct", "return_48_pct",
        "return_288_pct", "trend_12_atr", "trend_48_atr", "streak", "regime",
    ]
    for key in feature_keys:
        assert up[key] == down[key]
    assert up["outcomes"] != down["outcomes"]
