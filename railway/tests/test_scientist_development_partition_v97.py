from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from types import SimpleNamespace

from app.services import backtest
from app.services import research_fabric


def row(year: int, index: int = 0) -> dict:
    return {
        "symbol": "XAU/USD",
        "snapshot_interval": "5min",
        "source_interval": "5min",
        "candle_time": datetime(year, 1, 1, 0, index, tzinfo=timezone.utc).isoformat(),
        "close": 1800.0 + year,
        "outcomes": {},
        "outcome_complete": True,
        "feature_version": "fixture",
    }


def test_presegmented_development_rows_equal_original_calendar_development_partition() -> None:
    full = [row(year, index) for year in range(2020, 2027) for index in range(2)]
    original = backtest.chronological_segments(full)
    expected = list(original["development"])

    partition = research_fabric.DevelopmentResearchRows(
        expected,
        {
            "years": original["years"],
            "method": original["method"],
            "total_rows": len(full),
            "development_rows": len(expected),
            "development_before": "2024-01-01T00:00:00+00:00",
        },
    )
    bounded = backtest.chronological_segments(partition)

    assert bounded["development"] == expected
    assert bounded["validation"] == []
    assert bounded["confirmation"] == []
    assert bounded["holdout"] == []
    assert bounded["years"] == original["years"]
    assert bounded["method"] == original["method"]
    assert bounded["full_dataset_rows"] == len(full)
    assert bounded["presegmented_development_only"] is True


class FakeFabricClient:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict]] = []
        self.rows = [row(2020), row(2021), row(2022)]

    async def rpc(self, function: str, payload: dict):
        assert function == "get_scientist_fabric_split_v97"
        return {
            "version": research_fabric.SCIENTIST_DEVELOPMENT_SPLIT_VERSION,
            "complete_server_side_split": True,
            "method": "calendar_year_four_stage",
            "years": [2020, 2021, 2022, 2023, 2024, 2025, 2026],
            "total_rows": 7,
            "development_rows": 3,
            "development_before": "2024-01-01T00:00:00+00:00",
        }

    async def get(self, table: str, *, params: dict | None = None, **_kwargs):
        assert table == "m5_scientist_research"
        params = dict(params or {})
        self.calls.append((table, params))
        return list(self.rows)


def test_scientist_loader_reads_only_declared_development_partition() -> None:
    client = FakeFabricClient()
    repo = SimpleNamespace(client=client)

    rows = asyncio.run(research_fabric.load_scientist_development_rows(repo, "XAU/USD"))

    assert len(rows) == 3
    assert rows.development_partition["total_rows"] == 7
    assert rows.development_partition["development_rows"] == 3
    assert client.calls[0][1]["candle_time"] == "lt.2024-01-01T00:00:00+00:00"
    assert client.calls[0][1]["limit"] == "3"


class IncompleteFabricClient(FakeFabricClient):
    def __init__(self) -> None:
        super().__init__()
        self.rows = self.rows[:2]


def test_scientist_loader_fails_closed_on_incomplete_partition() -> None:
    repo = SimpleNamespace(client=IncompleteFabricClient())

    try:
        asyncio.run(research_fabric.load_scientist_development_rows(repo, "XAU/USD"))
    except RuntimeError as exc:
        assert "partition incomplete" in str(exc)
    else:
        raise AssertionError("incomplete Scientist partition must fail closed")
