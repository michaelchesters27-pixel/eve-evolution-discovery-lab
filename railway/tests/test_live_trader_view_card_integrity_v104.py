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
        assert "ctx.context_valid !== true" in source or "ctx.context_valid === true" in source
        assert "ctx.fresh !== true" in source or "ctx.fresh === true" in source
        assert "dq.live_context_stale === true" in source or "dq.live_context_stale !== true" in source
        assert "dq.trade_bias_blocked === true" in source or "dq.trade_bias_blocked !== true" in source

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

    assert "Global buy structural ref" in stops
    assert "Global sell structural ref" in stops
    assert "use zone-specific SL refs above" in stops
    assert "REF COVERS NEARBY SWEEPS" in stops
    assert "ALREADY PROTECTED" not in stops
    assert "price - safeAtr * 1.5" not in stops
    assert "price + safeAtr * 1.5" not in stops
    assert "ATR DATA INVALID" in stops
    assert "safeAtr <= 0" in stops


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
    assert "${safe(fmt(retrace.low))} – ${safe(fmt(retrace.high))}" in session
    assert "${fmt(test.low)} – ${fmt(test.high)}" in tolerance


def test_eve_view_zone_labels_expose_side_strength_and_backing() -> None:
    session = (_frontend() / "live_trader_session_outlook_v55.js").read_text(encoding="utf-8")
    tolerance = (_frontend() / "live_trader_zone_decision_tolerance_v82.js").read_text(encoding="utf-8")

    for source in (session, tolerance):
        assert "POTENTIAL" in source
        assert "ZONE" in source
        assert "H1 + M15 BACKED" in source
        assert "M15 BACKED" in source
        assert "H1 BACKED" in source
        assert "M5 ONLY" in source
        assert "QUALITY" in source
        assert "TOUCH BAR" in source
        assert "FRESH" in source
        assert "USED" in source

    assert "POTENTIAL ${safe(retrace.side)} ZONE" in session
    assert "POTENTIAL ${side} ZONE" in tolerance


def test_eve_view_always_lists_relevant_buy_and_sell_chart_zones() -> None:
    session = (_frontend() / "live_trader_session_outlook_v55.js").read_text(encoding="utf-8")

    assert "RELEVANT CHART ZONES" in session
    assert "chartZoneColumn(state, 'demand', 'BUY')" in session
    assert "chartZoneColumn(state, 'supply', 'SELL')" in session
    assert "${side} ZONES" in session
    assert "LIVE PRICE + COMPLETED M5 MAP · NEAREST FIRST" in session
    assert "chartZoneRows(state, kind)" in session
    assert "state?.chart_zones?.[kind]" in session
    assert "state?.chart_zones || state?.zones || {}" not in session
    assert ".sort((a,b) => a.distance - b.distance)" in session
    assert ".slice(0, 3)" not in session
    assert "H1 + M15 BACKED" in session
    assert "M15 BACKED" in session
    assert "H1 BACKED" in session
    assert "M5 ONLY" in session
    assert "QUALITY" in session
    assert "TOUCH BAR" in session
    assert "FRESH" in session and "USED" in session
    assert "Only AUTHORITATIVE TRADE ACTION is execution authority" in session
    assert "api('/live-trader')" not in session
    assert 'api("/live-trader")' not in session


def test_eve_view_chart_zones_have_zone_specific_sweep_aware_sl_refs() -> None:
    session = (_frontend() / "live_trader_session_outlook_v55.js").read_text(encoding="utf-8")

    assert "ZONE_SL_HUNT_BAND_ATR = 1.25" in session
    assert "ZONE_SL_BUFFER_ATR = 0.22" in session
    assert "function zoneSpecificSlReference(state, kind, low, high)" in session
    assert "reclaimedLiquidityKeysForZoneSl" in session
    assert "prior sell-side sweep extreme" in session
    assert "prior buy-side sweep extreme" in session
    assert "SWEEP-PROTECTED STRUCTURAL REF" in session
    assert "LIQUIDITY-PROTECTED STRUCTURAL REF" in session
    assert "ZONE EDGE + ATR BUFFER" in session
    assert "SL REF UNAVAILABLE" in session
    assert "ATR DATA INVALID" in session
    assert "Math.abs(level - edge) <= huntBand" in session
    assert "Math.abs(extreme - edge) <= huntBand" in session
    assert "Only AUTHORITATIVE TRADE ACTION is execution authority" in session


def test_chart_zone_panel_uses_persistent_valid_zone_feed() -> None:
    session = (_frontend() / "live_trader_session_outlook_v55.js").read_text(encoding="utf-8")
    core = (Path(__file__).resolve().parents[2] / "railway" / "app" / "services" / "live_trader.py").read_text(encoding="utf-8")

    assert "state?.chart_zones?.[kind]" in session
    assert "UNDER PRESSURE" in session
    assert "BROKEN IF M5 CLOSES <" in session
    assert "BROKEN IF M5 CLOSES >" in session
    backend = (Path(__file__).resolve().parents[2] / "railway" / "app" / "services" / "live_trader_authoritative_state_v94.py").read_text(encoding="utf-8")
    assert '"chart_zones": getattr(self, "_chart_zones_v95", zones)' in core
    assert '"fallback_used": False' in backend
    assert "strict_chart_zone_feed_unavailable" in backend


def test_chart_zone_backend_uses_actual_zone_edge_not_trade_atr_tolerance() -> None:
    backend = (Path(__file__).resolve().parents[2] / "railway" / "app" / "services" / "live_trader_mtf_zones_v63.py").read_text(encoding="utf-8")

    assert "def _chart_zone_broken_by_completed_m5_close" in backend
    assert 'kind == "demand" and close < low' in backend
    assert 'kind == "supply" and close > high' in backend
    assert "origin_index + 9" in backend
    assert "atr * 0.2" not in backend[backend.index("def _chart_zone_broken_by_completed_m5_close"):backend.index("def _chart_zones_v95")]


def test_chart_zone_panel_is_easy_live_trading_cockpit() -> None:
    session = (_frontend() / "live_trader_session_outlook_v55.js").read_text(encoding="utf-8")

    assert "function zoneCockpitSummary(state)" in session
    assert "LIVE PRICE" in session
    assert "TRADE ACTION" in session
    assert "NEAREST BUY" in session
    assert "NEAREST SELL" in session
    assert "DISTANCE" in session
    assert "INVALIDATION" in session
    assert "OPPOSING ZONE" in session
    assert "CURRENT M5 / M15 STRUCTURE" in session
    assert "BROKEN IF M5 CLOSES <" in session
    assert "BROKEN IF M5 CLOSES >" in session
    assert "NEXT ${zone.opposing.side}" in session
    assert "GAP ${fmt(zone.opposing.gap)} PTS" in session
    assert "NEAREST</span>" in session
    assert "BEST MTF RANK</span>" in session
    assert "CURRENT STRUCTURE FAVOURS ${side}" in session
    assert "CURRENT STRUCTURE IS AGAINST ${side}" in session
    assert "MIXED CURRENT STRUCTURE" in session
    assert "state?.chart_zones?.[kind]" in session
    assert "state?.zones?.[kind]" not in session



def test_public_copilot_fail_closed_countermeasures_are_present() -> None:
    frontend = _frontend()
    base = (frontend / "live_trader.js").read_text(encoding="utf-8")
    session = (frontend / "live_trader_session_outlook_v55.js").read_text(encoding="utf-8")
    stops = (frontend / "live_trader_safe_stops_v48.js").read_text(encoding="utf-8")
    tolerance = (frontend / "live_trader_zone_decision_tolerance_v82.js").read_text(encoding="utf-8")

    assert "failClosedState" in base
    assert "renderState(failClosedState(lastState" in base
    assert "MAX_TICK_AGE_SECONDS = 90" in base
    assert "MAX_DECISION_AGE_MINUTES = 15" in base
    assert "live tick is too old or unavailable" in base
    assert "ATR is unavailable" in base
    assert "forceWait" in session
    assert "DATA NOT VALID" in session
    assert "PRICE TICK" in session and "COMPLETED M5" in session
    assert "SAME SNAPSHOT" not in session
    for source in (session, stops, tolerance):
        assert "MAX_TICK_AGE_SECONDS = 90" in source
        assert "MAX_DECISION_AGE_MINUTES = 15" in source


def test_chart_zone_public_semantics_name_actual_metrics() -> None:
    session = (_frontend() / "live_trader_session_outlook_v55.js").read_text(encoding="utf-8")

    assert "BEST MTF RANK" in session
    assert "STRONGEST" not in session
    assert "HEURISTIC QUALITY" in session
    assert "TOUCH BAR" in session
    assert "retest_metric" not in session  # backend provenance, not a fake UI claim
    assert "CURRENT M5 / M15 STRUCTURE" in session
    assert "REACTION</span>" not in session
    assert "M5/M15 is current global structure, not proof that price reacted" in session
    assert "item.low <= high && item.high >= low" in session
    assert "gap:0" in session


def test_chart_zone_objects_require_unique_ids_and_strict_provenance() -> None:
    session = (_frontend() / "live_trader_session_outlook_v55.js").read_text(encoding="utf-8")
    tolerance = (_frontend() / "live_trader_zone_decision_tolerance_v82.js").read_text(encoding="utf-8")

    assert "state?.chart_zones_status?.available !== true" in session
    assert "idCounts.get(id) === 1" in session
    assert "ZONE DATA UNAVAILABLE" in session
    assert "state?.chart_zones_status?.available !== true" in tolerance
    assert "idCounts.get(id) !== 1" in tolerance
    assert "leftId.length > 0 && rightId.length > 0" in tolerance


def test_exact_zone_confirmation_is_bound_to_source_zone() -> None:
    session = (_frontend() / "live_trader_session_outlook_v55.js").read_text(encoding="utf-8")
    tolerance = (_frontend() / "live_trader_zone_decision_tolerance_v82.js").read_text(encoding="utf-8")

    for source in (session, tolerance):
        assert "source_zone" in source
        assert "sourceZoneId" in source
    assert "sourceZoneId === test.id" in tolerance
    assert "test.wasInside === true" in tolerance
    assert "APPROACHING ZONE — WAIT" in tolerance
    assert "TEST WINDOW EXPIRED — WAIT" in tolerance
    assert "ACTIVE FOR 20 MIN AFTER ACTUAL TOUCH" in tolerance
