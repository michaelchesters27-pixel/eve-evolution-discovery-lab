from datetime import datetime, timedelta, timezone

from app.services.m1_replay import Intent, build_intents, replay_sequence


def rules():
    return {
        "family": "momentum_continuation",
        "market": {"symbol": "XAU/USD", "timeframe": "M5", "source_interval": "5min", "snapshot_interval": "15min"},
        "schedule": {"weekdays": list(range(1, 8)), "months": list(range(1, 13)), "sessions": [], "hours_utc": list(range(24))},
        "environment": {"regimes": [], "trend_12": "any", "trend_48": "any", "compression": "any", "min_alignment_abs": 0, "alignment_sign": "any", "streak": "any"},
        "entry": {"direction_rule": "current_direction"},
        "risk": {"stop_atr": 1.0, "target_atr": 1.0, "max_hold_minutes": 60, "cooldown_minutes": 15},
    }


def row(time):
    return {
        "symbol": "XAU/USD", "source_interval": "5min", "snapshot_interval": "15min",
        "candle_time": time.isoformat(), "weekday": time.isoweekday(), "month": time.month,
        "hour_utc": time.hour, "session": "london", "regime": "trend_up", "direction": 1,
        "trend_12_atr": .4, "trend_48_atr": .3, "compression_ratio": 1.0,
        "alignment_score": 3, "return_3_pct": .1, "atr_14": 1.0,
    }


def candles(start, minutes=40):
    result=[]
    for i in range(minutes):
        t=start+timedelta(minutes=i)
        # Every entry reaches its 1 ATR target inside the first M1 bar.
        result.append({"candle_time": t.isoformat(), "open": 100.0, "high": 101.2, "low": 99.9, "close": 101.0})
    return result


def test_build_intents_keeps_all_signals_for_actual_exit_resolution():
    start=datetime(2025,1,6,8,0,tzinfo=timezone.utc)
    intents=build_intents([row(start),row(start+timedelta(minutes=15))],rules(),"holdout")
    assert len(intents)==2
    assert intents[0].entry_time==start+timedelta(minutes=5)


def test_sequential_replay_allows_new_trade_after_early_exit_and_cooldown():
    start=datetime(2025,1,6,8,5,tzinfo=timezone.utc)
    items=[
        Intent(start-timedelta(minutes=5),start,1,1.0,"holdout","london","trend_up"),
        Intent(start+timedelta(minutes=10),start+timedelta(minutes=15),1,1.0,"holdout","london","trend_up"),
    ]
    data={start.date().isoformat():candles(start)}
    result=replay_sequence(items,data,stop_atr=1.0,target_atr=1.0,hold_minutes=60,cooldown_minutes=15,cost_r=.04)
    assert result["trades"]==2
    assert result["skipped_while_position_or_cooldown"]==0
    assert result["profit_factor"]>1


def test_sequential_replay_skips_signal_inside_cooldown():
    start=datetime(2025,1,6,8,5,tzinfo=timezone.utc)
    items=[
        Intent(start-timedelta(minutes=5),start,1,1.0,"holdout","london","trend_up"),
        Intent(start,start+timedelta(minutes=5),1,1.0,"holdout","london","trend_up"),
    ]
    data={start.date().isoformat():candles(start)}
    result=replay_sequence(items,data,stop_atr=1.0,target_atr=1.0,hold_minutes=60,cooldown_minutes=15,cost_r=.04)
    assert result["trades"]==1
    assert result["skipped_while_position_or_cooldown"]==1
