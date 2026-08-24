from app.services.live_trader_safe_stops_v48 import SAFE_STOPS_VERSION, safe_stop_references


def test_safe_stop_references_clear_nearby_structure_cluster() -> None:
    state = {
        "price": 100.0,
        "market": {"atr": 10.0},
        "zones": {
            "demand": [{"low": 92.0, "high": 95.0}],
            "supply": [{"low": 105.0, "high": 108.0}],
        },
        "liquidity": {
            "recent_low": 93.0,
            "previous_day_low": 80.0,
            "london_low": 91.5,
            "new_york_low": 89.0,
            "recent_high": 107.0,
            "previous_day_high": 120.0,
            "london_high": 108.5,
            "new_york_high": 111.0,
        },
    }

    refs = safe_stop_references(state)

    assert refs["version"] == SAFE_STOPS_VERSION
    assert refs["informational_only"] is True
    # The downside cluster starts at recent low 93 and includes demand 92 / London 91.5.
    # EVE clears the deepest nearby anchor, then adds a 0.22 ATR breathing buffer.
    assert refs["buy"]["anchor"] == 89.0
    assert refs["buy"]["level"] == 86.8
    # The upside cluster starts at recent high 107 and includes 108 / 108.5 / 111.
    assert refs["sell"]["anchor"] == 111.0
    assert refs["sell"]["level"] == 113.2
    assert refs["buy"]["fallback"] is False
    assert refs["sell"]["fallback"] is False


def test_safe_stop_references_fall_back_to_atr_when_no_structure_exists() -> None:
    refs = safe_stop_references(
        {
            "price": 200.0,
            "market": {"atr": 4.0},
            "zones": {"demand": [], "supply": []},
            "liquidity": {},
        }
    )

    assert refs["buy"]["level"] == 194.0
    assert refs["sell"]["level"] == 206.0
    assert refs["buy"]["fallback"] is True
    assert refs["sell"]["fallback"] is True


def test_safe_stop_references_are_unavailable_without_price() -> None:
    refs = safe_stop_references({"price": None, "market": {"atr": 5.0}})

    assert refs["available"] is False
    assert refs["buy"]["level"] is None
    assert refs["sell"]["level"] is None
