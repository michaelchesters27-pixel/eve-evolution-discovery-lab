from pathlib import Path

from app.web import STATIC_DIR, app


PUBLISHED = {
    "app.js",
    "evidence_panel.js",
    "index.html",
    "intelligence.js",
    "live_trader.css",
    "live_trader.js",
    "live_trader_academy.js",
    "live_trader_events.js",
    "live_trader_intelligence_meter.js",
    "live_trader_news.js",
    "live_trader_news_week_confirmation.js",
    "live_trader_trade_outcomes.js",
    "styles.css",
}


def test_railway_frontend_mount_is_last_and_api_routes_remain_first():
    assert STATIC_DIR.is_dir()
    assert app.routes[-1].name == "eve-frontend"
    paths = [getattr(route, "path", None) for route in app.routes[:-1]]
    assert "/health" in paths
    assert "/api/live-trader" in paths
    assert "/api/live-trader/learning" in paths
    assert "/api/live-trader/chat" in paths


def test_railway_static_bundle_is_complete():
    actual = {item.name for item in Path(STATIC_DIR).iterdir() if item.is_file()}
    assert actual == PUBLISHED


def test_railway_static_bundle_matches_canonical_frontend():
    root = Path(__file__).resolve().parents[2]
    canonical = root.parent / "frontend"
    # CI checks out the whole repository. This guard prevents future frontend
    # edits from silently diverging from the Railway-hosted copy.
    if not canonical.is_dir():
        return
    for name in PUBLISHED:
        assert (STATIC_DIR / name).read_bytes() == (canonical / name).read_bytes(), name
