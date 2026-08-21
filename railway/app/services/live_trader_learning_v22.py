from __future__ import annotations

import hashlib
from typing import Any

from app.services import live_trader_learning_v2 as v2

LEARNING_VERSION = "eve-live-learning-v2.2"
EPISODE_POLICY = "one structural-family sample per symbol + UTC trading day + session"
FAMILY_POLICY = (
    "family identity uses bias, execution class, HTF/intraday relationship and zone-side location; "
    "session, regime, momentum and zone quality transfer as weighted context"
)
MIN_EFFECTIVE_SAMPLES = 8.0

_base_descriptor = v2.setup_family_descriptor
_current_runtime_status = v2.LiveTrader.runtime_status


def _relation(alignment: str, bias: str) -> str:
    alignment = str(alignment or "mixed")
    bias = str(bias or "neutral")
    if bias not in {"bullish", "bearish"}:
        return "mixed"
    if alignment == bias:
        return "aligned"
    if alignment in {"bullish", "bearish"}:
        return "opposed"
    return "mixed"


def _execution_class(order_type: Any) -> str:
    value = str(order_type or "none").lower()
    if value == "market":
        return "market"
    if value.endswith("_limit"):
        return "pullback"
    if value.endswith("_stop"):
        return "breakout"
    return "wait"


def _regime_group(value: Any) -> str:
    regime = str(value or "unknown").lower()
    if regime.startswith("trend_"):
        return "trend"
    if regime == "compression":
        return "compression"
    if regime in {"range", "ranging"}:
        return "range"
    return "other"


def _location_relation(location: str, bias: str) -> str:
    location = str(location or "middle")
    bias = str(bias or "neutral")
    demand_side = "demand" in location
    supply_side = "supply" in location
    if bias == "bullish":
        if demand_side:
            return "preferred"
        if supply_side:
            return "opposing"
        return "middle"
    if bias == "bearish":
        if supply_side:
            return "preferred"
        if demand_side:
            return "opposing"
        return "middle"
    if location.startswith("in_") or location.startswith("near_"):
        return "at_zone"
    return "middle"


def _momentum_relation(momentum_12: str, momentum_48: str, bias: str) -> str:
    bias = str(bias or "neutral")
    values = [str(momentum_12 or "flat"), str(momentum_48 or "flat")]
    if bias == "neutral":
        return "quiet" if all(value == "flat" for value in values) else "directional"
    aligned_value = "up" if bias == "bullish" else "down"
    opposed_value = "down" if bias == "bullish" else "up"
    aligned = sum(value == aligned_value for value in values)
    opposed = sum(value == opposed_value for value in values)
    if aligned == 2:
        return "aligned"
    if opposed == 2:
        return "opposed"
    return "mixed"


def setup_family_descriptor(state: dict[str, Any]) -> dict[str, str]:
    """Build a transferable condition description.

    Only structural fields define the family hash. Context fields remain in the
    descriptor so calibration can down-weight evidence from a different session,
    regime or momentum state without pretending it is unrelated.
    """
    base = _base_descriptor(state)
    bias = str(base.get("bias") or "neutral")
    return {
        "bias": bias,
        "execution_class": _execution_class(base.get("order_type")),
        "htf_relation": _relation(str(base.get("htf_alignment") or "mixed"), bias),
        "intraday_relation": _relation(str(base.get("intraday_alignment") or "mixed"), bias),
        "location_relation": _location_relation(str(base.get("location") or "middle"), bias),
        # Weighted context: intentionally not part of family identity.
        "session": str(base.get("session") or "unknown"),
        "regime_group": _regime_group(base.get("regime")),
        "momentum_relation": _momentum_relation(
            str(base.get("momentum_12") or "flat"),
            str(base.get("momentum_48") or "flat"),
            bias,
        ),
        "zone_quality": str(base.get("zone_quality") or "none"),
    }


_FAMILY_KEYS = (
    "bias",
    "execution_class",
    "htf_relation",
    "intraday_relation",
    "location_relation",
)


def family_signature(state: dict[str, Any]) -> str:
    descriptor = setup_family_descriptor(state)
    raw = "|".join(f"{key}={descriptor[key]}" for key in _FAMILY_KEYS)
    return hashlib.sha1(raw.encode()).hexdigest()[:20]


def episode_key(state: dict[str, Any]) -> str:
    as_of = str(state.get("as_of") or "")
    day = as_of[:10] if len(as_of) >= 10 else v2.utc_now().date().isoformat()
    symbol = str(state.get("symbol") or "XAU/USD")
    session = str((state.get("market") or {}).get("session") or "unknown")
    raw = "|".join([symbol, day, session])
    return hashlib.sha1(raw.encode()).hexdigest()[:24]


def _context_weight(current: dict[str, Any], historical: dict[str, Any]) -> float:
    weight = 1.0
    if current and historical:
        if current.get("session") != historical.get("session"):
            weight *= 0.80
        if current.get("regime_group") != historical.get("regime_group"):
            weight *= 0.75
        if current.get("momentum_relation") != historical.get("momentum_relation"):
            weight *= 0.85
        if current.get("zone_quality") != historical.get("zone_quality"):
            weight *= 0.90
    return weight


def weighted_calibration_from_rows(rows: list[dict[str, Any]], current: dict[str, Any]) -> dict[str, Any]:
    independent: dict[str, dict[str, Any]] = {}
    for row in rows:
        outcome = row.get("learning_success")
        key = str(row.get("episode_key") or "")
        if outcome is None or not key or key in independent:
            continue
        independent[key] = row

    clean = list(independent.values())
    samples = len(clean)
    days = {
        str(row.get("observed_at"))[:10]
        for row in clean
        if row.get("observed_at") and len(str(row.get("observed_at"))) >= 10
    }
    wins = sum(1 for row in clean if bool(row.get("learning_success")))
    raw_accuracy = wins / samples if samples else None

    weighted_wins = 0.0
    effective_samples = 0.0
    same_session = 0
    same_regime = 0
    for row in clean:
        market_state = row.get("market_state") or {}
        historical = market_state.get("setup_family_descriptor") or {}
        weight = _context_weight(current, historical)
        effective_samples += weight
        if bool(row.get("learning_success")):
            weighted_wins += weight
        if current and historical and current.get("session") == historical.get("session"):
            same_session += 1
        if current and historical and current.get("regime_group") == historical.get("regime_group"):
            same_regime += 1

    weighted_accuracy = weighted_wins / effective_samples if effective_samples > 0 else None
    posterior_accuracy = (
        (weighted_wins + v2.PRIOR_WINS)
        / (effective_samples + v2.PRIOR_WINS + v2.PRIOR_LOSSES)
        if effective_samples > 0
        else 0.5
    )
    active = (
        samples >= v2.MIN_INDEPENDENT_EPISODES
        and len(days) >= v2.MIN_INDEPENDENT_DAYS
        and effective_samples >= MIN_EFFECTIVE_SAMPLES
    )
    adjustment = v2.clamp((posterior_accuracy - 0.5) * 20.0, -6.0, 6.0) if active else 0.0
    return {
        "samples": samples,
        "effective_samples": round(effective_samples, 2),
        "accuracy": round(weighted_accuracy, 3) if weighted_accuracy is not None else None,
        "raw_accuracy": round(raw_accuracy, 3) if raw_accuracy is not None else None,
        "posterior_accuracy": round(posterior_accuracy, 3),
        "confidence_adjustment": round(adjustment, 1),
        "independent_days": len(days),
        "same_session_samples": same_session,
        "same_regime_samples": same_regime,
        "active": active,
        "minimum_samples": v2.MIN_INDEPENDENT_EPISODES,
        "minimum_days": v2.MIN_INDEPENDENT_DAYS,
        "minimum_effective_samples": MIN_EFFECTIVE_SAMPLES,
        "learning_version": LEARNING_VERSION,
    }


def _signature_v22(self: v2.LiveTrader, state: dict[str, Any]) -> str:
    descriptor = setup_family_descriptor(state)
    signature = family_signature(state)
    state["setup_family"] = signature
    state["setup_family_descriptor"] = descriptor
    state["learning_version"] = LEARNING_VERSION
    self._learning_descriptor_v22 = descriptor
    return signature


async def _calibration_v22(self: v2.LiveTrader, signature: str) -> dict[str, Any]:
    try:
        rows = await self.repo.client.get(
            "live_trader_opinions",
            params={
                "select": "learning_success,episode_key,observed_at,market_state",
                "setup_family": f"eq.{signature}",
                "learning_version": f"eq.{LEARNING_VERSION}",
                "independent_sample": "eq.true",
                "status": "eq.resolved",
                "order": "observed_at.desc",
                "limit": "500",
            },
        )
    except Exception:
        rows = []
    current = getattr(self, "_learning_descriptor_v22", {}) or {}
    return weighted_calibration_from_rows(rows, current)


async def _learning_summary_v22(self: v2.LiveTrader) -> dict[str, Any]:
    summary = await v2._learning_summary_v2(self)
    summary["version"] = LEARNING_VERSION
    summary["policy"] = (
        "Learning v2.2 groups live decisions into transferable structural families. "
        "A family can contribute only once per UTC day/session; session, regime, momentum and zone quality "
        "are similarity weights rather than separate identities. Confidence stays locked until at least "
        f"{v2.MIN_INDEPENDENT_EPISODES} independent outcomes across {v2.MIN_INDEPENDENT_DAYS} trading days "
        f"and {MIN_EFFECTIVE_SAMPLES:.0f} effective weighted samples are available. Bayesian shrinkage and a ±6-point cap remain enforced."
    )
    summary["family_policy"] = FAMILY_POLICY
    summary["episode_policy"] = EPISODE_POLICY
    summary["legacy_v1_v2_v21_history_preserved"] = True
    return summary


def _runtime_status_v22(self: v2.LiveTrader) -> dict[str, Any]:
    state = dict(_current_runtime_status(self))
    state.update(
        {
            "learning_version": LEARNING_VERSION,
            "learning_family_policy": FAMILY_POLICY,
            "learning_episode_policy": EPISODE_POLICY,
            "learning_min_independent_samples": v2.MIN_INDEPENDENT_EPISODES,
            "learning_min_independent_days": v2.MIN_INDEPENDENT_DAYS,
            "learning_min_effective_samples": MIN_EFFECTIVE_SAMPLES,
            "learning_confidence_cap_points": 6,
        }
    )
    return state


# v2.2 reuses v2's race-safe record/resolve path and conservative execution scoring,
# but changes the family namespace and calibration semantics. Old versions remain
# in the database for audit and are never mixed into the new confidence pool.
v2.LEARNING_VERSION = LEARNING_VERSION
v2.setup_family_descriptor = setup_family_descriptor
v2.family_signature = family_signature
v2.episode_key = episode_key
v2.LiveTrader._signature = _signature_v22  # type: ignore[method-assign]
v2.LiveTrader._calibration = _calibration_v22  # type: ignore[method-assign]
v2.LiveTrader.learning_summary = _learning_summary_v22  # type: ignore[method-assign]
v2.LiveTrader.runtime_status = _runtime_status_v22  # type: ignore[method-assign]
