from __future__ import annotations

import json
from typing import Any

VERSION = "eve-compact-research-row-v1"

BASE_FIELDS: tuple[str, ...] = (
    "symbol",
    "snapshot_interval",
    "source_interval",
    "candle_time",
    "open",
    "high",
    "low",
    "close",
    "weekday",
    "month",
    "hour_utc",
    "session",
    "direction",
    "range_price",
    "body_price",
    "upper_wick",
    "lower_wick",
    "close_location",
    "atr_14",
    "average_range_12",
    "compression_ratio",
    "return_1_pct",
    "return_3_pct",
    "trend_12_atr",
    "trend_48_atr",
    "streak",
    "regime",
    "alignment_score",
    "outcome_complete",
    "feature_version",
    "mtf_m1_available",
    "mtf_m1_direction",
    "mtf_m1_direction_changes",
    "mtf_m1_path_efficiency",
    "mtf_m1_last_direction",
    "mtf_m15_direction",
    "mtf_m30_direction",
    "mtf_h1_direction",
    "mtf_h4_direction",
    "mtf_d1_direction",
    "mtf_htf_alignment_score",
    "fabric_version",
)

OBSERVATION_FIELDS: tuple[str, ...] = (
    "observation_version",
    "obs_prior_4_high",
    "obs_prior_4_low",
    "obs_prior_12_high",
    "obs_prior_12_low",
    "obs_prior_48_high",
    "obs_prior_48_low",
    "obs_sweep_prior_12_high",
    "obs_sweep_prior_12_low",
    "obs_break_prior_12_high",
    "obs_break_prior_12_low",
    "obs_range_position_12",
    "obs_distance_prior_12_high_atr",
    "obs_distance_prior_12_low_atr",
    "obs_previous_day_high",
    "obs_previous_day_low",
    "obs_prev_day_high_sweep",
    "obs_prev_day_low_sweep",
    "obs_prev_day_high_break",
    "obs_prev_day_low_break",
    "obs_session_prior_high",
    "obs_session_prior_low",
    "obs_session_high_sweep",
    "obs_session_low_sweep",
    "obs_displacement_atr",
    "obs_range_expansion",
    "obs_compression_release",
    "obs_three_bar_same_direction",
    "obs_three_bar_direction",
    "obs_structure_direction",
)

BASE_INDEX = {name: index for index, name in enumerate(BASE_FIELDS)}
OBS_INDEX = {name: index for index, name in enumerate(OBSERVATION_FIELDS)}

LEGACY_SELECT = ",".join(
    field
    for field in BASE_FIELDS
    if not field.startswith("mtf_") and field != "fabric_version"
) + ",outcomes"

FABRIC_SELECT = ",".join(BASE_FIELDS) + ",outcomes"


class CompactResearchRow:
    """Mutable dict-like research row with fixed pointer arrays.

    Source JSON pages are converted immediately, so hundreds of thousands of
    repeated Python dictionaries/keys and nested outcome dictionaries are not
    retained. The canonical outcome JSON preserves the exact original outcome
    object for dataset fingerprints while hot-path outcome access uses compact
    horizon triples.
    """

    __slots__ = ("_values", "_observations", "_outcome_hot", "canonical_outcomes_json", "_extras")

    def __init__(self, row: dict[str, Any]) -> None:
        self._values = tuple(row.get(field) for field in BASE_FIELDS)
        outcomes = row.get("outcomes") if isinstance(row.get("outcomes"), dict) else {}
        self.canonical_outcomes_json = json.dumps(
            outcomes or {},
            sort_keys=True,
            separators=(",", ":"),
            default=str,
        )
        hot: dict[str, tuple[Any, Any, Any]] = {}
        for horizon, outcome in (outcomes or {}).items():
            if not isinstance(outcome, dict):
                continue
            hot[str(horizon)] = (
                outcome.get("max_up_atr"),
                outcome.get("max_down_atr"),
                outcome.get("close_return_pct"),
            )
        self._outcome_hot = hot
        self._observations = [None] * len(OBSERVATION_FIELDS)
        self._extras: dict[str, Any] | None = None

    def get(self, key: str, default: Any = None) -> Any:
        index = BASE_INDEX.get(key)
        if index is not None:
            value = self._values[index]
            return default if value is None and default is not None else value
        obs_index = OBS_INDEX.get(key)
        if obs_index is not None:
            value = self._observations[obs_index]
            return default if value is None and default is not None else value
        if key == "outcomes":
            try:
                return json.loads(self.canonical_outcomes_json)
            except json.JSONDecodeError:
                return {}
        if self._extras is not None and key in self._extras:
            return self._extras[key]
        return default

    def __getitem__(self, key: str) -> Any:
        sentinel = object()
        value = self.get(key, sentinel)
        if value is sentinel:
            raise KeyError(key)
        return value

    def __setitem__(self, key: str, value: Any) -> None:
        obs_index = OBS_INDEX.get(key)
        if obs_index is not None:
            self._observations[obs_index] = value
            return
        if self._extras is None:
            self._extras = {}
        self._extras[key] = value

    def __contains__(self, key: str) -> bool:
        if key in BASE_INDEX or key in OBS_INDEX or key == "outcomes":
            return True
        return self._extras is not None and key in self._extras

    def outcome(self, horizon: int | str) -> dict[str, Any] | None:
        value = self._outcome_hot.get(str(horizon))
        if value is None:
            return None
        return {
            "max_up_atr": value[0],
            "max_down_atr": value[1],
            "close_return_pct": value[2],
        }


def compact_row(row: dict[str, Any]) -> CompactResearchRow:
    return CompactResearchRow(row)


def research_outcome(row: Any, horizon: int | str) -> dict[str, Any] | None:
    if isinstance(row, CompactResearchRow):
        return row.outcome(horizon)
    outcomes = row.get("outcomes") if hasattr(row, "get") else None
    result = outcomes.get(str(horizon)) if isinstance(outcomes, dict) else None
    return dict(result) if isinstance(result, dict) else None


def fingerprint_outcomes(row: Any) -> Any:
    if isinstance(row, CompactResearchRow):
        try:
            return json.loads(row.canonical_outcomes_json)
        except json.JSONDecodeError:
            return {}
    return row.get("outcomes") if hasattr(row, "get") else {}
