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
    assert "state?.zones?.[kind]" in canonical
    assert "M5" in canonical and "M15" in canonical
    assert "fetch('/api/live-trader'" in canonical

    forbidden = ["state.trade =", "state['trade'] =", "_trade_idea", "order_type =", "fetch('/api/trade"]
    assert all(token not in canonical for token in forbidden)
