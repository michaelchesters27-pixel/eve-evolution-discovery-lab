from __future__ import annotations

from app.services import live_trader as core
from app.services import live_trader_clear_bias_gate_v45 as v45


def modern_bias(
    *,
    overall: str = "bullish",
    confidence: int = 72,
    d1: str = "bullish",
    h4: str = "bullish",
    h1: str = "bullish",
    m30: str = "bullish",
    m15: str = "bullish",
    blocked: bool = False,
) -> dict:
    directions = {"D1": d1, "H4": h4, "H1": h1, "M30": m30, "M15": m15, "M5": overall, "M1": overall}
    return {
        "overall": overall,
        "confidence": confidence,
        "panel_bias_version": v45.STRUCTURAL_PANEL_VERSION,
        "timeframes": {
            timeframe: {
                "direction": direction,
                "method": "multi_candle_structure" if timeframe != "M1" else "microstructure_diagnostic",
            }
            for timeframe, direction in directions.items()
        },
        "data_quality": {
            "trade_bias_blocked": blocked,
            "critical_stale": ["H4"] if blocked else [],
        },
    }


def test_neutral_bias_cannot_publish_new_trade(monkeypatch) -> None:
    trader = core.LiveTrader.__new__(core.LiveTrader)
    trader._live_campaign = None

    def should_not_run(*args, **kwargs):
        raise AssertionError("underlying trade generator must not run without clear bias")

    monkeypatch.setattr(v45, "_original_trade_idea", should_not_run)
    bias = modern_bias(overall="neutral", confidence=80, d1="neutral", h4="neutral", h1="neutral", m30="neutral", m15="neutral")

    setup, trade = v45._trade_idea_v45(trader, 4600.0, 8.0, bias, {}, {})

    assert setup["status"] == "BIAS WAIT"
    assert trade["action"] == "WAIT"
    assert trade["clear_bias_blocked"] is True
    assert any("not directional" in reason for reason in trade["clear_bias_gate"]["reasons"])


def test_low_confidence_directional_bias_is_blocked(monkeypatch) -> None:
    trader = core.LiveTrader.__new__(core.LiveTrader)
    trader._live_campaign = None
    monkeypatch.setattr(v45, "_original_trade_idea", lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("must not run")))

    _, trade = v45._trade_idea_v45(trader, 4600.0, 8.0, modern_bias(confidence=64), {}, {})

    assert trade["action"] == "WAIT"
    assert any("below 65" in reason for reason in trade["clear_bias_gate"]["reasons"])


def test_mixed_higher_timeframes_are_not_clear_bias(monkeypatch) -> None:
    trader = core.LiveTrader.__new__(core.LiveTrader)
    trader._live_campaign = None
    monkeypatch.setattr(v45, "_original_trade_idea", lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("must not run")))

    _, trade = v45._trade_idea_v45(
        trader,
        4600.0,
        8.0,
        modern_bias(h4="bearish", d1="bullish", h1="bullish", m30="bullish", m15="bullish"),
        {},
        {},
    )

    assert trade["action"] == "WAIT"
    assert any("H4 is not aligned" in reason for reason in trade["clear_bias_gate"]["reasons"])


def test_strong_opposing_market_event_blocks_trade(monkeypatch) -> None:
    trader = core.LiveTrader.__new__(core.LiveTrader)
    trader._live_campaign = None
    monkeypatch.setattr(v45, "_original_trade_idea", lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("must not run")))
    liquidity = {
        "primary_event": {
            "event_class": "accepted_breakout_down",
            "label": "BREAKDOWN HOLDING BELOW",
            "implication": "bearish",
            "strength": 84,
        }
    }

    _, trade = v45._trade_idea_v45(trader, 4600.0, 8.0, modern_bias(), {}, liquidity)

    assert trade["action"] == "WAIT"
    assert any("strongly opposed" in reason for reason in trade["clear_bias_gate"]["reasons"])


def test_clear_bias_reaches_existing_execution_chain(monkeypatch) -> None:
    trader = core.LiveTrader.__new__(core.LiveTrader)
    trader._live_campaign = None
    expected_trade = {"action": "BUY LIMIT", "order_type": "buy_limit", "entry": 4600.0}
    monkeypatch.setattr(
        v45,
        "_original_trade_idea",
        lambda *args, **kwargs: ({"status": "ARMED", "reason": "candidate"}, dict(expected_trade)),
    )

    setup, trade = v45._trade_idea_v45(trader, 4600.0, 8.0, modern_bias(), {}, {})

    assert setup["status"] == "ARMED"
    assert trade["action"] == "BUY LIMIT"
    assert trade["clear_bias_gate"]["clear"] is True
    assert trade["clear_bias_gate"]["aligned_critical_timeframes"] == 5


def test_existing_active_campaign_is_managed_even_if_bias_turns_unclear(monkeypatch) -> None:
    trader = core.LiveTrader.__new__(core.LiveTrader)
    trader._live_campaign = {"status": "active", "id": "locked"}
    monkeypatch.setattr(
        v45,
        "_original_trade_idea",
        lambda *args, **kwargs: (
            {"status": "TRADE ACTIVE", "reason": "locked"},
            {"action": "BUY ACTIVE", "order_type": "buy_limit", "entry": 4600.0},
        ),
    )
    bias = modern_bias(overall="neutral", confidence=40, d1="neutral", h4="neutral", h1="neutral", m30="neutral", m15="neutral")

    setup, trade = v45._trade_idea_v45(trader, 4600.0, 8.0, bias, {}, {})

    assert setup["status"] == "TRADE ACTIVE"
    assert trade["action"] == "BUY ACTIVE"


def test_legacy_deterministic_helper_payloads_remain_compatible(monkeypatch) -> None:
    trader = core.LiveTrader.__new__(core.LiveTrader)
    trader._live_campaign = None
    monkeypatch.setattr(
        v45,
        "_original_trade_idea",
        lambda *args, **kwargs: ({"status": "WATCHING"}, {"action": "NO TRADE", "order_type": "none"}),
    )

    setup, trade = v45._trade_idea_v45(trader, 4600.0, 8.0, {"overall": "bullish", "confidence": 60}, {}, {})

    assert setup["clear_bias_gate"]["compatibility_bypass"] is True
    assert trade["clear_bias_gate"]["compatibility_bypass"] is True
