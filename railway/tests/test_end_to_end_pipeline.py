from datetime import datetime, timedelta, timezone
import random

from app.services.backtest import evaluate_strategy, compare_child_to_parent
from app.services.composer import mutation_batch
from app.services.mt5_generator import package_payload


def rows():
    out=[]
    for year in range(2020,2026):
        start=datetime(year,1,6,13,0,tzinfo=timezone.utc)
        for i in range(160):
            t=start+timedelta(minutes=15*i)
            out.append({
                'candle_time':t.isoformat(),'weekday':t.isoweekday(),'month':t.month,'hour_utc':t.hour,
                'session':'new_york','regime':'trend_up','direction':1,'trend_12_atr':.4,'trend_48_atr':.25,
                'compression_ratio':1.0,'alignment_score':4,'return_1_pct':.03,'return_3_pct':.1,
                'close_location':.8,'upper_wick':.1,'lower_wick':.05,'body_price':.3,'atr_14':2,'close':2000,
                'outcomes':{'15':{'max_up_atr':2.0,'max_down_atr':.1,'close_return_pct':.15}},
            })
    return out


def seed():
    rules={
        'family':'alignment_continuation',
        'schedule':{'weekdays':[1,2,3,4,5,6,7],'months':list(range(1,13)),'sessions':[],'hours_utc':list(range(24)),'everyday_target':True},
        'environment':{'regimes':[],'trend_12':'any','trend_48':'any','compression':'any','min_alignment_abs':2,'alignment_sign':'any','streak':'any'},
        'entry':{'direction_rule':'alignment_direction'},
        'risk':{'stop_atr':.75,'target_atr':1.5,'horizon_minutes':15,'max_hold_minutes':15,'cooldown_minutes':15,'cost_r':.04,'risk_percent':.25,'max_daily_loss_percent':1,'max_spread_points':100},
    }
    return {'id':'11111111-1111-1111-1111-111111111111','candidate_key':'candidate-test','name':'Everyday Alignment','family':'alignment_continuation','rules':rules}


def test_compose_evaluate_mutate_freeze_generate():
    parent=seed()
    result=evaluate_strategy(parent,rows(),min_validation_trades=40,min_locked_trades=40)
    assert result['result_status']=='elite'
    lineage={'id':'22222222-2222-2222-2222-222222222222','family':parent['family'],'name':parent['name'],'generation':0,'champion_rules':parent['rules'],'champion_metrics':result['metrics'],'champion_fitness':result['fitness_score']}
    child=mutation_batch(lineage,1,1,seed=88,memory=[])[0]
    child['id']='33333333-3333-3333-3333-333333333333'
    child_result=evaluate_strategy(child,rows(),min_validation_trades=40,min_locked_trades=40)
    selection=compare_child_to_parent(child_result,result['metrics'],result['fitness_score'])
    frozen={
        'name':parent['name'],'strategy_code':'EVE-DISC-END2END001','family':parent['family'],
        'rule_hash':'b'*64,'rules':parent['rules'],'metrics':result['metrics'],'walk_forward':result['walk_forward'],
        'robustness':result['robustness'],'evidence':result['evidence'],'stability_score':result['stability_score'],
    }
    package=package_payload(frozen)
    assert package['status']=='ready'
    assert package['file_name'].endswith('.zip')
    assert 'OnTick' in package['mq5_source']
    assert isinstance(selection['promoted'],bool)
