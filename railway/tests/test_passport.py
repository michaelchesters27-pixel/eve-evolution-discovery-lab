from app.services.passport import (
    PROFILE_VERSION,
    build_trading_passport,
    passport_completeness,
    passport_is_complete,
    passport_text,
)


def complete_frozen():
    return {
        'name':'Session Bot','strategy_code':'EVE-1','family':'volatility_breakout','symbol':'XAU/USD','timeframe':'M5','rule_hash':'a'*64,
        'rules':{
            'family':'volatility_breakout',
            'market':{'symbol':'XAU/USD','timeframe':'M5','snapshot_interval':'15min','source_interval':'5min'},
            'schedule':{'sessions':['new_york'],'weekdays':[1,2,3,4,5],'months':list(range(1,13))},
            'environment':{'compression':'compressed'},
            'risk':{'stop_atr':1.0,'target_atr':2.0,'max_hold_minutes':60,'max_spread_points':80},
        },
        'metrics':{
            'validation':{'profit_factor':1.2,'trades':100,'trades_per_day':2},
            'confirmation':{'profit_factor':1.3,'trades':100,'session_expectancy':{'new_york':.1},'session_trades':{'new_york':100}},
            'holdout':{
                'profit_factor':1.15,'expectancy_r':.04,'trades':80,
                'session_expectancy':{'new_york':.1,'asia':-.02},'session_trades':{'new_york':60,'asia':20},
                'regime_expectancy':{'compression':.08,'range':-.02},'regime_trades':{'compression':55,'range':25},
                'weekday_expectancy':{'2':.07,'5':-.01},'weekday_trades':{'2':45,'5':35},
                'hour_expectancy':{'13':.09,'22':-.03},'hour_trades':{'13':50,'22':30},
            },
        },
        'robustness':{'pass_rate':.75},'stability_score':80,'dataset_version':'dataset-x',
        'm1_replay':{'status':'passed','passed':True},
    }


def test_passport_specifies_market_timeframe_and_when_to_use_bot():
    passport=build_trading_passport(complete_frozen())
    assert passport['market']=='XAU/USD'
    assert passport['primary_timeframe']=='M5'
    assert passport['attach_to_chart']=='XAU/USD M5'
    assert passport['research_source_interval']=='5min'
    assert 'new york' in passport['operating_window'].lower()
    assert passport['best_session']=='New York'
    assert passport['best_regime']=='Compression'
    assert passport['best_weekday']=='Tuesday'
    assert passport['best_hour_utc']=='13:00–14:00 UTC'
    assert passport['profile_version']==PROFILE_VERSION
    assert passport_is_complete(passport)
    assert passport['use_when'] and passport['avoid_when']
    text=passport_text(passport)
    assert 'Primary timeframe: M5' in text
    assert 'USE WHEN' in text and 'AVOID WHEN' in text
    assert 'Complete: YES' in text


def test_legacy_empty_passport_is_not_download_complete():
    legacy={}
    report=passport_completeness(legacy)
    assert report['complete'] is False
    assert 'market' in report['missing_fields']
    assert passport_is_complete(legacy) is False
