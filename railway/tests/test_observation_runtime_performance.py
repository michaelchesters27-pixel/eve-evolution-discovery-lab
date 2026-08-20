from app.services.backtest_v3 import OBSERVATION_VERSION, enrich_market_observations


def row(minute: int, close: float) -> dict:
    return {
        "candle_time": f"2026-01-05T10:{minute:02d}:00+00:00",
        "open": close - 0.1,
        "high": close + 0.2,
        "low": close - 0.2,
        "close": close,
        "direction": 1,
        "atr_14": 1.0,
        "average_range_12": 0.4,
        "range_price": 0.4,
        "compression_ratio": 1.0,
        "session": "london",
    }


def test_enriched_chronological_list_returns_same_object_without_resort():
    rows = [row(0, 100.0), row(5, 100.2), row(10, 100.4)]
    enriched = enrich_market_observations(rows)
    assert enriched is rows
    assert all(item.get("observation_version") == OBSERVATION_VERSION for item in rows)

    again = enrich_market_observations(rows)
    assert again is rows


def test_appended_raw_tail_is_enriched_without_changing_list_identity():
    rows = [row(0, 100.0), row(5, 100.2), row(10, 100.4)]
    enrich_market_observations(rows)
    rows.append(row(15, 100.6))
    assert rows[-1].get("observation_version") is None

    result = enrich_market_observations(rows)
    assert result is rows
    assert rows[-1]["observation_version"] == OBSERVATION_VERSION


def test_unsorted_input_is_still_sorted_for_causal_enrichment():
    rows = [row(10, 100.4), row(0, 100.0), row(5, 100.2)]
    result = enrich_market_observations(rows)
    assert [item["candle_time"] for item in result] == sorted(item["candle_time"] for item in rows)
