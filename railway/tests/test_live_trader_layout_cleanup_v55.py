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


def test_breakout_language_boundary_never_reparents_live_trader_cards():
    root = _repo_root()
    js = (root / "frontend" / "live_trader_breakout_language_v54.js").read_text(encoding="utf-8")

    assert "Section ownership belongs exclusively" in js
    assert "tradeCard.insertAdjacentElement('afterend', zoneGrid)" not in js
    assert "zoneGrid.insertAdjacentElement('afterend', eventCard)" not in js
    assert "insertAdjacentElement('afterend', zoneGrid)" not in js


def test_live_trader_section_router_has_single_explicit_owner_for_major_cards():
    root = _repo_root()
    js = (root / "frontend" / "live_trader_sections_v59.js").read_text(encoding="utf-8")

    assert "eve-live-trader-sections-v78" in js
    assert "place(closestCard('ltTradeAction'), trade)" in js
    assert "place(closestCard('ltDemand'), zoneHost)" in js
    assert "place(closestCard('ltSupply'), zoneHost)" in js
    assert "place(document.getElementById('ltMarketEventCard'), structure)" in js
    assert "place(document.getElementById('ltZoneRetracePanel'), learning)" in js
    assert "place(document.getElementById('ltWeeklyOutcomesCard'), academyPages.performance)" in js
    assert "place(document.getElementById('ltIntelligenceCard'), academyPages.intelligence)" in js
    assert "place(document.getElementById('ltExecutionIntelligenceCard'), academyPages.intelligence)" in js
    assert "place(document.getElementById('ltNewsCard'), academyPages.news)" in js
    assert "Zone retracement learning" in js


def test_live_trader_integrity_guard_hides_legacy_execution_replies_and_zero_entry_fake_result():
    root = _repo_root()
    js = (root / "frontend" / "live_trader_audit_v60.js").read_text(encoding="utf-8")

    assert "eve-live-trader-ui-integrity-v79" in js
    assert "preferred execution is" in js
    assert "legacyStrategyReply" in js
    assert "Older pre-retracement stop/limit trade replies are archived" in js
    assert "No entries yet" in js
    assert "Waiting for a confirmed entry" in js
    assert "ltZrBody" not in js


def test_live_trader_layout_patch_is_presentation_only():
    root = _repo_root()
    files = [
        root / "frontend" / "live_trader_breakout_language_v54.js",
        root / "frontend" / "live_trader_sections_v59.js",
        root / "frontend" / "live_trader_audit_v60.js",
    ]
    combined = "\n".join(path.read_text(encoding="utf-8") for path in files)

    forbidden = ["_trade_idea", "confidence >=", "risk_reward", "target_policy", "source_zone_required"]
    assert all(token not in combined for token in forbidden)
