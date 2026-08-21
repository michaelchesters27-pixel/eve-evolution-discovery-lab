from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timedelta, timezone
import math

from app.services import memory_guard_v1 as guard


STRUCTURE_CONDITIONS = [
    {"type": "sweep_prior_12_high_reclaim"},
    {"type": "sweep_prior_12_low_reclaim"},
    {"type": "break_prior_12_high"},
    {"type": "break_prior_12_low"},
    {"type": "prev_day_high_sweep_reclaim"},
    {"type": "prev_day_low_sweep_reclaim"},
    {"type": "prev_day_high_break"},
    {"type": "prev_day_low_break"},
    {"type": "session_high_sweep_reclaim"},
    {"type": "session_low_sweep_reclaim"},
    {"type": "displacement_atr_min", "min": 0.35},
    {"type": "range_expansion_min", "min": 1.20},
    {"type": "range_position_high", "min": 0.80},
    {"type": "range_position_low", "max": 0.20},
    {"type": "compression_release"},
    {"type": "three_bar_same_direction"},
]


def _base_rows(count: int = 700) -> list[dict]:
    start = datetime(2024, 1, 2, 0, 0, tzinfo=timezone.utc)
    rows: list[dict] = []
    price = 2000.0
    for index in range(count):
        timestamp = start + timedelta(minutes=5 * index)
        # Deterministic waves create breaks, sweeps, trends and compressions.
        wave = math.sin(index / 11.0) * 1.7 + math.sin(index / 37.0) * 2.3
        impulse = 4.5 if index % 79 == 0 else -4.2 if index % 113 == 0 else 0.0
        body = (0.75 if index % 5 in (0, 1, 2) else -0.62) + wave * 0.08 + impulse
        open_price = price
        close = open_price + body
        wick_up = 0.55 + (2.4 if index % 97 == 0 else 0.0)
        wick_down = 0.48 + (2.7 if index % 89 == 0 else 0.0)
        high = max(open_price, close) + wick_up
        low = min(open_price, close) - wick_down
        range_price = high - low
        atr = 2.0 + abs(math.sin(index / 17.0)) * 0.8
        avg_range = 2.2 + abs(math.sin(index / 23.0)) * 0.5
        compression = 0.62 if index % 31 == 0 else 1.02 + math.sin(index / 13.0) * 0.18
        hour = timestamp.hour
        session = "asia" if hour < 7 else "london" if hour < 12 else "new_york" if hour < 17 else "off_session"
        direction = 1 if close > open_price else -1 if close < open_price else 0
        rows.append(
            {
                "candle_time": timestamp.isoformat(),
                "open": open_price,
                "high": high,
                "low": low,
                "close": close,
                "atr_14": atr,
                "average_range_12": avg_range,
                "range_price": range_price,
                "compression_ratio": compression,
                "direction": direction,
                "session": session,
                "regime": "compression" if compression < 0.72 else "trend_up" if direction > 0 else "trend_down",
                "weekday": timestamp.isoweekday(),
                "month": timestamp.month,
                "hour_utc": timestamp.hour,
                "alignment_score": 2 if index % 3 else -1,
                "trend_12_atr": body / max(atr, 0.01),
                "return_3_pct": body * 0.01,
                "return_12_pct": wave * 0.01,
                "return_48_pct": math.sin(index / 41.0) * 0.08,
            }
        )
        price = close
    return rows


def _rows_with_outcomes(count: int = 1800) -> list[dict]:
    rows = _base_rows(count)
    for index, row in enumerate(rows):
        direction = int(row["direction"])
        base = (0.045 if direction > 0 else -0.038) + math.sin(index / 19.0) * 0.025
        row["outcomes"] = {
            "15": {"close_return_pct": base * 0.65, "direction": "up" if base > 0 else "down"},
            "30": {"close_return_pct": base * 0.85, "direction": "up" if base > 0 else "down"},
            "60": {"close_return_pct": base, "direction": "up" if base > 0 else "down"},
            "240": {"close_return_pct": base * 1.35, "direction": "up" if base > 0 else "down"},
        }
    return rows


def test_compact_observations_match_original_structure_semantics() -> None:
    raw = _base_rows()
    old_rows = guard._ORIGINAL_ENRICH(deepcopy(raw))
    compact_rows = guard.compact_enrich_market_observations(deepcopy(raw))

    assert len(old_rows) == len(compact_rows)
    for old, compact in zip(old_rows, compact_rows):
        assert guard.OBS_KEY in compact
        assert not any(key.startswith("obs_") for key in compact)
        for condition in STRUCTURE_CONDITIONS:
            assert guard._ORIGINAL_RECIPE(old, condition) == guard.compact_recipe_condition_matches(compact, condition)
        for rule in ("structure_direction", "three_bar_direction"):
            rules = {"entry": {"direction_rule": rule}}
            assert guard._ORIGINAL_DIRECTION(old, rules) == guard.compact_candidate_direction(compact, rules)


def test_memory_bounded_evidence_miner_is_statistically_identical() -> None:
    rows = guard.compact_enrich_market_observations(_rows_with_outcomes())
    expected = guard._ORIGINAL_MINE_EVIDENCE(rows)
    actual = guard.memory_bounded_mine_evidence(rows)

    # The new implementation adds only an audit marker. All scientific output
    # must remain byte-for-byte equivalent as Python values.
    actual = dict(actual)
    assert actual.pop("memory_guard_version") == guard.MEMORY_GUARD_VERSION
    assert actual == expected


def test_guard_reports_bounded_working_memory_policy() -> None:
    status = guard.runtime_status()
    assert status["persistent_observation_fields_per_row"] == 1
    assert "byte masks" in status["evidence_match_policy"]
    assert status["research_semantics"] == "unchanged"
