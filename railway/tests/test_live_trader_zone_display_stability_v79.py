from pathlib import Path


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def test_live_trader_zone_display_has_hysteresis_without_changing_backend_logic() -> None:
    root = _repo_root()
    js = (root / "frontend" / "live_trader_audit_v60.js").read_text(encoding="utf-8")

    assert "ZONE_MIN_HOLD_MS = 20000" in js
    assert "ZONE_ABSOLUTE_GAIN_ATR = 0.35" in js
    assert "ZONE_RELATIVE_RATIO = 0.70" in js
    assert "challengerEntered" in js
    assert "meaningfullyCloser" in js
    assert "stabilizeLiveTraderPayload" in js
    assert "String(path || '') === '/live-trader'" in js
    assert "window.api = wrapped" in js


def test_zone_stability_is_frontend_only_and_build_is_cache_busted() -> None:
    root = _repo_root()
    canonical = (root / "frontend" / "live_trader_intelligence_meter.js").read_text(encoding="utf-8")
    static = (root / "railway" / "app" / "static" / "live_trader_intelligence_meter.js").read_text(encoding="utf-8")

    assert "const UI_BUILD = '79'" in canonical
    assert canonical == static
