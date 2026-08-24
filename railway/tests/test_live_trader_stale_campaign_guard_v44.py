from __future__ import annotations

from app.services import live_trader as core
from app.services import live_trader_stale_campaign_guard_v44 as v44


def blocked_bias() -> dict:
    return {
        "overall": "neutral",
        "data_quality": {
            "trade_bias_blocked": True,
            "critical_stale": ["H4"],
        },
    }


def campaign(status: str) -> dict:
    return {
        "version": "eve-live-trade-lock-v1",
        "id": "campaign-test",
        "symbol": "XAU/USD",
        "status": status,
        "side": "SELL",
        "order_type": "sell_limit",
        "entry": 4651.648,
        "stop": 4658.413,
        "target": 4613.565,
        "risk_reward": 5.63,
        "confidence": 69,
        "reason": "Original reason",
        "invalidation": "Cancel above 4658.41",
        "invalidation_price": 4658.41,
        "created_at": "2026-08-24T03:15:56+00:00",
        "expires_at": "2026-08-24T06:15:56+00:00",
        "triggered_at": "2026-08-24T03:20:00+00:00" if status == "active" else None,
        "completed_at": None,
        "result": None,
        "last_price": 4650.0,
        "last_checked_at": "2026-08-24T06:14:00+00:00",
        "published_trade": {
            "action": "SELL LIMIT",
            "side": "SELL",
            "order_type": "sell_limit",
            "entry": 4651.648,
            "stop": 4658.413,
            "target": 4613.565,
        },
    }


def test_pending_campaign_is_cancelled_before_entry_when_critical_bias_is_stale() -> None:
    trader = core.LiveTrader.__new__(core.LiveTrader)
    trader._live_campaign = campaign("pending")
    trader._live_campaign_dirty = False

    setup, trade = v44._trade_idea_v44(trader, 4650.0, 6.0, blocked_bias(), {}, {})

    assert trader._live_campaign["status"] == "invalidated"
    assert trader._live_campaign["triggered_at"] is None
    assert trader._live_campaign["result"].startswith(v44.STALE_RESULT_PREFIX)
    assert trader._live_campaign["data_quality_invalidation"]["critical_stale"] == ["H4"]
    assert trader._live_campaign_dirty is True
    assert setup["status"] == "IDEA CANCELLED"
    assert trade["action"] == "CANCEL — STALE DATA"
    assert trade["order_type"] == "none"
    assert trade["campaign_locked"] is False


def test_active_campaign_is_not_cancelled_or_rewritten(monkeypatch) -> None:
    trader = core.LiveTrader.__new__(core.LiveTrader)
    trader._live_campaign = campaign("active")

    original_trade = {
        "action": "SELL ACTIVE",
        "side": "SELL",
        "order_type": "sell_limit",
        "entry": 4651.648,
        "stop": 4658.413,
        "target": 4613.565,
    }
    monkeypatch.setattr(
        v44,
        "_original_trade_idea",
        lambda self, price, atr, bias, zones, liquidity: (
            {"status": "TRADE ACTIVE", "reason": "Locked trade active."},
            dict(original_trade),
        ),
    )

    setup, trade = v44._trade_idea_v44(trader, 4652.0, 6.0, blocked_bias(), {}, {})

    assert trader._live_campaign["status"] == "active"
    assert trader._live_campaign["stop"] == 4658.413
    assert trader._live_campaign["target"] == 4613.565
    assert trade["entry"] == original_trade["entry"]
    assert trade["stop"] == original_trade["stop"]
    assert trade["target"] == original_trade["target"]
    assert "will not rewrite an active trade" in trade["data_quality_warning"]
    assert "Data warning" in setup["reason"]


def test_no_new_campaign_is_published_while_critical_bias_is_stale(monkeypatch) -> None:
    trader = core.LiveTrader.__new__(core.LiveTrader)
    trader._live_campaign = None

    def should_not_run(*args, **kwargs):
        raise AssertionError("underlying trade generator must not run during a critical stale-data block")

    monkeypatch.setattr(v44, "_original_trade_idea", should_not_run)

    setup, trade = v44._trade_idea_v44(trader, 4650.0, 6.0, blocked_bias(), {}, {})

    assert setup["status"] == "DATA WAIT"
    assert trade["action"] == "WAIT"
    assert trade["order_type"] == "none"
    assert trade["data_quality_blocked"] is True
    assert trade["critical_stale"] == ["H4"]
