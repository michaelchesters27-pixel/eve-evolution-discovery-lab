from __future__ import annotations

from typing import Any

from app.services import live_trader as core
from app.services import live_trader_zone_retrace_live_policy_replay_v68 as v68

DIAGNOSTIC_VERSION = "eve-live-zone-retrace-replay-diagnostics-v70"
_current_runtime_status = core.LiveTrader.runtime_status
_prior_replay_episode = v68.ZoneRetraceLivePolicyReplayer._replay_episode


def _bump(mapping: dict[str, int], key: str) -> None:
    key = str(key or "unknown")[:240]
    mapping[key] = int(mapping.get(key, 0)) + 1


def _find_entry_v70(
    self: v68.ZoneRetraceLivePolicyReplayer,
    *,
    expected_bias: str,
    observed,
    search_end,
    warm: list[dict[str, Any]],
    future: list[dict[str, Any]],
    m1_rows: list[dict[str, Any]],
) -> dict[str, Any] | None:
    diagnostics: dict[str, Any] = {
        "version": DIAGNOSTIC_VERSION,
        "expected_bias": expected_bias,
        "m5_states": 0,
        "m1_minutes_considered": 0,
        "broker_or_session_blocked": 0,
        "bias_not_expected": 0,
        "clear_bias_blocked": 0,
        "clear_bias_reasons": {},
        "ranked_zone_missing": 0,
        "ranked_zone_present": 0,
        "zone_not_touched": 0,
        "zone_touch_minutes": 0,
        "candidate_rejected_after_touch": 0,
        "candidate_rejection_reasons": {},
        "entry_found": False,
        "ended_on_opposite_clear_bias": False,
    }
    self._last_entry_search_diagnostics_v70 = diagnostics

    m5_states: list[tuple[Any, dict[str, Any], list[dict[str, Any]]]] = []
    rolling = list(warm)
    seen_candle_times = {str(row.get("candle_time") or "") for row in rolling}
    for row in future:
        stamp = str(row.get("candle_time") or "")
        if stamp not in seen_candle_times:
            rolling.append(row)
            seen_candle_times.add(stamp)
        decision = v68._decision_time(row)
        if decision is None or decision < observed or decision > search_end:
            continue
        m5_states.append((decision, row, list(rolling[-720:])))
    diagnostics["m5_states"] = len(m5_states)

    if not m5_states:
        diagnostics["primary_blocker"] = "no_m5_states"
        return None

    state_index = -1
    state_cache: dict[int, tuple[dict[str, Any], dict[str, Any], bool, dict[str, Any]]] = {}
    for bar in m1_rows:
        bar_time = v68._parse_time(bar.get("candle_time"))
        if bar_time is None or bar_time < observed or bar_time > search_end:
            continue
        diagnostics["m1_minutes_considered"] += 1
        while state_index + 1 < len(m5_states) and m5_states[state_index + 1][0] <= bar_time:
            state_index += 1
        if state_index < 0:
            continue

        decision, latest, history = m5_states[state_index]
        if state_index not in state_cache:
            state_cache[state_index] = self._state_for_m5(history, latest)
        bias, liquidity, clear, assessment = state_cache[state_index]
        overall = str(bias.get("overall") or "neutral").lower()

        if overall != expected_bias:
            diagnostics["bias_not_expected"] += 1
            if clear and overall in {"bullish", "bearish"} and overall != expected_bias:
                diagnostics["ended_on_opposite_clear_bias"] = True
                diagnostics["opposite_bias"] = overall
                diagnostics["opposite_bias_at"] = bar_time.isoformat()
                diagnostics["primary_blocker"] = "opposite_clear_bias"
                return None
            continue

        if not clear:
            diagnostics["clear_bias_blocked"] += 1
            for reason in list(assessment.get("reasons") or []):
                _bump(diagnostics["clear_bias_reasons"], reason)
            continue

        if not v68.academy.broker_market_open(bar_time) or not v68.session_gate._inside_london_window(bar_time):
            diagnostics["broker_or_session_blocked"] += 1
            continue

        open_price = v68._num(bar.get("open"))
        atr = max(v68._num(latest.get("atr_14")), 0.01)
        zones_at_open = self.engine._zone_candidates(history, open_price, bias)
        zone_at_open = v68._source_zone_for_bias(zones_at_open, overall)
        if not zone_at_open:
            diagnostics["ranked_zone_missing"] += 1
            continue
        diagnostics["ranked_zone_present"] += 1

        probe, resolution = v68._touch_probe(bar, zone_at_open)
        if probe is None:
            diagnostics["zone_not_touched"] += 1
            continue
        diagnostics["zone_touch_minutes"] += 1

        zones = self.engine._zone_candidates(history, probe, bias)
        setup, trade = v68.v58._candidate_v58(self.engine, probe, atr, bias, zones, liquidity)
        trade = dict(trade or {})
        if str(trade.get("order_type") or "").lower() != "market" or str(trade.get("strategy_key") or "") != v68.v58.STRATEGY_KEY:
            diagnostics["candidate_rejected_after_touch"] += 1
            _bump(diagnostics["candidate_rejection_reasons"], str(trade.get("reason") or (setup or {}).get("reason") or "unknown"))
            continue

        adjusted = v68.v49._apply_target_cap(trade)
        source_zone = dict(adjusted.get("source_zone") or v68._source_zone_for_bias(zones, overall) or {})
        entry = v68._num(adjusted.get("entry"))
        stop = v68._num(adjusted.get("stop"))
        target = v68._num(adjusted.get("target"))
        risk = abs(entry - stop)
        if entry <= 0 or stop <= 0 or target <= 0 or risk <= 0:
            diagnostics["candidate_rejected_after_touch"] += 1
            _bump(diagnostics["candidate_rejection_reasons"], "invalid live risk geometry")
            continue

        target_r = abs(target - entry) / risk
        diagnostics["entry_found"] = True
        diagnostics["entry_at"] = bar_time.isoformat()
        diagnostics["entry_resolution"] = resolution
        diagnostics["primary_blocker"] = None
        return {
            "entry_at": bar_time,
            "decision_at": decision,
            "side": str(adjusted.get("side") or "").upper(),
            "entry": round(entry, 3),
            "stop": round(stop, 3),
            "target": round(target, 3),
            "target_r": round(target_r, 3),
            "source_zone": source_zone,
            "clear_bias_gate": assessment,
            "confirmation": {
                "m5": ((bias.get("timeframes") or {}).get("M5") or {}).get("direction"),
                "m15": ((bias.get("timeframes") or {}).get("M15") or {}).get("direction"),
                "overall": overall,
                "entry_resolution": resolution,
                "m1_bar_time": bar_time.isoformat(),
            },
            "trade": adjusted,
            "setup": setup,
        }

    blockers = {
        "outside_session": int(diagnostics["broker_or_session_blocked"]),
        "bias_not_expected": int(diagnostics["bias_not_expected"]),
        "clear_bias": int(diagnostics["clear_bias_blocked"]),
        "no_ranked_zone": int(diagnostics["ranked_zone_missing"]),
        "zone_not_touched": int(diagnostics["zone_not_touched"]),
        "candidate_rejected_after_touch": int(diagnostics["candidate_rejected_after_touch"]),
    }
    diagnostics["primary_blocker"] = max(blockers, key=blockers.get) if any(blockers.values()) else "no_entry"
    return None


async def _replay_episode_v70(self: v68.ZoneRetraceLivePolicyReplayer, row: dict[str, Any]) -> dict[str, Any]:
    self._last_entry_search_diagnostics_v70 = {}
    result = dict(await _prior_replay_episode(self, row))
    diagnostics = dict(getattr(self, "_last_entry_search_diagnostics_v70", {}) or {})
    if diagnostics:
        details = dict(result.get("details") or {})
        details["entry_search_diagnostics"] = diagnostics
        result["details"] = details
    return result


def _runtime_status_v70(self: core.LiveTrader) -> dict[str, Any]:
    status = dict(_current_runtime_status(self))
    status.update(
        {
            "zone_retrace_replay_diagnostic_version": DIAGNOSTIC_VERSION,
            "zone_retrace_replay_gate_funnel_recorded": True,
        }
    )
    return status


v68.ZoneRetraceLivePolicyReplayer._find_entry = _find_entry_v70
v68.ZoneRetraceLivePolicyReplayer._replay_episode = _replay_episode_v70
core.LiveTrader.runtime_status = _runtime_status_v70  # type: ignore[method-assign]
