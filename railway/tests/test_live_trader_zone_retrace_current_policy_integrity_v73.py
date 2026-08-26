import asyncio

from app.services import live_trader_zone_retrace_current_policy_integrity_v73 as v73


def test_no_entry_result_preserves_directional_side() -> None:
    original = v73._original_replay_current_opportunity

    async def fake_replay(self, opportunity):
        return {
            "status": "no_entry",
            "entry_at": None,
            "details": {"entry_policy": "test"},
        }

    try:
        v73._original_replay_current_opportunity = fake_replay
        result = asyncio.run(
            v73._replay_current_opportunity_v73(
                object(),
                {"side": "SELL", "bias": "bearish"},
            )
        )
    finally:
        v73._original_replay_current_opportunity = original

    assert result["side"] == "SELL"
    assert result["details"]["side_preserved_without_entry"] is True
    assert result["details"]["current_policy_integrity_version"] == v73.INTEGRITY_VERSION


def test_scan_cycle_claims_and_releases_database_lease() -> None:
    original = v73._original_run_cycle
    calls = []

    class Client:
        async def rpc(self, name, payload):
            calls.append((name, payload))
            if name == "claim_live_trader_zone_retrace_current_policy_scan":
                return [{"claimed": True, "claim_token": "token-123"}]
            if name == "release_live_trader_zone_retrace_current_policy_scan":
                return True
            raise AssertionError(name)

    class Dummy:
        symbol = "XAU/USD"
        repo = type("Repo", (), {"client": Client()})()

    async def fake_cycle(self):
        return True

    try:
        v73._original_run_cycle = fake_cycle
        result = asyncio.run(v73._run_cycle_v73(Dummy()))
    finally:
        v73._original_run_cycle = original

    assert result is True
    assert calls[0][0] == "claim_live_trader_zone_retrace_current_policy_scan"
    assert calls[-1] == (
        "release_live_trader_zone_retrace_current_policy_scan",
        {"p_symbol": "XAU/USD", "p_claim_token": "token-123"},
    )


def test_losing_scan_claim_does_not_execute_archive_cycle() -> None:
    original = v73._original_run_cycle
    executed = False

    class Client:
        async def rpc(self, name, payload):
            if name == "claim_live_trader_zone_retrace_current_policy_scan":
                return [{"claimed": False, "claim_token": None}]
            raise AssertionError(name)

    class Dummy:
        symbol = "XAU/USD"
        repo = type("Repo", (), {"client": Client()})()

    async def fake_cycle(self):
        nonlocal executed
        executed = True
        return True

    try:
        v73._original_run_cycle = fake_cycle
        result = asyncio.run(v73._run_cycle_v73(Dummy()))
    finally:
        v73._original_run_cycle = original

    assert result is True
    assert executed is False
