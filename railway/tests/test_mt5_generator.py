import io
import zipfile

from app.services.mt5_generator import package_payload, generate_mq5_source, static_validate, decode_package


def frozen():
    rules={
        "family":"alignment_continuation",
        "schedule":{"weekdays":[1,2,3,4,5],"months":list(range(1,13)),"sessions":["new_york"],"hours_utc":[],"everyday_target":True},
        "environment":{"regimes":[],"trend_12":"directional","trend_48":"any","compression":"any","min_alignment_abs":2,"alignment_sign":"any"},
        "entry":{"direction_rule":"alignment_direction"},
        "risk":{"stop_atr":1.0,"target_atr":2.0,"horizon_minutes":60,"max_hold_minutes":60,"cooldown_minutes":30,"risk_percent":.25,"max_daily_loss_percent":1,"max_spread_points":100},
    }
    return {
        "name":"Everyday Alignment","strategy_code":"EVE-DISC-ABC123456789","family":"alignment_continuation",
        "rule_hash":"a"*64,"rules":rules,"metrics":{"locked":{"profit_factor":1.4,"expectancy_r":.1,"trades":120},"recent":{"profit_factor":1.2}},
        "walk_forward":{"stability":.8},"robustness":{"pass_rate":1},"evidence":{},"stability_score":80,
    }


def test_generated_mq5_contains_real_trade_engine():
    name,source=generate_mq5_source(frozen())
    assert name.endswith('.mq5')
    assert static_validate(source,'a'*64) == []
    assert 'trade.Buy' in source and 'trade.Sell' in source
    assert 'InpEnableTrading              = false' in source
    assert 'MathAbs(f.alignment_score) >= 2' in source
    assert 'f.session == "new_york"' in source


def test_package_is_downloadable_zip():
    payload=package_payload(frozen())
    data=decode_package(payload)
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        names=set(archive.namelist())
    assert 'FROZEN_RULES.json' in names
    assert 'VALIDATION_REPORT.json' in names
    assert 'README.txt' in names
    assert any(name.endswith('.mq5') for name in names)
    assert len(payload['sha256']) == 64
