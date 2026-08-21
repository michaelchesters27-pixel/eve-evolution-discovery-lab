from __future__ import annotations

"""P0 memory hardening for Discovery research.

The six-year Every-M5 fabric is intentionally large. This module keeps the
scientific semantics unchanged while removing two avoidable Python-heap
multipliers:

1. structure observations are encoded in one compact tuple per row instead of
   adding dozens of long-lived ``obs_*`` keys to every cached dictionary;
2. Evidence Miner evaluates one feature match list at a time and retains only
   byte masks for the small set of pair-candidate features.

It is imported from ``app.__init__`` before the Scientist binds the patched
helpers, so all research/live-recognition consumers see the same semantics.
"""

from collections import deque
from typing import Any, Iterable

from app.services import backtest_v3 as research

MEMORY_GUARD_VERSION = "eve-research-memory-guard-v1"
OBS_KEY = "_eve_obs"

# Compact tuple layout.
_BITS = 0
_RANGE_POSITION = 1
_DISPLACEMENT_ATR = 2
_RANGE_EXPANSION = 3
_THREE_BAR_DIRECTION = 4
_STRUCTURE_DIRECTION = 5

# Boolean observation bit positions.
_SWEEP12_HIGH = 1 << 0
_SWEEP12_LOW = 1 << 1
_BREAK12_HIGH = 1 << 2
_BREAK12_LOW = 1 << 3
_PDH_SWEEP = 1 << 4
_PDL_SWEEP = 1 << 5
_PDH_BREAK = 1 << 6
_PDL_BREAK = 1 << 7
_SESSION_HIGH_SWEEP = 1 << 8
_SESSION_LOW_SWEEP = 1 << 9
_COMPRESSION_RELEASE = 1 << 10
_THREE_BAR_SAME = 1 << 11

_ORIGINAL_ENRICH = research.enrich_market_observations
_ORIGINAL_RECIPE = research.recipe_condition_matches
_ORIGINAL_DIRECTION = research.candidate_direction
_V2_RECIPE = research._V2_RECIPE_CONDITION_MATCHES
_V2_DIRECTION = research._V2_CANDIDATE_DIRECTION
legacy = research.legacy


def _compact_ready(row: dict[str, Any]) -> bool:
    value = row.get(OBS_KEY)
    return isinstance(value, tuple) and len(value) >= 6


def compact_enrich_market_observations(rows: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    """Add causal structure state using one compact tuple per row.

    This intentionally reproduces the v3 observation semantics. Only values
    consumed by strategy conditions/direction are retained. Debug-only prior
    high/low fields are not materialised into every cached row.
    """
    source = rows if isinstance(rows, list) else list(rows)
    if not source:
        return source

    sample_indexes = {0, len(source) - 1, len(source) // 2}
    if all(_compact_ready(source[index]) for index in sample_indexes):
        return source

    chronological = all(
        str(source[index - 1].get("candle_time") or "") <= str(source[index].get("candle_time") or "")
        for index in range(1, len(source))
    )
    ordered = source if chronological else sorted(source, key=lambda row: str(row.get("candle_time") or ""))

    prior_highs: deque[float] = deque(maxlen=12)
    prior_lows: deque[float] = deque(maxlen=12)
    prior_directions: deque[int] = deque(maxlen=2)
    current_day: str | None = None
    day_high: float | None = None
    day_low: float | None = None
    previous_day_high: float | None = None
    previous_day_low: float | None = None
    session_highs: dict[str, float] = {}
    session_lows: dict[str, float] = {}
    previous_compression = 1.0

    for row in ordered:
        timestamp = legacy.as_utc(row.get("candle_time"))
        if timestamp is None:
            continue
        day = timestamp.date().isoformat()
        high = legacy.number(row.get("high"))
        low = legacy.number(row.get("low"))
        close = legacy.number(row.get("close"))
        open_price = legacy.number(row.get("open"))
        atr = max(legacy.number(row.get("atr_14")), 1e-9)

        if current_day != day:
            if current_day is not None:
                previous_day_high = day_high
                previous_day_low = day_low
            current_day = day
            day_high = None
            day_low = None
            # Old implementation keyed these by (day, session), so old days
            # could never be read again. Clearing them is semantically identical
            # and prevents needless six-year accumulation during enrichment.
            session_highs.clear()
            session_lows.clear()

        p12h = max(prior_highs) if prior_highs else None
        p12l = min(prior_lows) if prior_lows else None

        sweep12_high = bool(p12h is not None and high > p12h and close < p12h)
        sweep12_low = bool(p12l is not None and low < p12l and close > p12l)
        break12_high = bool(p12h is not None and close > p12h)
        break12_low = bool(p12l is not None and close < p12l)

        if p12h is not None and p12l is not None and p12h > p12l:
            range_position: float | None = (close - p12l) / (p12h - p12l)
        else:
            range_position = None

        pdh_sweep = bool(previous_day_high is not None and high > previous_day_high and close < previous_day_high)
        pdl_sweep = bool(previous_day_low is not None and low < previous_day_low and close > previous_day_low)
        pdh_break = bool(previous_day_high is not None and close > previous_day_high)
        pdl_break = bool(previous_day_low is not None and close < previous_day_low)

        session = str(row.get("session") or "unknown")
        prior_session_high = session_highs.get(session)
        prior_session_low = session_lows.get(session)
        session_high_sweep = bool(prior_session_high is not None and high > prior_session_high and close < prior_session_high)
        session_low_sweep = bool(prior_session_low is not None and low < prior_session_low and close > prior_session_low)

        average_range = max(legacy.number(row.get("average_range_12")), 1e-9)
        range_price = max(0.0, legacy.number(row.get("range_price"), high - low))
        displacement_atr = abs(close - open_price) / atr
        range_expansion = range_price / average_range
        current_compression = legacy.number(row.get("compression_ratio"), 1.0)
        compression_release = bool(previous_compression < 0.72 and current_compression >= 0.95)

        current_direction = legacy.sign(row.get("direction"))
        directions = [*prior_directions, current_direction]
        same_three = (
            len(directions) == 3
            and directions[0] != 0
            and directions[0] == directions[1] == directions[2]
        )
        three_bar_direction = directions[0] if same_three else 0

        bullish = (pdl_sweep, sweep12_low, pdh_break, break12_high)
        bearish = (pdh_sweep, sweep12_high, pdl_break, break12_low)
        if any(bullish) and not any(bearish):
            structure_direction = 1
        elif any(bearish) and not any(bullish):
            structure_direction = -1
        else:
            structure_direction = 0

        bits = 0
        for flag, bit in (
            (sweep12_high, _SWEEP12_HIGH),
            (sweep12_low, _SWEEP12_LOW),
            (break12_high, _BREAK12_HIGH),
            (break12_low, _BREAK12_LOW),
            (pdh_sweep, _PDH_SWEEP),
            (pdl_sweep, _PDL_SWEEP),
            (pdh_break, _PDH_BREAK),
            (pdl_break, _PDL_BREAK),
            (session_high_sweep, _SESSION_HIGH_SWEEP),
            (session_low_sweep, _SESSION_LOW_SWEEP),
            (compression_release, _COMPRESSION_RELEASE),
            (same_three, _THREE_BAR_SAME),
        ):
            if flag:
                bits |= bit

        row[OBS_KEY] = (
            bits,
            range_position,
            displacement_atr,
            range_expansion,
            three_bar_direction,
            structure_direction,
        )

        day_high = high if day_high is None else max(day_high, high)
        day_low = low if day_low is None else min(day_low, low)
        session_highs[session] = high if prior_session_high is None else max(prior_session_high, high)
        session_lows[session] = low if prior_session_low is None else min(prior_session_low, low)
        prior_highs.append(high)
        prior_lows.append(low)
        prior_directions.append(current_direction)
        previous_compression = current_compression

    return ordered


def _obs(row: dict[str, Any]) -> tuple[Any, ...] | None:
    value = row.get(OBS_KEY)
    return value if isinstance(value, tuple) and len(value) >= 6 else None


def compact_recipe_condition_matches(row: dict[str, Any], condition: dict[str, Any]) -> bool:
    kind = str(condition.get("type") or "")
    if kind not in research.STRUCTURE_CONDITION_TYPES:
        return _V2_RECIPE(row, condition)

    value = _obs(row)
    if value is None:
        # Compatibility for isolated tests/old rows that were enriched with the
        # pre-v1 representation rather than the process cache.
        return _ORIGINAL_RECIPE(row, condition)
    bits = int(value[_BITS])
    if kind == "sweep_prior_12_high_reclaim":
        return bool(bits & _SWEEP12_HIGH)
    if kind == "sweep_prior_12_low_reclaim":
        return bool(bits & _SWEEP12_LOW)
    if kind == "break_prior_12_high":
        return bool(bits & _BREAK12_HIGH)
    if kind == "break_prior_12_low":
        return bool(bits & _BREAK12_LOW)
    if kind == "prev_day_high_sweep_reclaim":
        return bool(bits & _PDH_SWEEP)
    if kind == "prev_day_low_sweep_reclaim":
        return bool(bits & _PDL_SWEEP)
    if kind == "prev_day_high_break":
        return bool(bits & _PDH_BREAK)
    if kind == "prev_day_low_break":
        return bool(bits & _PDL_BREAK)
    if kind == "session_high_sweep_reclaim":
        return bool(bits & _SESSION_HIGH_SWEEP)
    if kind == "session_low_sweep_reclaim":
        return bool(bits & _SESSION_LOW_SWEEP)
    if kind == "displacement_atr_min":
        return legacy.number(value[_DISPLACEMENT_ATR]) >= legacy.number(condition.get("min"), 0.5)
    if kind == "range_expansion_min":
        return legacy.number(value[_RANGE_EXPANSION]) >= legacy.number(condition.get("min"), 1.5)
    if kind == "range_position_high":
        return legacy.number(value[_RANGE_POSITION], -99.0) >= legacy.number(condition.get("min"), 0.8)
    if kind == "range_position_low":
        return legacy.number(value[_RANGE_POSITION], 99.0) <= legacy.number(condition.get("max"), 0.2)
    if kind == "compression_release":
        return bool(bits & _COMPRESSION_RELEASE)
    if kind == "three_bar_same_direction":
        return bool(bits & _THREE_BAR_SAME)
    return _V2_RECIPE(row, condition)


def compact_candidate_direction(row: dict[str, Any], rules: dict[str, Any]) -> int:
    rule = str((rules.get("entry") or {}).get("direction_rule") or "current_direction")
    value = _obs(row)
    if value is None:
        return _ORIGINAL_DIRECTION(row, rules)
    if rule == "structure_direction":
        return legacy.sign(value[_STRUCTURE_DIRECTION])
    if rule == "three_bar_direction":
        return legacy.sign(value[_THREE_BAR_DIRECTION])
    return _V2_DIRECTION(row, rules)


# Install compact research semantics before intelligence modules import the
# legacy helpers by value.
research.enrich_market_observations = compact_enrich_market_observations
research.recipe_condition_matches = compact_recipe_condition_matches
research.candidate_direction = compact_candidate_direction
legacy.recipe_condition_matches = compact_recipe_condition_matches
legacy.candidate_direction = compact_candidate_direction


# Import after the observation patch so feature matchers bind the compact
# recipe semantics.
from app.services import evidence_miner as miner  # noqa: E402

_ORIGINAL_MINE_EVIDENCE = miner.mine_evidence


def _chronological(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if all(
        str(rows[index - 1].get("candle_time") or "") <= str(rows[index].get("candle_time") or "")
        for index in range(1, len(rows))
    ):
        return rows
    return sorted(rows, key=lambda row: str(row.get("candle_time") or ""))


def _match_indices(spec: Any, rows: list[dict[str, Any]]) -> list[int]:
    matched: list[int] = []
    for index, row in enumerate(rows):
        try:
            if spec.matcher(row):
                matched.append(index)
        except Exception:
            continue
    return matched


def _mask_for(spec: Any, rows: list[dict[str, Any]]) -> bytearray:
    mask = bytearray(len(rows))
    for index, row in enumerate(rows):
        try:
            if spec.matcher(row):
                mask[index] = 1
        except Exception:
            continue
    return mask


def memory_bounded_mine_evidence(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Evidence Miner v1 semantics with bounded feature-match working memory."""
    ordered = _chronological(rows)
    returns_by_horizon = miner._returns_by_horizon(ordered)
    years, year_baselines = miner._year_context(ordered, returns_by_horizon)
    specs = miner.feature_specs()
    spec_by_key = {spec.key: spec for spec in specs}

    # Old implementation retained match-index lists for every feature at once.
    # Process one feature at a time, retaining only statistical results.
    singles: list[dict[str, Any]] = []
    eligible_feature_keys: list[str] = []
    for spec in specs:
        indices = _match_indices(spec, ordered)
        if len(indices) < miner.MIN_SINGLE_SAMPLES:
            continue
        eligible_feature_keys.append(spec.key)
        for horizon in miner.HORIZONS:
            tested = miner._test_indices(
                [spec.key],
                indices,
                returns_by_horizon,
                years,
                year_baselines,
                horizon,
                miner.MIN_SINGLE_SAMPLES,
            )
            if tested:
                tested["kind"] = "single"
                singles.append(tested)
        # ``indices`` is now out of scope and can be reclaimed before the next
        # feature instead of accumulating across the feature universe.
    miner._bh_adjust(singles)

    ranked_single_features: list[str] = []
    for item in sorted(
        singles,
        key=lambda value: (
            miner._float_or(value.get("q_value"), 1.0),
            -abs(miner._float_or(value.get("standardized_effect"), 0.0)),
            -int(value.get("sample_count") or 0),
        ),
    ):
        feature_key = str((item.get("feature_keys") or [""])[0])
        if feature_key and feature_key not in ranked_single_features:
            ranked_single_features.append(feature_key)
        if len(ranked_single_features) >= miner.TOP_PAIR_FEATURES:
            break

    # Byte masks cost one byte per row/feature and replace Python sets/lists of
    # integer objects for pair intersections.
    pair_masks: dict[str, bytearray] = {}
    for key in ranked_single_features:
        spec = spec_by_key.get(key)
        if spec is not None:
            pair_masks[key] = _mask_for(spec, ordered)

    pairs: list[dict[str, Any]] = []
    for left_index, left in enumerate(ranked_single_features):
        left_mask = pair_masks.get(left)
        if left_mask is None:
            continue
        for right in ranked_single_features[left_index + 1 :]:
            right_mask = pair_masks.get(right)
            if right_mask is None:
                continue
            intersection = [
                index
                for index in range(len(ordered))
                if left_mask[index] and right_mask[index]
            ]
            if len(intersection) < miner.MIN_PAIR_SAMPLES:
                continue
            for horizon in miner.PAIR_HORIZONS:
                tested = miner._test_indices(
                    [left, right],
                    intersection,
                    returns_by_horizon,
                    years,
                    year_baselines,
                    horizon,
                    miner.MIN_PAIR_SAMPLES,
                )
                if tested:
                    tested["kind"] = "pair"
                    pairs.append(tested)
    miner._bh_adjust(pairs)

    all_tests = singles + pairs
    signals: list[dict[str, Any]] = []
    for item in all_tests:
        q_value = miner._float_or(item.get("q_value"), 1.0)
        stability = miner._float_or(item.get("year_stability"), 0.0)
        standardized = abs(miner._float_or(item.get("standardized_effect"), 0.0))
        passed = q_value <= miner.FDR_GATE and stability >= miner.YEAR_STABILITY_GATE and standardized >= 0.03
        item["status"] = "signal" if passed else "screened"
        item["evidence_score"] = round(miner._score(item) if passed else 0.0, 6)
        feature_keys = list(item.get("feature_keys") or [])
        item["signature"] = f"{item.get('kind')}:{'||'.join(sorted(feature_keys))}:{int(item.get('horizon_minutes') or 0)}"
        if passed:
            signals.append(item)

    signals.sort(
        key=lambda item: (
            miner._float_or(item.get("evidence_score"), 0.0),
            abs(miner._float_or(item.get("standardized_effect"), 0.0)),
            int(item.get("sample_count") or 0),
        ),
        reverse=True,
    )
    all_tests.sort(
        key=lambda item: (
            0 if item.get("status") == "signal" else 1,
            miner._float_or(item.get("q_value"), 1.0),
            -abs(miner._float_or(item.get("standardized_effect"), 0.0)),
        )
    )
    return {
        "version": miner.EVIDENCE_MINER_VERSION,
        "memory_guard_version": MEMORY_GUARD_VERSION,
        "development_rows": len(ordered),
        "features_screened": len(eligible_feature_keys),
        "single_tests": len(singles),
        "pair_tests": len(pairs),
        "signals": len(signals),
        "horizons": list(miner.HORIZONS),
        "fdr_gate": miner.FDR_GATE,
        "year_stability_gate": miner.YEAR_STABILITY_GATE,
        "top_signals": signals[:20],
        "rows": all_tests[:500],
        "data_access": "development_only",
        "validation_access": "forbidden",
        "confirmation_holdout_access": "forbidden",
    }


miner.mine_evidence = memory_bounded_mine_evidence


def runtime_status() -> dict[str, Any]:
    return {
        "version": MEMORY_GUARD_VERSION,
        "compact_observation_key": OBS_KEY,
        "persistent_observation_fields_per_row": 1,
        "evidence_match_policy": "one feature index list at a time; byte masks for top pair features",
        "research_semantics": "unchanged",
    }
