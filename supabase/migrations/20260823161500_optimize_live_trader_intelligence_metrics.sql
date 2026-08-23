-- Reduce Live Trader intelligence aggregation cost without changing metric semantics.
-- The original function materialized SELECT * from ~six years of historical episodes,
-- including large JSON payloads that were irrelevant to the aggregates. Under dashboard
-- polling this could spill to temporary disk and exceed Supabase statement_timeout.
-- Keep only the narrow columns required for each calculation and scan challenger JSON
-- separately so the hot CTE remains compact.

create or replace function public.get_live_trader_intelligence_metrics(p_symbol text default 'XAU/USD')
returns jsonb
language sql
stable
security definer
set search_path = public
as $$
with forward_rows as materialized (
  select
    setup_family,
    observed_at,
    status,
    learning_success,
    market_state
  from public.live_trader_opinions
  where symbol = p_symbol
    and learning_version = 'eve-live-learning-family-v1'
    and independent_sample = true
),
forward_families as (
  select
    setup_family,
    count(*) as independent_rows,
    count(*) filter (where status = 'resolved' and learning_success is not null) as scored,
    count(distinct observed_at::date) as days
  from forward_rows
  group by setup_family
),
historical_core as materialized (
  select
    setup_family,
    observed_at,
    learning_success,
    path_complete,
    best_challenger
  from public.live_trader_historical_learning
  where symbol = p_symbol
),
historical_families as (
  select
    setup_family,
    count(*) as episodes,
    count(*) filter (where learning_success is not null) as scored,
    count(*) filter (where path_complete = true) as complete,
    count(distinct observed_at::date) as days
  from historical_core
  group by setup_family
),
best_counts as (
  select setup_family, best_challenger, count(*) as n
  from historical_core
  where path_complete = true
    and best_challenger is not null
    and best_challenger <> ''
  group by setup_family, best_challenger
),
best_totals as (
  select setup_family, sum(n) as total, max(n) as top_count
  from best_counts
  group by setup_family
),
challenger_count as (
  select count(*)::bigint as n
  from public.live_trader_historical_learning h
  cross join lateral jsonb_object_keys(coalesce(h.challenger_results, '{}'::jsonb)) k
  where h.symbol = p_symbol
),
combined_family_count as (
  select count(*)::bigint as n
  from (
    select setup_family from forward_families
    union
    select setup_family from historical_families
  ) x
)
select jsonb_build_object(
  'forward_independent', (select count(*) from forward_rows),
  'forward_scored', (select count(*) from forward_rows where status = 'resolved' and learning_success is not null),
  'forward_days', (select count(distinct observed_at::date) from forward_rows),
  'forward_families', (select count(*) from forward_families),
  'mature_forward_families', (select count(*) from forward_families where independent_rows >= 12 and days >= 3),
  'governor_veto_observations', (
    select count(*) from forward_rows
    where coalesce(market_state->'learning_governor'->>'decision', '') = 'veto'
  ),
  'historical_episodes', (select count(*) from historical_core),
  'historical_scored', (select count(*) from historical_core where learning_success is not null),
  'historical_complete', (select count(*) from historical_core where path_complete = true),
  'historical_days', (select count(distinct observed_at::date) from historical_core),
  'historical_families', (select count(*) from historical_families),
  'historically_deep_families', (select count(*) from historical_families where scored >= 8),
  'historical_seed_families', (select count(*) from historical_families where scored >= 24 and days >= 12),
  'execution_discoveries', (
    select count(*) from best_totals
    where total >= 12 and (top_count::numeric / nullif(total, 0)) >= 0.60
  ),
  'challenger_runs', (select n from challenger_count),
  'combined_families', (select n from combined_family_count)
);
$$;

revoke all on function public.get_live_trader_intelligence_metrics(text) from public, anon, authenticated;
grant execute on function public.get_live_trader_intelligence_metrics(text) to service_role;
