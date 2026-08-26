from __future__ import annotations

from app.services import live_trader_mtf_zones_v63 as mtf
from app.services import live_trader_zone_ranking_v62 as ranking


def test_fresh_high_quality_zone_beats_closer_retested_zone() -> None:
    clean = {
        "quality": 99,
        "fresh": True,
        "retests": 0,
        "departure_atr": 3.2,
        "distance_atr": 7.0,
    }
    closer_used = {
        "quality": 88,
        "fresh": False,
        "retests": 2,
        "departure_atr": 3.8,
        "distance_atr": 5.8,
    }
    assert ranking._rank_score(clean) > ranking._rank_score(closer_used)


def test_h1_and_m15_overlap_gets_full_execution_role() -> None:
    m5 = {"low": 100.0, "high": 102.0, "quality": 86, "rank_score": 90.0}
    h1 = [{"low": 99.0, "high": 104.0, "quality": 88}]
    m15 = [{"low": 100.5, "high": 103.0, "quality": 90}]
    result = mtf._confluence(m5, h1, m15, 2.0)
    assert result["h1_confluence"] is True
    assert result["m15_confluence"] is True
    assert result["mtf_confluence_count"] == 2
    assert result["zone_role"] == "H1_ZONE_M15_REFINEMENT_M5_EXECUTION"
    assert result["rank_score"] > 90.0


def test_m15_only_overlap_is_labelled_honestly() -> None:
    m5 = {"low": 100.0, "high": 102.0, "quality": 86, "rank_score": 90.0}
    h1 = [{"low": 110.0, "high": 112.0, "quality": 95}]
    m15 = [{"low": 100.5, "high": 103.0, "quality": 90}]
    result = mtf._confluence(m5, h1, m15, 2.0)
    assert result["h1_confluence"] is False
    assert result["m15_confluence"] is True
    assert result["mtf_confluence_count"] == 1
    assert result["zone_role"] == "M15_BACKED_M5_EXECUTION"


def test_native_timeframe_source_ignores_unfinished_candles() -> None:
    rows = [
        {
            "mtf_context": {
                "M15": {
                    "candle_time": "2026-08-26T10:00:00+00:00",
                    "completed_at": "2026-08-26T10:15:00+00:00",
                    "open": 100.0,
                    "high": 103.0,
                    "low": 99.0,
                    "close": 102.0,
                }
            }
        },
        {
            "mtf_context": {
                "M15": {
                    "candle_time": "2026-08-26T10:15:00+00:00",
                    "completed_at": None,
                    "open": 102.0,
                    "high": 104.0,
                    "low": 101.0,
                    "close": 103.0,
                }
            }
        },
    ]
    bars = mtf._unique_tf_bars(rows, "M15")
    assert len(bars) == 1
    assert bars[0]["candle_time"] == "2026-08-26T10:00:00+00:00"
