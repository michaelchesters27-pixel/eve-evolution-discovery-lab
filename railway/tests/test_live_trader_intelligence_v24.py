from __future__ import annotations

from datetime import datetime, timedelta, timezone

from app.services import live_trader_learning_v2 as v2
from app.services import live_trader_intelligence_v24 as v24


def tf(direction: int, *, body_ratio: float = 0.7, close_location: float | None = None) -> dict:
    if close_location is None:
        close_location = 0.85 if direction > 0 else 0.15 if direction < 0 else 0.5
    return {
        "direction": direction,
        "return_pct": 0.25 * direction,
        "range_price": 10.0,
        "body_abs": 10.0 * body_ratio,
        "close_location": close_location,
    }


def latest_row(*, m1_direction: int = -1, trend: float = 0.16, return_12: float = 0.35, return_48: float = 0.8) -> dict:
    return {
        "close": 4600.0,
        "atr_14": 6.0,
        "regime": "trend_up",
        "trend_12_atr": trend,
        "trend_48_atr": trend * 0.8,
        "return_12_pct": return_12,
        "return_48_pct": return_48,
        "mtf_context": {
            "D1": tf(1, body_ratio=0.75),
            "H4": tf(1, body_ratio=0.80),
            "H1": tf(1, body_ratio=0.65),
            "M30": tf(1, body_ratio=0.60),
            "M15": tf(1, body_ratio=0.55),
            "M5": tf(-1, body_ratio=0.25, close_location=0.45),
            "M1": {"direction": m1_direction},
            "higher_timeframe_alignment_score": 4,
            "direction_alignment_score": 4,
        },
    }


def test_bias_v24_uses_richer_structure_and_excludes_m1() -> None:
    trader = v2.LiveTrader.__new__(v2.LiveTrader)
    first, first_score = v24._bias_v24(trader, latest_row(m1_direction=-1))
    second, second_score = v24._bias_v24(trader, latest_row(m1_direction=1))

    assert first["overall"] == "bullish"
    assert first["engine_version"] == v24.BIAS_VERSION
    assert first["components"]["momentum_score"] > 0
    assert first["timeframes"]["M1"]["weight"] == 0
    assert first_score == second_score


def test_bias_v24_does_not_force_direction_when_structure_and_momentum_conflict() -> None:
    trader = v2.LiveTrader.__new__(v2.LiveTrader)
    row = latest_row(trend=-0.22, return_12=-0.55, return_48=-1.1)
    row["regime"] = "range"
    row["mtf_context"]["M30"] = tf(-1, body_ratio=0.8)
    row["mtf_context"]["M15"] = tf(-1, body_ratio=0.8)
    row["mtf_context"]["M5"] = tf(-1, body_ratio=0.8)

    bias, _ = v24._bias_v24(trader, row)

    assert bias["overall"] == "neutral"
    assert bias["components"]["structural_score"] > 0
    assert bias["components"]["momentum_score"] < 0


def bar(start: datetime, close: float, *, high: float | None = None, low: float | None = None) -> dict:
    return {
        "candle_time": start.isoformat(),
        "open": close,
        "high": high if high is not None else close + 0.5,
        "low": low if low is not None else close - 0.5,
        "close": close,
    }


def test_exact_horizon_endpoint_never_uses_candle_extending_past_horizon() -> None:
    observed = datetime(2026, 8, 21, 10, 2, tzinfo=timezone.utc)
    horizon = observed + timedelta(minutes=60)
    rows = [
        bar(datetime(2026, 8, 21, 10, 0, tzinfo=timezone.utc), 100.0),
        bar(datetime(2026, 8, 21, 10, 5, tzinfo=timezone.utc), 101.0),
        bar(datetime(2026, 8, 21, 10, 55, tzinfo=timezone.utc), 109.0),
        bar(datetime(2026, 8, 21, 11, 0, tzinfo=timezone.utc), 999.0),
    ]

    endpoint = v24._horizon_endpoint(rows, observed, horizon)

    assert endpoint is not None
    price, price_time = endpoint
    assert price == 109.0
    assert price_time == datetime(2026, 8, 21, 11, 0, tzinfo=timezone.utc)


def test_trade_path_excludes_partial_start_and_post_horizon_bars() -> None:
    observed = datetime(2026, 8, 21, 10, 2, tzinfo=timezone.utc)
    horizon = observed + timedelta(minutes=60)
    rows = [
        bar(datetime(2026, 8, 21, 10, 0, tzinfo=timezone.utc), 100.0, high=200.0, low=1.0),
        bar(datetime(2026, 8, 21, 10, 5, tzinfo=timezone.utc), 101.0),
        bar(datetime(2026, 8, 21, 10, 55, tzinfo=timezone.utc), 109.0),
        bar(datetime(2026, 8, 21, 11, 0, tzinfo=timezone.utc), 110.0, high=500.0, low=1.0),
    ]

    completed = v24._fully_completed_bars(rows, observed, horizon)

    assert [row["candle_time"] for row in completed] == [
        datetime(2026, 8, 21, 10, 5, tzinfo=timezone.utc).isoformat(),
        datetime(2026, 8, 21, 10, 55, tzinfo=timezone.utc).isoformat(),
    ]


def test_v24_starts_a_fresh_learning_namespace() -> None:
    assert v2.LEARNING_VERSION == v24.LEARNING_VERSION
    assert v24.LEARNING_VERSION == "eve-live-learning-v2.4"
