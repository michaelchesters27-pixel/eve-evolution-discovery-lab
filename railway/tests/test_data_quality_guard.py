import asyncio
import math
from types import SimpleNamespace

from app.services import fabric_builder as fabric_builder_module
from app.services.data_quality_guard import (
    DATA_QUALITY_GUARD_VERSION,
    GuardedFabricBuilder,
    GuardedSourceRepository,
    usable_atr,
)


class FakeReadClient:
    def __init__(self):
        self.calls = []

    async def get(self, table, *, params=None, range_start=None, range_end=None):
        self.calls.append((table, dict(params or {})))
        if str((params or {}).get("order") or "").endswith("desc"):
            return [{"candle_time": "2026-08-20T20:10:00+00:00", "atr_14": 1.2}]
        return [{"candle_time": "2026-08-20T20:00:00+00:00", "atr_14": 1.1}]


class FakeWriteClient:
    def __init__(self):
        self.upserts = []

    async def upsert(self, table, rows, *, on_conflict, return_rows=False):
        self.upserts.append((table, rows, on_conflict))
        return []


class FakeRepo:
    def __init__(self):
        self.client = FakeWriteClient()
        self.events = []

    async def event(self, level, component, message, details):
        self.events.append((level, component, message, details))


def source_settings():
    return SimpleNamespace(
        source_supabase_url="https://example.invalid",
        source_read_key="test-key",
        source_credential_mode="read_only",
        source_symbol="XAU/USD",
        source_snapshot_interval="15min",
        source_candle_interval="5min",
        source_page_size=100,
    )


def test_usable_atr_requires_finite_positive_value():
    assert usable_atr(0.001)
    assert usable_atr("1.25")
    assert not usable_atr(0)
    assert not usable_atr(-0.01)
    assert not usable_atr(None)
    assert not usable_atr(math.nan)
    assert not usable_atr(math.inf)


def test_source_snapshot_queries_exclude_non_positive_atr():
    source = GuardedSourceRepository(source_settings())
    fake = FakeReadClient()
    source.client = fake

    latest = asyncio.run(source.latest_snapshot_time())
    rows = asyncio.run(source.fetch_snapshots_after(None, limit=5))

    assert latest == "2026-08-20T20:10:00+00:00"
    assert rows
    snapshot_calls = [params for table, params in fake.calls if table == "market_learning_snapshots"]
    assert len(snapshot_calls) == 2
    assert all(params.get("atr_14") == "gt.0" for params in snapshot_calls)
    assert all(params.get("outcome_complete") == "eq.true" for params in snapshot_calls)


def test_fabric_builder_export_is_guarded_at_startup():
    assert fabric_builder_module.FabricBuilder is GuardedFabricBuilder


def test_invalid_fabric_snapshot_is_quarantined_with_audit_event():
    repo = FakeRepo()
    builder = GuardedFabricBuilder(SimpleNamespace(source_symbol="XAU/USD"), None, repo)
    row = {
        "symbol": "XAU/USD",
        "candle_time": "2025-04-18T20:15:00+00:00",
        "atr_14": 0,
        "open": 3326.27,
        "high": 3326.27,
        "low": 3326.27,
        "close": 3326.27,
    }

    asyncio.run(builder._quarantine_invalid_snapshots([row]))

    assert len(repo.client.upserts) == 1
    table, payloads, conflict = repo.client.upserts[0]
    assert table == "research_data_quarantine"
    assert conflict == "source_table,record_key"
    assert payloads[0]["source_table"] == "m5_research_snapshots"
    assert payloads[0]["payload"]["atr_14"] == 0
    assert repo.events[0][1] == "data_integrity"
    assert repo.events[0][3]["guard_version"] == DATA_QUALITY_GUARD_VERSION
