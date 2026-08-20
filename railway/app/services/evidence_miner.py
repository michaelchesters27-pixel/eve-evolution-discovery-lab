from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
import math
import statistics
from typing import Any, Callable

from app.services import backtest_v3 as research
from app.services import intelligence as v1
from app.services import intelligence_v2 as scientist
from app.services import mtf_reasoning as mtf
from app.services.multitimeframe import as_utc, number, safe_pct

EVIDENCE_MINER_VERSION = "eve-evidence-miner-v1"
HORIZONS = (15, 30, 60, 120, 240)
PAIR_HORIZONS = (30, 60, 240)
MIN_SINGLE_SAMPLES = 250
MIN_PAIR_SAMPLES = 180
FDR_GATE = 0.10
YEAR_STABILITY_GATE = 0.60
TOP_PAIR_FEATURES = 12


@dataclass(frozen=True)
class FeatureSpec:
    key: str
    label: str
    matcher: Callable[[dict[str, Any]], bool]


def _condition_spec(condition: dict[str, Any]) -> FeatureSpec:
    copied = dict(condition)
    key = v1.condition_key(copied)
    return FeatureSpec(
        key=key,
        label=key.removeprefix("condition:"),
        matcher=lambda row, condition=copied: bool(research.recipe_condition_matches(row, condition)),
    )


def feature_specs() -> list[FeatureSpec]:
    specs: list[FeatureSpec] = []
    seen: set[str] = set()
    condition_pool = [*v1.CONDITION_POOL, *scientist.STRUCTURE_POOL, *mtf.MTF_POOL]
    for condition in condition_pool:
        spec = _condition_spec(dict(condition))
        if spec.key not in seen:
            specs.append(spec)
            seen.add(spec.key)

    for session in ("asia", "london", "new_york", "off_session"):
        key = f"schedule:session:{session}"
        specs.append(FeatureSpec(key, f"session {session}", lambda row, value=session: str(row.get("session") or "") == value))
    for regime in ("compression", "trend_up", "trend_down", "high_volatility", "range"):
        key = f"environment:regime:{regime}"
        specs.append(FeatureSpec(key, f"regime {regime}", lambda row, value=regime: str(row.get("regime") or "") == value))
    return specs


def _stored_return(row: dict[str, Any], horizon: int) -> float | None:
    outcome = (row.get("outcomes") or {}).get(str(horizon))
    if not isinstance(outcome, dict) or outcome.get("close_return_pct") is None:
        return None
    value = number(outcome.get("close_return_pct"), math.nan)
    return value if math.isfinite(value) else None


def _returns_by_horizon(rows: list[dict[str, Any]]) -> dict[int, list[float | None]]:
    result: dict[int, list[float | None]] = {horizon: [None] * len(rows) for horizon in HORIZONS}
    times = [as_utc(row.get("candle_time")) for row in rows]
    for index, row in enumerate(rows):
        for horizon in (15, 30, 60, 240):
            result[horizon][index] = _stored_return(row, horizon)

        future_index = index + 24
        if future_index >= len(rows):
            continue
        current_time = times[index]
        future_time = times[future_index]
        if current_time is None or future_time is None:
            continue
        # Twenty-four five-minute bars must really be 120 minutes apart. This
        # avoids manufacturing a 120-minute label across a weekend/data gap.
        if future_time - current_time != timedelta(minutes=120):
            continue
        close = number(row.get("close"))
        future_close = number(rows[future_index].get("close"))
        if close > 0 and future_close > 0:
            result[120][index] = safe_pct(future_close, close)
    return result


def _mean(values: list[float]) -> float:
    return statistics.fmean(values) if values else 0.0


def _variance(values: list[float]) -> float:
    return statistics.pvariance(values) if len(values) >= 2 else 0.0


def _float_or(value: Any, default: float) -> float:
    if value is None:
        return default
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return default
    return parsed if math.isfinite(parsed) else default


def _normal_two_sided_p(z_score: float) -> float:
    return max(0.0, min(1.0, math.erfc(abs(z_score) / math.sqrt(2.0))))


def _bh_adjust(items: list[dict[str, Any]]) -> None:
    if not items:
        return
    ordered = sorted(enumerate(items), key=lambda pair: _float_or(pair[1].get("p_value"), 1.0))
    m = len(ordered)
    running = 1.0
    adjusted: dict[int, float] = {}
    for reverse_rank, (original_index, item) in enumerate(reversed(ordered), start=1):
        rank = m - reverse_rank + 1
        raw = _float_or(item.get("p_value"), 1.0)
        q_value = min(1.0, raw * m / max(1, rank))
        running = min(running, q_value)
        adjusted[original_index] = running
    for index, item in enumerate(items):
        item["q_value"] = round(adjusted.get(index, 1.0), 8)


def _year_context(
    rows: list[dict[str, Any]],
    returns_by_horizon: dict[int, list[float | None]],
) -> tuple[list[int | None], dict[int, dict[int, tuple[int, float]]]]:
    years: list[int | None] = []
    for row in rows:
        timestamp = as_utc(row.get("candle_time"))
        years.append(timestamp.year if timestamp is not None else None)

    baselines: dict[int, dict[int, tuple[int, float]]] = {}
    for horizon, returns in returns_by_horizon.items():
        grouped: dict[int, list[float]] = {}
        for index, value in enumerate(returns):
            year = years[index]
            if year is None or value is None:
                continue
            grouped.setdefault(year, []).append(float(value))
        baselines[horizon] = {
            year: (len(values), _mean(values))
            for year, values in grouped.items()
            if values
        }
    return years, baselines


def _year_stability(
    indices: list[int],
    returns: list[float | None],
    years: list[int | None],
    baseline_by_year: dict[int, tuple[int, float]],
    expected_sign: int,
) -> tuple[float, dict[str, float]]:
    matched_by_year: dict[int, list[float]] = {}
    for index in indices:
        if index >= len(returns):
            continue
        value = returns[index]
        year = years[index]
        if value is None or year is None:
            continue
        matched_by_year.setdefault(year, []).append(float(value))

    effects: dict[str, float] = {}
    stable = 0
    tested = 0
    for year in sorted(matched_by_year):
        feature_values = matched_by_year[year]
        baseline_count, baseline_mean = baseline_by_year.get(year, (0, 0.0))
        if len(feature_values) < 40 or baseline_count < 200:
            continue
        effect = _mean(feature_values) - baseline_mean
        effects[str(year)] = round(effect, 8)
        tested += 1
        sign = 1 if effect > 0 else -1 if effect < 0 else 0
        if expected_sign != 0 and sign == expected_sign:
            stable += 1
    return (stable / tested if tested else 0.0), effects


def _test_indices(
    feature_keys: list[str],
    indices: list[int],
    returns_by_horizon: dict[int, list[float | None]],
    years: list[int | None],
    year_baselines: dict[int, dict[int, tuple[int, float]]],
    horizon: int,
    minimum_samples: int,
) -> dict[str, Any] | None:
    returns = returns_by_horizon[horizon]
    feature_values = [float(returns[index]) for index in indices if index < len(returns) and returns[index] is not None]
    baseline_values = [float(value) for value in returns if value is not None]
    if len(feature_values) < minimum_samples or len(baseline_values) < max(1000, minimum_samples * 2):
        return None

    feature_mean = _mean(feature_values)
    baseline_mean = _mean(baseline_values)
    effect = feature_mean - baseline_mean
    feature_var = _variance(feature_values)
    baseline_var = _variance(baseline_values)
    se = math.sqrt(feature_var / len(feature_values) + baseline_var / len(baseline_values))
    z_score = effect / se if se > 1e-12 else 0.0
    p_value = _normal_two_sided_p(z_score)
    baseline_sd = math.sqrt(baseline_var)
    standardized = effect / baseline_sd if baseline_sd > 1e-12 else 0.0
    expected_sign = 1 if effect > 0 else -1 if effect < 0 else 0
    stability, year_effects = _year_stability(
        indices,
        returns,
        years,
        year_baselines.get(horizon, {}),
        expected_sign,
    )
    direction = "up" if expected_sign > 0 else "down" if expected_sign < 0 else "flat"
    return {
        "feature_keys": feature_keys,
        "horizon_minutes": horizon,
        "sample_count": len(feature_values),
        "baseline_count": len(baseline_values),
        "occurrence_rate": round(len(feature_values) / len(baseline_values), 8),
        "mean_return_pct": round(feature_mean, 8),
        "baseline_mean_return_pct": round(baseline_mean, 8),
        "effect_pct": round(effect, 8),
        "standardized_effect": round(standardized, 8),
        "z_score": round(z_score, 6),
        "p_value": round(p_value, 10),
        "direction": direction,
        "year_stability": round(stability, 6),
        "year_effects": year_effects,
    }


def _score(item: dict[str, Any]) -> float:
    q_value = max(_float_or(item.get("q_value"), 1.0), 1e-12)
    standardized = abs(_float_or(item.get("standardized_effect"), 0.0))
    stability = _float_or(item.get("year_stability"), 0.0)
    sample = int(item.get("sample_count") or 0)
    sample_weight = min(1.0, math.sqrt(sample / 1000.0))
    significance = min(3.0, max(0.0, -math.log10(q_value)))
    return min(3.0, standardized * 5.0 * max(0.25, stability) * sample_weight + significance * 0.30)


def mine_evidence(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Mine anomalies using development rows only.

    This is hypothesis generation, not validation. The caller must pass only the
    development split. Benjamini-Hochberg FDR control, minimum occurrence counts
    and cross-year sign stability make the output useful as cautious priors rather
    than as proof of a tradable edge.
    """
    ordered = sorted(rows, key=lambda row: str(row.get("candle_time") or ""))
    returns_by_horizon = _returns_by_horizon(ordered)
    years, year_baselines = _year_context(ordered, returns_by_horizon)
    specs = feature_specs()

    matches: dict[str, list[int]] = {}
    for spec in specs:
        matched: list[int] = []
        for index, row in enumerate(ordered):
            try:
                if spec.matcher(row):
                    matched.append(index)
            except Exception:
                continue
        if len(matched) >= MIN_SINGLE_SAMPLES:
            matches[spec.key] = matched

    singles: list[dict[str, Any]] = []
    for feature_key, indices in matches.items():
        for horizon in HORIZONS:
            tested = _test_indices(
                [feature_key],
                indices,
                returns_by_horizon,
                years,
                year_baselines,
                horizon,
                MIN_SINGLE_SAMPLES,
            )
            if tested:
                tested["kind"] = "single"
                singles.append(tested)
    _bh_adjust(singles)

    ranked_single_features: list[str] = []
    for item in sorted(
        singles,
        key=lambda value: (
            _float_or(value.get("q_value"), 1.0),
            -abs(_float_or(value.get("standardized_effect"), 0.0)),
            -int(value.get("sample_count") or 0),
        ),
    ):
        feature_key = str((item.get("feature_keys") or [""])[0])
        if feature_key and feature_key not in ranked_single_features:
            ranked_single_features.append(feature_key)
        if len(ranked_single_features) >= TOP_PAIR_FEATURES:
            break

    pairs: list[dict[str, Any]] = []
    match_sets = {key: set(indices) for key, indices in matches.items() if key in ranked_single_features}
    for left_index, left in enumerate(ranked_single_features):
        left_set = match_sets.get(left, set())
        for right in ranked_single_features[left_index + 1 :]:
            intersection = sorted(left_set.intersection(match_sets.get(right, set())))
            if len(intersection) < MIN_PAIR_SAMPLES:
                continue
            for horizon in PAIR_HORIZONS:
                tested = _test_indices(
                    [left, right],
                    intersection,
                    returns_by_horizon,
                    years,
                    year_baselines,
                    horizon,
                    MIN_PAIR_SAMPLES,
                )
                if tested:
                    tested["kind"] = "pair"
                    pairs.append(tested)
    _bh_adjust(pairs)

    all_tests = singles + pairs
    signals: list[dict[str, Any]] = []
    for item in all_tests:
        q_value = _float_or(item.get("q_value"), 1.0)
        stability = _float_or(item.get("year_stability"), 0.0)
        standardized = abs(_float_or(item.get("standardized_effect"), 0.0))
        passed = q_value <= FDR_GATE and stability >= YEAR_STABILITY_GATE and standardized >= 0.03
        item["status"] = "signal" if passed else "screened"
        item["evidence_score"] = round(_score(item) if passed else 0.0, 6)
        feature_keys = list(item.get("feature_keys") or [])
        item["signature"] = f"{item.get('kind')}:{'||'.join(sorted(feature_keys))}:{int(item.get('horizon_minutes') or 0)}"
        if passed:
            signals.append(item)

    signals.sort(
        key=lambda item: (
            _float_or(item.get("evidence_score"), 0.0),
            abs(_float_or(item.get("standardized_effect"), 0.0)),
            int(item.get("sample_count") or 0),
        ),
        reverse=True,
    )
    all_tests.sort(
        key=lambda item: (
            0 if item.get("status") == "signal" else 1,
            _float_or(item.get("q_value"), 1.0),
            -abs(_float_or(item.get("standardized_effect"), 0.0)),
        )
    )
    return {
        "version": EVIDENCE_MINER_VERSION,
        "development_rows": len(ordered),
        "features_screened": len(matches),
        "single_tests": len(singles),
        "pair_tests": len(pairs),
        "signals": len(signals),
        "horizons": list(HORIZONS),
        "fdr_gate": FDR_GATE,
        "year_stability_gate": YEAR_STABILITY_GATE,
        "top_signals": signals[:20],
        "rows": all_tests[:500],
        "data_access": "development_only",
        "validation_access": "forbidden",
        "confirmation_holdout_access": "forbidden",
    }


def evidence_priors(rows: list[dict[str, Any]]) -> dict[str, float]:
    priors: dict[str, list[float]] = {}
    for row in rows:
        if str(row.get("status") or "") != "signal":
            continue
        score = float(number(row.get("evidence_score")))
        if score <= 0:
            continue
        for feature_key in row.get("feature_keys") or []:
            priors.setdefault(str(feature_key), []).append(score)
    return {
        feature_key: min(3.0, statistics.fmean(scores))
        for feature_key, scores in priors.items()
        if feature_key and scores
    }
