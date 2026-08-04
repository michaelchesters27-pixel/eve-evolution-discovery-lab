from app.services.passport import build_trading_passport, passport_text


def test_passport_specifies_market_timeframe_and_when_to_use_bot():
    frozen={
        'name':'Session Bot','strategy_code':'EVE-1','family':'volatility_breakout','symbol':'XAU/USD','timeframe':'M5','rule_hash':'a'*64,
        'rules':{'family':'volatility_breakout','market':{'symbol':'XAU/USD','timeframe':'M5','snapshot_interval':'15min','source_interval':'5min'},'schedule':{'sessions':['new_york'],'weekdays':[1,2,3,4,5],'months':list(range(1,13))},'environment':{'compression':'compressed'},'risk':{'max_spread_points':80}},
        'metrics':{'validation':{'profit_factor':1.2,'trades_per_day':2},'confirmation':{'profit_factor':1.3,'session_expectancy':{'new_york':.1}},'holdout':{'profit_factor':1.15,'expectancy_r':.04,'regime_expectancy':{'compression':.08,'range':-.02}}},
        'robustness':{'pass_rate':.75},'stability_score':80,'dataset_version':'dataset-x',
    }
    passport=build_trading_passport(frozen)
    assert passport['market']=='XAU/USD'
    assert passport['primary_timeframe']=='M5'
    assert passport['attach_to_chart']=='XAU/USD M5'
    assert passport['research_source_interval']=='5min'
    assert 'new york' in passport['operating_window']
    assert passport['use_when'] and passport['avoid_when']
    text=passport_text(passport)
    assert 'Primary timeframe: M5' in text
    assert 'USE WHEN' in text and 'AVOID WHEN' in text
