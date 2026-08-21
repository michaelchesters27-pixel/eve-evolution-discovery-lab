from __future__ import annotations

import asyncio

from app.services import live_trader_learning_governor_v25 as governor


def candidate_state() -> dict:
    return {
        "setup": {"status": "ARMED", "reason": "Base setup"},
        "trade": {
            "action": "SELL STOP",
            "order_type": "sell_stop",
            "side": "SELL",
            "entry": 4600.0,
            "stop": 4610.0,
            "target": 4580.0,
            "risk_reward": 2.0,
            "manual_only": True,
        },
    }


def learning(*, active: bool, posterior: float, samples: int = 12) -> dict:
    return {
        "active": active,
        "samples": samples,
        "posterior_accuracy": posterior,
    }


def test_mature_bad_family_vetoes_candidate() -> None:
    state = candidate_state()

    governor.apply_learning_governor(state, learning(active=True, posterior=0.40))

    assert state["learning_governor"]["decision"] == "veto"
    assert state["trade"]["action"] == "WAIT"
    assert state["trade"]["order_type"] == "none"
    assert state["trade"]["learning_veto"] is True
    assert state["learning_governor"]["candidate_trade"]["order_type"] == "sell_stop"
    assert state["setup"]["status"] == "WATCHING"


def test_good_mature_family_is_allowed() -> None:
    state = candidate_state()

    governor.apply_learning_governor(state, learning(active=True, posterior=0.61))

    assert state["learning_governor"]["decision"] == "allow"
    assert state["trade"]["order_type"] == "sell_stop"


def test_immature_family_cannot_veto() -> None:
    state = candidate_state()

    governor.apply_learning_governor(state, learning(active=False, posterior=0.20, samples=5))

    assert state["learning_governor"]["decision"] == "insufficient_evidence"
    assert state["trade"]["order_type"] == "sell_stop"


def test_vetoed_candidate_is_shadow_recorded(monkeypatch) -> None:
    state = candidate_state()
    governor.apply_learning_governor(state, learning(active=True, posterior=0.40))
    captured: list[dict] = []

    async def fake_record(_self, payload: dict) -> None:
        captured.append(payload)

    monkeypatch.setattr(governor, "_current_record", fake_record)
    asyncio.run(governor._record_v25(object(), state))

    assert len(captured) == 1
    assert captured[0]["trade"]["order_type"] == "sell_stop"
    assert state["trade"]["order_type"] == "none"
    assert "Shadow candidate rejected" in captured[0]["opinion"]
