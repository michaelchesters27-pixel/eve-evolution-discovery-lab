import importlib
import os


def load_main():
    os.environ.update({
        "SOURCE_SUPABASE_URL": "https://source.example.supabase.co",
        "SOURCE_SUPABASE_READ_ONLY_KEY": "r" * 32,
        "DISCOVERY_SUPABASE_URL": "https://discovery.example.supabase.co",
        "DISCOVERY_SUPABASE_SERVICE_ROLE_KEY": "d" * 32,
        "ADMIN_TOKEN": "a" * 20,
    })
    return importlib.import_module("app.main")


def complete_passport():
    return {
        "market": "XAU/USD",
        "primary_timeframe": "M5",
        "attach_to_chart": "XAU/USD M5",
        "operating_window": "New York",
        "best_session": "New York",
        "best_regime": "Trend",
        "confidence_score": 80,
        "dataset_version": "unused",
        "deployment_status": "Demo forward testing only",
        "use_when": ["Attach to XAU/USD M5"],
        "avoid_when": ["Avoid high spread"],
        "risk": {"stop_atr": 1, "target_atr": 2, "maximum_hold_minutes": 60, "maximum_spread_points": 100},
        "evidence": {"dataset_version": "dataset-1"},
    }


def test_download_gate_blocks_legacy_pending_package():
    main = load_main()
    ready, reason = main.package_download_ready({
        "profile_status": "pending",
        "download_eligible": False,
        "profile_reason": "Legacy package awaiting profile",
        "trading_passport": {},
        "status": "ready",
    })
    assert ready is False
    assert "Legacy package" in reason


def test_download_gate_allows_only_complete_profile():
    main = load_main()
    ready, reason = main.package_download_ready({
        "profile_status": "complete",
        "download_eligible": True,
        "trading_passport": complete_passport(),
        "status": "ready",
    })
    assert ready is True
    assert reason == "ready"
