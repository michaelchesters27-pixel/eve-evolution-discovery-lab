create table if not exists public.live_trader_intelligence_snapshots (
  snapshot_key text primary key,
  symbol text not null,
  captured_at timestamptz not null default now(),
  overall_score numeric(4,2) not null,
  brain_score numeric(4,2) not null,
  experience_score numeric(4,2) not null,
  applied_score numeric(4,2) not null,
  level text not null,
  score_version text not null,
  metrics jsonb not null default '{}'::jsonb
);

create index if not exists idx_live_trader_intelligence_snapshots_symbol_time
  on public.live_trader_intelligence_snapshots(symbol, captured_at desc);

alter table public.live_trader_intelligence_snapshots enable row level security;
revoke all on public.live_trader_intelligence_snapshots from anon, authenticated;
grant all on public.live_trader_intelligence_snapshots to service_role;

create or replace function public.get_live_trader_intelligence_metrics(p_symbol text default 'XAU/USD')
returns jsonb
language sql
stable
security definer
set search_path = public
as $$
with forward_rows as (
  select *
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
historical_rows as (
  select *
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
  from historical_rows
  group by setup_family
),
best_counts as (
  select setup_family, best_challenger, count(*) as n
  from historical_rows
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
  from historical_rows h
  cross join lateral jsonb_object_keys(coalesce(h.challenger_results, '{}'::jsonb)) k
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
  'historical_episodes', (select count(*) from historical_rows),
  'historical_scored', (select count(*) from historical_rows where learning_success is not null),
  'historical_complete', (select count(*) from historical_rows where path_complete = true),
  'historical_days', (select count(distinct observed_at::date) from historical_rows),
  'historical_families', (select count(*) from historical_families),
  'historically_deep_families', (select count(*) from historical_families where scored >= 8),
  'historical_seed_families', (select count(*) from historical_families where scored >= 24 and days >= 12),
  'execution_discoveries', (
    select count(*) from best_totals
    where total >= 12 and (top_count::numeric / nullif(total,0)) >= 0.60
  ),
  'challenger_runs', (select n from challenger_count),
  'combined_families', (select n from combined_family_count)
);
$$;

revoke all on function public.get_live_trader_intelligence_metrics(text) from public, anon, authenticated;
grant execute on function public.get_live_trader_intelligence_metrics(text) to service_role;
