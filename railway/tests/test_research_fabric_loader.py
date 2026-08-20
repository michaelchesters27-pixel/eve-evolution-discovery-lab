import asyncio

from app.services import research_fabric
from app.services.research_fabric import load_fabric_rows


class FakeClient:
    def __init__(self):
        self.calls = []

    async def get(self, table, *, params=None, range_start=None, range_end=None):
        self.calls.append(
            {
                "table": table,
                "params": dict(params or {}),
                "range_start": range_start,
                "range_end": range_end,
            }
        )
        cursor = (params or {}).get("candle_time")
        if cursor is None:
            # A full first page forces the loader to request another page.
            return [
                {"candle_time": f"2020-01-01T00:{index % 60:02d}:00+00:00"}
                for index in range(999)
            ] + [{"candle_time": "2020-01-02T00:00:00+00:00"}]
        if cursor == "gt.2020-01-02T00:00:00+00:00":
            return [
                {"candle_time": "2020-01-02T00:05:00+00:00"},
                {"candle_time": "2020-01-02T00:10:00+00:00"},
            ]
        return []


class FakeRepo:
    def __init__(self):
        self.client = FakeClient()


def clear_cache():
    research_fabric._FABRIC_ROW_CACHE.clear()
    research_fabric._FABRIC_CACHE_LOCKS.clear()


def test_full_fabric_load_uses_candle_time_keyset_not_offset_ranges():
    clear_cache()
    repo = FakeRepo()
    rows = asyncio.run(load_fabric_rows(repo, "XAU/USD", complete_only=True))

    assert len(rows) == 1002
    assert len(repo.client.calls) == 2
    first, second = repo.client.calls

    assert first["range_start"] is None
    assert first["range_end"] is None
    assert first["params"]["limit"] == "1000"
    assert first["params"]["outcome_complete"] == "eq.true"
    assert "candle_time" not in first["params"]

    assert second["range_start"] is None
    assert second["range_end"] is None
    assert second["params"]["candle_time"] == "gt.2020-01-02T00:00:00+00:00"
    assert second["params"]["order"] == "candle_time.asc"


def test_normal_refresh_reuses_process_cache_and_scans_only_after_last_row():
    clear_cache()
    repo = FakeRepo()
    first = asyncio.run(load_fabric_rows(repo, "XAU/USD", complete_only=True))
    second = asyncio.run(load_fabric_rows(repo, "XAU/USD", complete_only=True))

    assert first is second
    assert len(second) == 1002
    assert len(repo.client.calls) == 3
    refresh = repo.client.calls[-1]
    assert refresh["params"]["candle_time"] == "gt.2020-01-02T00:10:00+00:00"
    assert refresh["range_start"] is None
    assert refresh["range_end"] is None


def test_explicit_after_scan_does_not_replace_shared_history_cache():
    clear_cache()
    repo = FakeRepo()
    rows = asyncio.run(load_fabric_rows(repo, "XAU/USD", complete_only=True, after="2020-01-02T00:00:00+00:00"))
    assert len(rows) == 2
    assert repo.client.calls[0]["params"]["candle_time"] == "gt.2020-01-02T00:00:00+00:00"
    assert research_fabric._FABRIC_ROW_CACHE == {}


def test_fabric_load_can_include_incomplete_rows_without_complete_filter():
    clear_cache()
    repo = FakeRepo()
    asyncio.run(load_fabric_rows(repo, "XAU/USD", complete_only=False))
    assert "outcome_complete" not in repo.client.calls[0]["params"]
