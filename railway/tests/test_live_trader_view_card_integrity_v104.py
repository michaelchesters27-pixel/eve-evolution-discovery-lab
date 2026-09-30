from pathlib import Path


def _frontend() -> Path:
    return Path(__file__).resolve().parents[2] / "frontend"


def test_eve_view_extensions_use_one_authoritative_snapshot() -> None:
    frontend = _frontend()
    base = (frontend / "live_trader.js").read_text(encoding="utf-8")
    session = (frontend / "live_trader_session_outlook_v55.js").read_text(encoding="utf-8")
    stops = (frontend / "live_trader_safe_stops_v48.js").read_text(encoding="utf-8")
    tolerance = (frontend / "live_trader_zone_decision_tolerance_v82.js").read_text(encoding="utf-8")

    assert "eve:live-trader-state" in base
    assert "window.__eveLiveTraderState = state" in base

    for source in (session, stops, tolerance):
        assert "eve:live-trader-state" in source
        assert "api('/live-trader')" not in source
        assert 'api("/live-trader")' not in source


def test_eve_view_fails_closed_when_context_is_not_valid_and_fresh() -> None:
    session = (_frontend() / "live_trader_session_outlook_v55.js").read_text(encoding="utf-8")
    stops = (_frontend() / "live_trader_safe_stops_v48.js").read_text(encoding="utf-8")
    tolerance = (_frontend() / "live_trader_zone_decision_tolerance_v82.js").read_text(encoding="utf-8")

    for source in (session, stops, tolerance):
        assert "ctx.context_valid === true" in source
        assert "ctx.fresh === true" in source
        assert "dq.live_context_stale !== true" in source
        assert "dq.trade_bias_blocked !== true" in source

    assert "WAIT — DATA NOT VALID" in session
    assert "Directional outlook, BOS/CHoCH, retrace zones and stop references must not be trusted" in session
    assert "UNAVAILABLE" in stops


def test_session_card_distinguishes_opinion_from_authoritative_trade_action() -> None:
    session = (_frontend() / "live_trader_session_outlook_v55.js").read_text(encoding="utf-8")
    copy = (_frontend() / "live_trader_session_copy_v81.js").read_text(encoding="utf-8")
    base = (_frontend() / "live_trader.js").read_text(encoding="utf-8")

    assert "AUTHORITATIVE TRADE ACTION" in session
    assert "SESSION LEAN" in session
    assert "LEAN STRENGTH · NOT WIN RATE" in session
    assert "Session lean is an opinion, not a trade signal." in session
    assert "HEADWINDS / OPPOSING EVIDENCE" in session
    assert "Bias confidence" in base
    assert "not win rate" in base

    assert "SESSION LEAN invalidates" in copy
    assert "This is not a trade cancellation" in copy
    assert "Cancel it only" not in copy


def test_retrace_watch_uses_current_live_policy_geometry_not_any_far_zone() -> None:
    session = (_frontend() / "live_trader_session_outlook_v55.js").read_text(encoding="utf-8")

    assert "LIVE_ZONE_MAX_DISTANCE_ATR = 1.8" in session
    assert "LIVE_ZONE_MIN_QUALITY = 58" in session
    assert "biasDirection !== direction" in session
    assert "WATCH AREA — NO TRADE YET" in session
    assert "NO QUALIFIED RETRACE PLAN" in session
    assert "authoritative trade state" in session


def test_stop_cards_are_structural_references_not_claimed_safe_trade_stops() -> None:
    stops = (_frontend() / "live_trader_safe_stops_v48.js").read_text(encoding="utf-8")

    assert "Buy structural SL ref" in stops
    assert "Sell structural SL ref" in stops
    assert "Reference only · not a live trade stop" in stops
    assert "REF COVERS NEARBY SWEEPS" in stops
    assert "ALREADY PROTECTED" not in stops
    assert "price - safeAtr * 1.5" not in stops
    assert "price + safeAtr * 1.5" not in stops
    assert "return {level:null, sources:[], available:false}" in stops


def test_eve_view_labels_explain_setup_and_magnet_semantics() -> None:
    base = (_frontend() / "live_trader.js").read_text(encoding="utf-8")

    assert "EVE'S VIEW · TRADE BIAS" in base
    assert "<span>Trade action</span>" in base
    assert "Setup gate:" in base
    assert "<span>Market session</span>" in base
    assert "<span>Bias-side magnet</span>" in base
    assert "Nearest level in current bias direction" in base


def test_eve_view_shows_pending_bos_level_and_zone_coordinates() -> None:
    session = (_frontend() / "live_trader_session_outlook_v55.js").read_text(encoding="utf-8")
    tolerance = (_frontend() / "live_trader_zone_decision_tolerance_v82.js").read_text(encoding="utf-8")

    assert "Next BOS level" in session
    assert "completed M5 close must finish" in session
    assert "max(2% ATR, 0.01)" in session
    assert "ZONE ${safe(fmt(retrace.low))} – ${safe(fmt(retrace.high))}" in session
    assert "ZONE ${fmt(test.low)} – ${fmt(test.high)}" in tolerance
