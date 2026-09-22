from __future__ import annotations

from datetime import datetime, timedelta, timezone

from app.services import evidence_miner as miner


def _row(index: int) -> dict:
    at = datetime(2026, 1, 1, tzinfo=timezone.utc) + timedelta(minutes=5 * index)
    close = 100.0 + (index % 37) * 0.01 + index * 0.0001
    outcomes = {}
    for horizon, scale in ((15, 0.03), (30, 0.05), (60, 0.08), (240, 0.13)):
        value = ((index % 11) - 5) * scale / 10.0
        outcomes[str(horizon)] = {
            "max_up_atr": max(0.0, value),
            "max_down_atr": min(0.0, value),
            "close_return_pct": value,
        }
    return {
        "candle_time": at.isoformat(),
        "close": close,
        "group_a": index % 2 == 0,
        "group_b": index % 3 == 0,
        "group_c": index % 5 in (0, 1),
        "outcomes": outcomes,
    }


def _legacy_reference(rows: list[dict]) -> dict:
    ordered = sorted(rows, key=lambda row: str(row.get("candle_time") or ""))
    returns_by_horizon = miner._returns_by_horizon(ordered)
    years, year_baselines = miner._year_context(ordered, returns_by_horizon)
    specs = miner.feature_specs()

    matches: dict[str, list[int]] = {}
    for spec in specs:
        matched: list[int] = []
        for index, row in enumerate(ordered):
            try:
                if spec.matcher(row):
                    matched.append(index)
            except Exception:
                continue
        if len(matched) >= miner.MIN_SINGLE_SAMPLES:
            matches[spec.key] = matched

    singles: list[dict] = []
    for feature_key, indices in matches.items():
        for horizon in miner.HORIZONS:
            tested = miner._test_indices(
                [feature_key],
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
    miner._bh_adjust(singles)

    ranked: list[str] = []
    for item in sorted(
        singles,
        key=lambda value: (
            miner._float_or(value.get("q_value"), 1.0),
            -abs(miner._float_or(value.get("standardized_effect"), 0.0)),
            -int(value.get("sample_count") or 0),
        ),
    ):
        key = str((item.get("feature_keys") or [""])[0])
        if key and key not in ranked:
            ranked.append(key)
        if len(ranked) >= miner.TOP_PAIR_FEATURES:
            break

    pairs: list[dict] = []
    match_sets = {key: set(indices) for key, indices in matches.items() if key in ranked}
    for left_index, left in enumerate(ranked):
        left_set = match_sets.get(left, set())
        for right in ranked[left_index + 1 :]:
            intersection = sorted(left_set.intersection(match_sets.get(right, set())))
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
    for item in all_tests:
        q_value = miner._float_or(item.get("q_value"), 1.0)
        stability = miner._float_or(item.get("year_stability"), 0.0)
        standardized = abs(miner._float_or(item.get("standardized_effect"), 0.0))
        passed = q_value <= miner.FDR_GATE and stability >= miner.YEAR_STABILITY_GATE and standardized >= 0.03
        item["status"] = "signal" if passed else "screened"
        item["evidence_score"] = round(miner._score(item) if passed else 0.0, 6)
        keys = list(item.get("feature_keys") or [])
        item["signature"] = f"{item.get('kind')}:{'||'.join(sorted(keys))}:{int(item.get('horizon_minutes') or 0)}"

    all_tests.sort(
        key=lambda item: (
            0 if item.get("status") == "signal" else 1,
            miner._float_or(item.get("q_value"), 1.0),
            -abs(miner._float_or(item.get("standardized_effect"), 0.0)),
        )
    )
    return {
        "features_screened": len(matches),
        "single_tests": len(singles),
        "pair_tests": len(pairs),
        "rows": all_tests[:500],
    }


def test_resource_bounded_match_scan_preserves_legacy_evidence_results(monkeypatch) -> None:
    specs = [
        miner.FeatureSpec("a", "a", lambda row: bool(row.get("group_a"))),
        miner.FeatureSpec("b", "b", lambda row: bool(row.get("group_b"))),
        miner.FeatureSpec("c", "c", lambda row: bool(row.get("group_c"))),
    ]
    monkeypatch.setattr(miner, "feature_specs", lambda: specs)
    monkeypatch.setattr(miner, "MIN_SINGLE_SAMPLES", 20)
    monkeypatch.setattr(miner, "MIN_PAIR_SAMPLES", 10)
    monkeypatch.setattr(miner, "TOP_PAIR_FEATURES", 3)

    rows = [_row(index) for index in range(1200)]
    expected = _legacy_reference(rows)
    actual = miner.mine_evidence(rows)

    assert actual["features_screened"] == expected["features_screened"]
    assert actual["single_tests"] == expected["single_tests"]
    assert actual["pair_tests"] == expected["pair_tests"]
    assert actual["rows"] == expected["rows"]
