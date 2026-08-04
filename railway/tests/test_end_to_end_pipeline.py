from datetime import datetime, timedelta, timezone

from app.services.backtest import evaluate_strategy, compare_child_to_parent
from app.services.composer import mutation_batch
from app.services.mt5_generator import package_payload
from app.services.passport import build_trading_passport


def rows():
    out=[]
    for year in range(2020,2026):
        start=datetime(year,1,6,13,0,tzinfo=timezone.utc)
        for i in range(160):
            t=start+timedelta(minutes=15*i)
            out.append({
                'symbol':'XAU/USD','snapshot_interval':'15min','source_interval':'5min','feature_version':'test-v1','outcome_complete':True,
                'candle_time':t.isoformat(),'weekday':t.isoweekday(),'month':t.month,'hour_utc':t.hour,
                'session':'new_york','regime':'trend_up','direction':1,'trend_12_atr':.4,'trend_48_atr':.25,
                'compression_ratio':1.0,'alignment_score':4,'return_1_pct':.03,'return_3_pct':.1,
                'close_location':.8,'upper_wick':.1,'lower_wick':.05,'body_price':.3,'atr_14':2,'close':2000,
                'outcomes':{'15':{'max_up_atr':2.0,'max_down_atr':.1,'close_return_pct':.15}},
            })
    return out


def seed():
    rules={
        'family':'alignment_continuation','market':{'symbol':'XAU/USD','timeframe':'M5','snapshot_interval':'15min','source_interval':'5min'},
        'schedule':{'weekdays':[1,2,3,4,5,6,7],'months':list(range(1,13)),'sessions':[],'hours_utc':list(range(24)),'everyday_target':True},
        'environment':{'regimes':[],'trend_12':'any','trend_48':'any','compression':'any','min_alignment_abs':2,'alignment_sign':'any','streak':'any'},
        'entry':{'direction_rule':'alignment_direction'},
        'risk':{'stop_atr':.75,'target_atr':1.5,'horizon_minutes':15,'max_hold_minutes':15,'cooldown_minutes':15,'cost_r':.04,'risk_percent':.25,'max_daily_loss_percent':1,'max_spread_points':100},
    }
    return {'id':'11111111-1111-1111-1111-111111111111','candidate_key':'candidate-test','name':'Everyday Alignment','family':'alignment_continuation','symbol':'XAU/USD','timeframe':'M5','rules':rules}


def test_select_mutate_finalise_and_generate_documented_package():
    parent=seed()
    selection_result=evaluate_strategy(parent,rows(),min_validation_trades=40,min_locked_trades=40,stage='selection')
    assert selection_result['result_status']=='promising'
    lineage={'id':'22222222-2222-2222-2222-222222222222','family':parent['family'],'name':parent['name'],'generation':0,'champion_rules':parent['rules'],'champion_metrics':selection_result['metrics'],'champion_fitness':selection_result['fitness_score']}
    child=mutation_batch(lineage,1,1,seed=88,memory=[])[0]
    child['id']='33333333-3333-3333-3333-333333333333'
    child_result=evaluate_strategy(child,rows(),min_validation_trades=40,min_locked_trades=40,stage='selection')
    comparison=compare_child_to_parent(child_result,selection_result['metrics'],selection_result['fitness_score'])
    final_result=evaluate_strategy(parent,rows(),min_validation_trades=40,min_locked_trades=40,stage='final')
    frozen={
        **parent,'strategy_code':'EVE-DISC-END2END001','rule_hash':'b'*64,'metrics':final_result['metrics'],
        'walk_forward':final_result['walk_forward'],'robustness':final_result['robustness'],'monte_carlo':final_result['monte_carlo'],
        'execution_costs':final_result['execution_costs'],'evidence':final_result['evidence'],'stability_score':final_result['stability_score'],
        'dataset_version':final_result['dataset_version'],'research_integrity_version':final_result['research_integrity_version'],
        'm1_replay':{'status':'passed','passed':True},
    }
    frozen['trading_passport']=build_trading_passport(frozen)
    package=package_payload(frozen)
    assert package['status']=='ready'
    assert package['file_name'].endswith('.zip')
    assert package['manifest']['compile_status']=='required'
    assert 'OnTick' in package['mq5_source']
    assert isinstance(comparison['promoted'],bool)
