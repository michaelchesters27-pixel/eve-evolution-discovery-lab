from pathlib import Path


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def test_live_trader_warning_banners_are_hidden_and_removed():
    root = _repo_root()
    css = (root / "frontend" / "live_trader.css").read_text(encoding="utf-8")
    js = (root / "frontend" / "live_trader_breakout_language_v54.js").read_text(encoding="utf-8")

    assert ".lt-manual-warning{display:none!important}" in css
    assert "querySelectorAll('.lt-manual-warning')" in js
    assert "warning.remove()" in js


def test_live_trader_layout_is_decision_first():
    root = _repo_root()
    js = (root / "frontend" / "live_trader_breakout_language_v54.js").read_text(encoding="utf-8")

    assert "tradeCard.insertAdjacentElement('afterend', zoneGrid)" in js
    assert "zoneGrid.insertAdjacentElement('afterend', eventCard)" in js
    assert "zoneGrid.classList.add('lt-zone-grid')" in js


def test_live_trader_layout_patch_is_presentation_only():
    root = _repo_root()
    js = (root / "frontend" / "live_trader_breakout_language_v54.js").read_text(encoding="utf-8")

    forbidden = ["_trade_idea", "confidence >=", "risk_reward", "target_policy", "source_zone_required"]
    assert all(token not in js for token in forbidden)
