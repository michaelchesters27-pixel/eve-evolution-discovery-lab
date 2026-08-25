from __future__ import annotations

from datetime import timedelta
from typing import Any

from app.services import live_trader as core
from app.services import live_trader_execution_forensics_v47 as forensics
from app.services.live_trader_execution_forensics_metrics_v47 import bar_time, parse_time

MANAGEMENT_REPLAY_VERSION = "eve-live-management-replay-v1"
FORENSICS_VERSION = "eve-live-execution-forensics-v1.1-management"
_BASE_BUILD_FORENSICS = forensics.build_forensics

MANAGEMENT_VARIANTS = (
    {"name": "be_after_1R", "activate_r": 1.0, "lock_r": 0.0},
    {"name": "lock_0.5R_after_1.5R", "activate_r": 1.5, "lock_r": 0.5},
    {"name": "lock_1R_after_2R", "activate_r": 2.0, "lock_r": 1.0},
)


def _num(value: Any, default: float = 0.0) -> float:
    return core.number(value, default)


def _active_full_bars(campaign: dict[str, Any], bars: list[dict[str, Any]]) -> list[dict[str, Any]]:
    triggered = parse_time(campaign.get("triggered_at"))
    completed = parse_time(campaign.get("completed_at"))
    if not triggered or not completed:
        return []
    # A protection rule cannot be credited from the partial trigger candle because
    # M1 OHLC cannot prove whether the favourable move happened before an adverse
    # move. Start from the next full minute and stop at official completion.
    start = triggered.replace(second=0, microsecond=0) + timedelta(minutes=1)
    end = completed.replace(second=0, microsecond=0)
    result: list[dict[str, Any]] = []
    for bar in bars:
        stamp = bar_time(bar)
        if stamp is not None and start <= stamp <= end:
            result.append(bar)
    return result


def _managed_replay(
    campaign: dict[str, Any],
    bars: list[dict[str, Any]],
    *,
    activate_r: float,
    lock_r: float,
) -> dict[str, Any]:
    side = str(campaign.get("side") or "").upper()
    entry = _num(campaign.get("entry"))
    initial_stop = _num(campaign.get("stop"))
    target = _num(campaign.get("target"))
    risk = abs(entry - initial_stop)
    if side not in {"BUY", "SELL"} or entry <= 0 or initial_stop <= 0 or target <= 0 or risk <= 0:
        return {"available": False}

    usable = _active_full_bars(campaign, bars)
    if not usable:
        return {"available": False}

    current_stop = initial_stop
    protection_armed = False
    armed_at = None
    locked_r = -1.0
    original_rr = abs(target - entry) / risk

    for bar in usable:
        stamp = bar_time(bar)
        low = _num(bar.get("low"))
        high = _num(bar.get("high"))
        if side == "BUY":
            stop_hit = low <= current_stop
            target_hit = high >= target
            activation_hit = high >= entry + risk * activate_r
        else:
            stop_hit = high >= current_stop
            target_hit = low <= target
            activation_hit = low <= entry - risk * activate_r

        # Same-minute ambiguity remains adverse: a tightened stop or the original
        # stop wins over a target when both exist in one M1 bar.
        if stop_hit:
            realised = ((current_stop - entry) / risk) if side == "BUY" else ((entry - current_stop) / risk)
            return {
                "available": True,
                "trade_outcome": "protected_stop" if protection_armed else "stop",
                "realised_r": round(realised, 3),
                "protection_armed": protection_armed,
                "armed_at": armed_at,
                "final_stop": round(current_stop, 3),
            }
        if target_hit:
            return {
                "available": True,
                "trade_outcome": "target",
                "realised_r": round(original_rr, 3),
                "protection_armed": protection_armed,
                "armed_at": armed_at,
                "final_stop": round(current_stop, 3),
            }

        if not protection_armed and activation_hit:
            # Activate only for the NEXT full M1 bar. This is intentionally
            # conservative because OHLC cannot prove the within-bar sequence.
            current_stop = entry + risk * lock_r if side == "BUY" else entry - risk * lock_r
            protection_armed = True
            locked_r = lock_r
            armed_at = stamp.isoformat() if stamp else None

    return {
        "available": True,
        "trade_outcome": "open_at_official_completion",
        "realised_r": None,
        "protection_armed": protection_armed,
        "armed_at": armed_at,
        "protected_stop_r": round(locked_r, 3) if protection_armed else None,
        "final_stop": round(current_stop, 3),
    }


def management_replay(campaign: dict[str, Any], bars: list[dict[str, Any]]) -> dict[str, Any]:
    results: dict[str, Any] = {}
    for spec in MANAGEMENT_VARIANTS:
        results[str(spec["name"])] = {
            "activate_r": spec["activate_r"],
            "lock_r": spec["lock_r"],
            **_managed_replay(
                campaign,
                bars,
                activate_r=float(spec["activate_r"]),
                lock_r=float(spec["lock_r"]),
            ),
        }
    return {
        "version": MANAGEMENT_REPLAY_VERSION,
        "diagnostic_only": True,
        "policy": (
            "Protection activates only from the next full M1 bar after the threshold is observed; "
            "same-bar stop/target ambiguity is resolved adversely. These results do not alter live trades automatically."
        ),
        "results": results,
    }


def _build_forensics_v52(
    campaign: dict[str, Any],
    row: dict[str, Any],
    bars: list[dict[str, Any]],
    opinion: dict[str, Any] | None,
    historical: list[dict[str, Any]],
    forward: list[dict[str, Any]],
    version: str,
    max_source_bars: int,
) -> dict[str, Any]:
    result = _BASE_BUILD_FORENSICS(
        campaign,
        row,
        bars,
        opinion,
        historical,
        forward,
        version,
        max_source_bars,
    )
    result["management_alternative_replay"] = management_replay(campaign, bars)
    return result


# Changing the forensic version intentionally causes the existing background
# worker to re-enrich prior completed campaigns from their continuous source-M1
# paths. That includes today's trade, so the protection alternatives become real
# stored evidence rather than a one-off manual observation.
forensics.build_forensics = _build_forensics_v52
forensics.FORENSICS_VERSION = FORENSICS_VERSION
