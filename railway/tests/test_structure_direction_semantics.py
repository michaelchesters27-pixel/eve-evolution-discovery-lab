from datetime import datetime, timedelta, timezone

from app.services import backtest_v3 as research


def row(time, *, high, low, close):
    return {
        "symbol": "XAU/USD",
        "snapshot_interval": "15min",
        "source_interval": "5min",
        "candle_time": time.isoformat(),
        "open": close,
        "high": high,
        "low": low,
        "close": close,
        "direction": 1 if close >= 100 else -1,
        "atr_14": 2.0,
        "average_range_12": 2.0,
        "range_price": high - low,
        "compression_ratio": 1.0,
        "session": "london",
    }


def test_previous_day_high_break_is_bullish_and_low_break_is_bearish():
    start = datetime(2026, 8, 17, 8, 0, tzinfo=timezone.utc)
    prior = [row(start + timedelta(minutes=15 * i), high=105.0 if i == 2 else 103.0, low=95.0 if i == 4 else 97.0, close=100.0) for i in range(8)]

    high_break = prior + [row(datetime(2026, 8, 18, 8, 0, tzinfo=timezone.utc), high=107.0, low=101.0, close=106.0)]
    assert research.enrich_market_observations(high_break)[-1]["obs_structure_direction"] == 1

    # Use a fresh copy because enrichment mutates rows in place.
    prior2 = [row(start + timedelta(minutes=15 * i), high=105.0 if i == 2 else 103.0, low=95.0 if i == 4 else 97.0, close=100.0) for i in range(8)]
    low_break = prior2 + [row(datetime(2026, 8, 18, 8, 0, tzinfo=timezone.utc), high=99.0, low=93.0, close=94.0)]
    assert research.enrich_market_observations(low_break)[-1]["obs_structure_direction"] == -1
