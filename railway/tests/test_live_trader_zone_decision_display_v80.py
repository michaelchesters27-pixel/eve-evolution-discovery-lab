from pathlib import Path


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def test_zone_decision_pulse_is_on_zone_and_display_only():
    root = _repo_root()
    canonical = (root / "frontend" / "live_trader_session_outlook_v55.js").read_text(encoding="utf-8")
    production = (root / "railway" / "app" / "static" / "live_trader_session_outlook_v55.js").read_text(encoding="utf-8")

    assert canonical == production
    assert "function zoneDecision(state, direction, retrace)" in canonical
    assert "if (!retrace?.inZone) return null" in canonical
    assert "timeframeDirection(state, 'M5')" in canonical
    assert "timeframeDirection(state, 'M15')" in canonical
    assert "REJECTION BUILDING" in canonical
    assert "BREAK BUILDING" in canonical
    assert "UNDECIDED — WAIT" in canonical
    assert "REJECTION CONFIRMED" in canonical
    assert "zone_retrace_v1" in canonical
    assert "zone_retrace_confirmation" in canonical
    assert "Only EVE's existing live trade state can confirm a trade" in canonical

    forbidden = ["_trade_idea", "state.trade =", "state['trade'] =", "fetch('/api/trade", "order_type ="]
    assert all(token not in canonical for token in forbidden)
