from pathlib import Path


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def test_zone_decision_tolerance_is_display_only_and_time_bounded():
    root = _repo_root()
    canonical = (root / "frontend" / "live_trader_zone_decision_tolerance_v82.js").read_text(encoding="utf-8")
    production = (root / "railway" / "app" / "static" / "live_trader_zone_decision_tolerance_v82.js").read_text(encoding="utf-8")

    assert canonical == production
    assert "const TOLERANCE_ATR = 0.35" in canonical
    assert "const HOLD_MS = 20 * 60 * 1000" in canonical
    assert "BROWSER-OBSERVED MOVE — WAIT" in canonical
    assert "REJECTION BUILDING" in canonical
    assert "BREAK BUILDING" in canonical
    assert "REJECTION CONFIRMED" in canonical
    assert "state?.market?.atr" in canonical
    assert "window.eveChartZoneContractV99" in canonical
    assert "contract.eligibleZones(state, kind)" in canonical
    assert "state?.zones?.[kind]" not in canonical
    assert ".slice(0, 3)" not in canonical
    assert "leftId.length > 0 && rightId.length > 0" in canonical
    assert "Math.abs(left.low - right.low) <= 0.001" in canonical
    assert "M5" in canonical and "M15" in canonical
    assert "eve:live-trader-state" in canonical
    assert "window.__eveLiveTraderState" in canonical
    assert "api('/live-trader')" not in canonical
    assert "fetch('/api/live-trader'" not in canonical
    assert "ctx.context_valid === true" in canonical
    assert "ctx.fresh === true" in canonical
    assert "eve-zone-tolerance-pulse" in canonical

    forbidden = ["state.trade =", "state['trade'] =", "_trade_idea", "order_type =", "fetch('/api/trade"]
    assert all(token not in canonical for token in forbidden)


def test_zone_decision_labels_buy_sell_potential_without_creating_authority():
    root = _repo_root()
    source = (root / "frontend" / "live_trader_zone_decision_tolerance_v82.js").read_text(encoding="utf-8")

    assert "POTENTIAL ${side} ZONE" in source
    assert "H1 + M15 BACKED" in source
    assert "M5 ONLY" in source
    assert "HEURISTIC QUALITY ${Math.round(test.quality)}/100" in source
    assert "TOUCH BAR" in source
    assert "FRESH" in source and "USED" in source
    assert "state.trade =" not in source
    assert "order_type =" not in source


def test_zone_decision_can_only_use_a_zone_present_in_relevant_chart_zones():
    root = _repo_root()
    source = (root / "frontend" / "live_trader_zone_decision_tolerance_v82.js").read_text(encoding="utf-8")

    assert "window.eveChartZoneContractV99" in source
    assert "contract.eligibleZones(state, kind)" in source
    assert "state?.zones?.[kind]" not in source
    assert "id," in source
    assert "leftId.length > 0 && rightId.length > 0" in source



def test_zone_decision_confirmation_requires_exact_source_zone_and_touch():
    root = _repo_root()
    source = (root / "frontend" / "live_trader_zone_decision_tolerance_v82.js").read_text(encoding="utf-8")

    assert "sourceZoneId === test.id" in source
    assert "Math.abs(sourceZoneLow - test.low) <= 0.001" in source
    assert "Math.abs(sourceZoneHigh - test.high) <= 0.001" in source
    assert "test.wasInside === true" in source
    assert "APPROACHING ZONE — WAIT" in source
    assert "No rejection or break claim is active" in source
    assert "TEST WINDOW EXPIRED — WAIT" in source
    assert "expiredZoneId" in source


def test_zone_decision_rejects_bad_status_ids_atr_and_stale_wall_clock():
    root = _repo_root()
    source = (root / "frontend" / "live_trader_zone_decision_tolerance_v82.js").read_text(encoding="utf-8")
    contract_source = (root / "frontend" / "live_trader_session_outlook_v55.js").read_text(encoding="utf-8")

    assert "['BROKEN','INVALID','EXPIRED'].includes(status)" in contract_source
    assert "idCounts.get(id) === 1" in contract_source
    assert "contract.eligibleZones(state, kind)" in source
    assert "atr == null || atr <= 0" in source
    assert "MAX_TICK_AGE_SECONDS = 90" in source
    assert "MAX_DECISION_AGE_MINUTES = 15" in source
    assert "tickAgeSeconds <= MAX_TICK_AGE_SECONDS" in source
    assert "decisionAgeMinutes <= MAX_DECISION_AGE_MINUTES" in source



def test_zone_decision_states_browser_sampling_limit_for_early_move():
    root = _repo_root()
    source = (root / "frontend" / "live_trader_zone_decision_tolerance_v82.js").read_text(encoding="utf-8")

    assert "BROWSER-OBSERVED MOVE — WAIT" in source
    assert "not reconstructed complete tick history" in source
    assert "ACTIVE 20 MIN AFTER BROWSER-OBSERVED ENTRY" in source
