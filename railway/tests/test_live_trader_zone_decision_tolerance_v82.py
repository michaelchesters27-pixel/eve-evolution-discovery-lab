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
    assert "EARLY REJECTION — WAIT" in canonical
    assert "REJECTION BUILDING" in canonical
    assert "BREAK BUILDING" in canonical
    assert "REJECTION CONFIRMED" in canonical
    assert "state?.market?.atr" in canonical
    assert "state?.chart_zones?.[kind]" in canonical
    assert "state?.zones?.[kind]" not in canonical
    assert ".slice(0, 3)" not in canonical
    assert "if (left.id && right.id) return left.id === right.id" in canonical
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
    assert "QUALITY ${Math.round(test.quality)}/100" in source
    assert "RETEST" in source
    assert "FRESH" in source and "USED" in source
    assert "state.trade =" not in source
    assert "order_type =" not in source


def test_zone_decision_can_only_use_a_zone_present_in_relevant_chart_zones():
    root = _repo_root()
    source = (root / "frontend" / "live_trader_zone_decision_tolerance_v82.js").read_text(encoding="utf-8")

    assert "state?.chart_zones?.[kind]" in source
    assert "state?.zones?.[kind]" not in source
    assert "never fall back to the more tolerant trade-facing zones array" in source
    assert "id: String(zone?.id || '')" in source
    assert "if (left.id && right.id) return left.id === right.id" in source
