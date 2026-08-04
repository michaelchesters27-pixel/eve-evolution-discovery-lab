import io
import json
import zipfile

from app.services.mt5_generator import package_payload, generate_mq5_source, static_validate, decode_package
from app.services.passport import build_trading_passport


def frozen():
    rules={
        "family":"alignment_continuation",
        "market":{"symbol":"XAU/USD","timeframe":"M5","snapshot_interval":"15min"},
        "schedule":{"weekdays":[1,2,3,4,5],"months":list(range(1,13)),"sessions":["new_york"],"hours_utc":[],"everyday_target":True},
        "environment":{"regimes":[],"trend_12":"directional","trend_48":"any","compression":"any","min_alignment_abs":2,"alignment_sign":"any"},
        "entry":{"direction_rule":"alignment_direction"},
        "risk":{"stop_atr":1.0,"target_atr":2.0,"horizon_minutes":60,"max_hold_minutes":60,"cooldown_minutes":30,"risk_percent":.25,"max_daily_loss_percent":1,"max_spread_points":100},
    }
    row={
        "name":"Everyday Alignment","strategy_code":"EVE-DISC-ABC123456789","family":"alignment_continuation",
        "symbol":"XAU/USD","timeframe":"M5","rule_hash":"a"*64,"rules":rules,
        "metrics":{"validation":{"profit_factor":1.3,"expectancy_r":.08,"trades":100,"trades_per_day":2},"confirmation":{"profit_factor":1.4,"expectancy_r":.1,"trades":120,"trades_per_day":2.2,"session_expectancy":{"new_york":.1}},"holdout":{"profit_factor":1.2,"expectancy_r":.05,"trades":50,"trades_per_day":1.8}},
        "walk_forward":{"stability":.8},"robustness":{"pass_rate":1},"monte_carlo":{"pass_rate":.9},
        "execution_costs":{"elevated":{"profit_factor":1.1}},"m1_replay":{"status":"passed","passed":True},
        "evidence":{},"stability_score":80,"dataset_version":"dataset-test","research_integrity_version":"eve-research-integrity-v2.0",
    }
    row["trading_passport"]=build_trading_passport(row)
    return row


def test_generated_mq5_contains_dynamic_timeframe_and_telemetry_wrapper():
    name,source=generate_mq5_source(frozen())
    assert name.endswith('.mq5')
    assert static_validate(source,'a'*64) == []
    assert 'trade.Buy' in source and 'trade.Sell' in source
    assert 'InpEnableTrading              = false' in source
    assert 'const ENUM_TIMEFRAMES EVE_TIMEFRAME = PERIOD_M5' in source
    assert 'MathAbs(bars[0].close-bars[0].open)' in source
    assert 'InpFleetPackageId' in source and 'InpFleetToken' in source
    assert 'f.session == "new_york"' in source


def test_package_contains_passport_and_honest_compile_status():
    payload=package_payload(frozen())
    data=decode_package(payload)
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        names=set(archive.namelist())
        manifest=json.loads(archive.read('MANIFEST.json'))
        passport=json.loads(archive.read('TRADING_PASSPORT.json'))
    assert {'FROZEN_RULES.json','VALIDATION_REPORT.json','README.txt','TRADING_PASSPORT.json','TRADING_PASSPORT.txt'} <= names
    assert any(name.endswith('.mq5') for name in names)
    assert manifest['compile_status'] == 'required'
    assert manifest['timeframe'] == 'M5'
    assert passport['market'] == 'XAU/USD'
    assert passport['primary_timeframe'] == 'M5'
    assert len(payload['sha256']) == 64
