-- Historical production migration restored to source control during the v73 audit.
-- This is the surviving schema from the original 2026-08-26 13:02 migration.

create table if not exists public.live_trader_specialisations (
    strategy_key text primary key,
    symbol text not null default 'XAU/USD',
    name text not null,
    active boolean not null default true,
    mode text not null default 'learning',
    core_rules jsonb not null,
    objective text not null,
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now()
);

insert into public.live_trader_specialisations (
    strategy_key, symbol, name, active, mode, core_rules, objective
)
values (
    'zone_retrace_v1',
    'XAU/USD',
    'Zone Retracement Specialist',
    true,
    'learning',
    jsonb_build_object(
        'bias_required', true,
        'zone_required', true,
        'bearish_sequence', jsonb_build_array('bearish_bias','retrace_up','supply_zone','bearish_confirmation','sell'),
        'bullish_sequence', jsonb_build_array('bullish_bias','retrace_down','demand_zone','bullish_confirmation','buy'),
        'chasing_forbidden', true,
        'learnable_dimensions', jsonb_build_array(
            'zone_quality','fresh_vs_retested','retrace_depth','confirmation_type','session',
            'htf_alignment','intraday_alignment','momentum_relation','liquidity_event',
            'stop_distance','target_r','volatility'
        ),
        'one_trade_idea_at_a_time', true
    ),
    'Perfect a directional retracement-to-zone strategy using historical and forward evidence while preserving the existing live campaign lifecycle.'
)
on conflict (strategy_key) do update set
    symbol = excluded.symbol,
    name = excluded.name,
    active = excluded.active,
    mode = excluded.mode,
    core_rules = excluded.core_rules,
    objective = excluded.objective,
    updated_at = now();

create or replace view public.live_trader_zone_retrace_evidence as
with h as (
    select observed_at, learning_success, evidence_weight,
           market_state -> 'setup_family_descriptor' as d,
           market_state
    from public.live_trader_historical_learning
    where symbol = 'XAU/USD'
      and path_complete = true
      and market_state is not null
), eligible as (
    select * from h
    where coalesce(d ->> 'bias','') in ('bullish','bearish')
      and coalesce(d ->> 'execution_class','') = 'pullback'
      and coalesce(d ->> 'location_relation','') in ('preferred','at_zone')
)
select
    coalesce(d ->> 'bias','unknown') as bias,
    coalesce(d ->> 'session','unknown') as session,
    coalesce(d ->> 'zone_quality','unknown') as zone_quality,
    coalesce(d ->> 'htf_relation','unknown') as htf_relation,
    coalesce(d ->> 'intraday_relation','unknown') as intraday_relation,
    coalesce(d ->> 'momentum_relation','unknown') as momentum_relation,
    coalesce(d ->> 'market_event_class','none') as market_event_class,
    coalesce(d ->> 'market_event_relation','unknown') as market_event_relation,
    count(*) as samples,
    count(*) filter (where learning_success is not null) as scored,
    count(*) filter (where learning_success is true) as successes,
    count(*) filter (where learning_success is false) as failures,
    round(avg(case when learning_success is true then 1.0 when learning_success is false then 0.0 else null::numeric end),4) as success_rate,
    round(sum(coalesce(evidence_weight,0::double precision))::numeric,4) as evidence_weight
from eligible
group by
    coalesce(d ->> 'bias','unknown'),
    coalesce(d ->> 'session','unknown'),
    coalesce(d ->> 'zone_quality','unknown'),
    coalesce(d ->> 'htf_relation','unknown'),
    coalesce(d ->> 'intraday_relation','unknown'),
    coalesce(d ->> 'momentum_relation','unknown'),
    coalesce(d ->> 'market_event_class','none'),
    coalesce(d ->> 'market_event_relation','unknown');

create or replace view public.live_trader_zone_retrace_summary as
select
    count(*) as episodes,
    count(*) filter (where learning_success is not null) as scored,
    count(*) filter (where learning_success is true) as successes,
    count(*) filter (where learning_success is false) as failures,
    round(avg(case when learning_success is true then 1.0 when learning_success is false then 0.0 else null::numeric end),4) as success_rate,
    count(distinct observed_at::date) as independent_days
from public.live_trader_historical_learning
where symbol = 'XAU/USD'
  and path_complete = true
  and coalesce((market_state -> 'setup_family_descriptor') ->> 'bias','') in ('bullish','bearish')
  and coalesce((market_state -> 'setup_family_descriptor') ->> 'execution_class','') = 'pullback'
  and coalesce((market_state -> 'setup_family_descriptor') ->> 'location_relation','') in ('preferred','at_zone');
