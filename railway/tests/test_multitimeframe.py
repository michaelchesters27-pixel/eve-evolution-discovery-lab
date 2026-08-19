from datetime import datetime, timedelta, timezone

from app.services.multitimeframe import (
    CompletedCandleIndex,
    aggregate_m30,
    build_fabric_context,
    m1_microstructure,
)


def candle(time, o, h, l, c):
    return {
        "candle_time": time.isoformat(),
        "open": o,
        "high": h,
        "low": l,
        "close": c,
        "volume": 1,
    }


def test_h1_context_uses_only_completed_candle():
    nine = datetime(2026, 8, 19, 9, 0, tzinfo=timezone.utc)
    ten = datetime(2026, 8, 19, 10, 0, tzinfo=timezone.utc)
    index = CompletedCandleIndex(
        [
            candle(nine, 100, 102, 99, 101),
            candle(ten, 101, 110, 100, 109),
        ],
        "1h",
    )
    # An M5 candle starting 10:35 becomes known at 10:40. The 10:00 H1
    # candle is still open, so only the 09:00 H1 candle is legal context.
    at_1040 = index.at(datetime(2026, 8, 19, 10, 40, tzinfo=timezone.utc))
    assert at_1040 is not None
    assert at_1040["candle_time"] == nine.isoformat()

    at_1100 = index.at(datetime(2026, 8, 19, 11, 0, tzinfo=timezone.utc))
    assert at_1100 is not None
    assert at_1100["candle_time"] == ten.isoformat()


def test_m30_is_derived_from_exact_six_m5_bars():
    start = datetime(2026, 8, 19, 10, 0, tzinfo=timezone.utc)
    rows = [
        candle(start + timedelta(minutes=5 * i), 100 + i, 102 + i, 99 + i, 101 + i)
        for i in range(6)
    ]
    derived = aggregate_m30(rows)
    assert len(derived) == 1
    assert derived[0]["candle_time"] == start.isoformat()
    assert derived[0]["open"] == 100
    assert derived[0]["close"] == 106
    assert derived[0]["high"] == 107
    assert derived[0]["low"] == 99

    # Missing one constituent bar means no synthetic M30 candle is allowed.
    assert aggregate_m30(rows[:-1]) == []


def test_m1_microstructure_describes_only_the_completed_signal_m5_path():
    start = datetime(2026, 8, 19, 10, 35, tzinfo=timezone.utc)
    signal = candle(start, 100, 103, 99, 102)
    m1 = [
        candle(start + timedelta(minutes=0), 100.0, 101.0, 99.8, 100.8),
        candle(start + timedelta(minutes=1), 100.8, 101.3, 100.5, 101.2),
        candle(start + timedelta(minutes=2), 101.2, 101.4, 100.7, 100.9),
        candle(start + timedelta(minutes=3), 100.9, 102.0, 100.8, 101.8),
        candle(start + timedelta(minutes=4), 101.8, 103.0, 101.7, 102.0),
        # This next bar belongs to the next M5 candle and must be ignored.
        candle(start + timedelta(minutes=5), 102.0, 105.0, 101.9, 104.5),
    ]
    micro = m1_microstructure(signal, m1)
    assert micro["available"] is True
    assert micro["bars"] == 5
    assert micro["direction"] == 1
    assert micro["bullish_minutes"] == 4
    assert micro["bearish_minutes"] == 1
    assert micro["direction_changes"] == 2
    assert micro["high"] == 103.0


def test_fabric_context_is_auditable_at_m5_decision_time():
    signal_time = datetime(2026, 8, 19, 10, 35, tzinfo=timezone.utc)
    signal = candle(signal_time, 100, 102, 99, 101)
    m1 = [candle(signal_time + timedelta(minutes=i), 100 + i * 0.1, 100.5 + i * 0.1, 99.8 + i * 0.1, 100.3 + i * 0.1) for i in range(5)]

    m15 = CompletedCandleIndex(
        [candle(datetime(2026, 8, 19, 10, 15, tzinfo=timezone.utc), 99, 102, 98, 101)],
        "15min",
    )
    m30 = CompletedCandleIndex(
        [candle(datetime(2026, 8, 19, 10, 0, tzinfo=timezone.utc), 98, 103, 97, 101)],
        "30min",
    )
    h1 = CompletedCandleIndex(
        [
            candle(datetime(2026, 8, 19, 9, 0, tzinfo=timezone.utc), 95, 102, 94, 101),
            candle(datetime(2026, 8, 19, 10, 0, tzinfo=timezone.utc), 101, 109, 100, 108),
        ],
        "1h",
    )
    h4 = CompletedCandleIndex(
        [candle(datetime(2026, 8, 19, 4, 0, tzinfo=timezone.utc), 90, 103, 89, 101)],
        "4h",
    )
    d1 = CompletedCandleIndex(
        [candle(datetime(2026, 8, 18, 0, 0, tzinfo=timezone.utc), 85, 105, 80, 100)],
        "1day",
    )

    context = build_fabric_context(
        signal,
        m1_rows=m1,
        m15_index=m15,
        m30_index=m30,
        h1_index=h1,
        h4_index=h4,
        d1_index=d1,
    )
    decision = datetime.fromisoformat(context["decision_time"])
    assert decision == signal_time + timedelta(minutes=5)
    assert context["H1"]["candle_time"] == datetime(2026, 8, 19, 9, 0, tzinfo=timezone.utc).isoformat()
    assert context["M1"]["available"] is True
    assert context["context_complete"] is True
    for label in ("M5", "M15", "M30", "H1", "H4", "D1"):
        assert datetime.fromisoformat(context[label]["completed_at"]) <= decision
