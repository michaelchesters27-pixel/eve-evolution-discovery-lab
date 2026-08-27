from pathlib import Path


PUBLISHED = {
    "app.js",
    "evidence_panel.js",
    "index.html",
    "intelligence.js",
    "live_trader.css",
    "live_trader.js",
    "live_trader_academy.js",
    "live_trader_audit_v60.js",
    "live_trader_breakout_language_v54.js",
    "live_trader_events.js",
    "live_trader_execution_intelligence.js",
    "live_trader_intelligence_meter.js",
    "live_trader_intelligence_meter_core.js",
    "live_trader_news.js",
    "live_trader_news_week_confirmation.js",
    "live_trader_safe_stops_v48.js",
    "live_trader_sections_v59.js",
    "live_trader_session_copy_v81.js",
    "live_trader_session_outlook_v55.js",
    "live_trader_trade_outcomes.js",
    "live_trader_zone_decision_tolerance_v82.js",
    "live_trader_zone_retrace_v58.js",
    "live_trader_zone_truth_v49.js",
    "styles.css",
}


def _paths() -> tuple[Path, Path, Path]:
    railway = Path(__file__).resolve().parents[1]
    repo = railway.parent
    static = railway / "app" / "static"
    canonical = repo / "frontend"
    return railway, static, canonical


def test_railway_frontend_mount_contract_keeps_existing_api_app_authoritative():
    railway, static, _ = _paths()
    web = (railway / "app" / "web.py").read_text(encoding="utf-8")
    main = (railway / "app" / "main.py").read_text(encoding="utf-8")

    assert static.is_dir()
    assert "from app.main import app" in web
    assert 'app.mount("/", StaticFiles' in web
    assert 'name="eve-frontend"' in web
    assert '@app.get("/health")' in main
    assert '@app.get("/api/live-trader"' in main
    assert '@app.get("/api/live-trader/learning"' in main
    assert '@app.post("/api/live-trader/chat"' in main


def test_railway_static_bundle_is_complete():
    _, static, _ = _paths()
    actual = {item.name for item in static.iterdir() if item.is_file()}
    assert actual == PUBLISHED


def test_railway_static_bundle_matches_canonical_frontend():
    _, static, canonical = _paths()
    assert canonical.is_dir()
    for name in PUBLISHED:
        assert (static / name).read_bytes() == (canonical / name).read_bytes(), name
