from pathlib import Path


def test_live_trader_voice_governor_is_shared_and_semantic() -> None:
    root = Path(__file__).resolve().parents[1]
    trader = (root / "frontend" / "live_trader.js").read_text(encoding="utf-8")
    events = (root / "frontend" / "live_trader_events.js").read_text(encoding="utf-8")

    assert "eve-live-voice-governor-v1" in trader
    assert "window.eveLiveVoice" in trader
    assert "marketChangeAnnouncement" in trader
    assert "zones?.demand?.[0]?.id" not in trader
    assert "zones?.supply?.[0]?.id" not in trader
    assert "feed:stale" in trader
    assert "trade:cancel:" in trader
    assert "bias:" in trader
    assert "zone:${kind}:in:" in trader

    assert "window.eveLiveVoice?.say" in events
    assert "event:${eventSig}" in events
    assert "cooldownMs" in events
    assert "tradeSig === lastTradeSignature" not in events
