-- Audit remediation Fix 10: durable cadence/restart metadata and bounded
-- server-side replay work discovery. Existing evidence is preserved.

alter table public.bounded_research_cycles
  add column if not exists resume_count integer not null default 0,
  add column if not exists last_resumed_at timestamptz,
  add column if not exists supervisor_owner text,
  add column if not exists active_compute_ms double precision,
  add column if not exists max_stage_rss_mb double precision,
  add column if not exists total_stage_cpu_ms double precision,
  add column if not exists resource_budget_status text,
  add column if not exists next_due_at timestamptz;

create index if not exists bounded_research_cycles_outcome_started_idx
  on public.bounded_research_cycles(outcome, started_at desc);

create index if not exists bounded_research_cycles_finished_idx
  on public.bounded_research_cycles(finished_at desc)
  where finished_at is not null;

create index if not exists live_trader_zone_retrace_replay_identity_idx
  on public.live_trader_zone_retrace_live_policy_replays(symbol, replay_version, independence_key);

create or replace function public.get_live_trader_zone_replay_work_v97(
  p_symbol text,
  p_replay_version text,
  p_limit integer default 4
)
returns jsonb
language sql
stable
security invoker
set search_path = public
as $$
with source_window as (
  -- Preserve the exact v68 effective universe: the legacy worker examined the
  -- newest HISTORICAL_PAGES(5) * HISTORICAL_PAGE_SIZE(1000) complete rows first,
  -- then applied eligibility and newest-per-independence-key deduplication.
  select
    h.historical_episode_key,
    h.observed_at,
    h.independence_key,
    h.market_state,
    h.path_complete
  from public.live_trader_historical_learning h
  where h.symbol = p_symbol
    and h.path_complete is true
  order by h.observed_at desc
  limit 5000
),
ranked as (
  select
    h.historical_episode_key,
    h.observed_at,
    h.independence_key,
    h.market_state,
    h.path_complete,
    row_number() over (
      partition by h.independence_key
      order by h.observed_at desc, h.historical_episode_key desc
    ) as rn
  from source_window h
  where lower(coalesce(h.market_state #>> '{setup_family_descriptor,bias}', '')) in ('bullish','bearish')
    and lower(coalesce(h.market_state #>> '{setup_family_descriptor,location_relation}', '')) in ('preferred','at_zone')
    and lower(coalesce(h.market_state #>> '{setup_family_descriptor,zone_quality}', '')) in ('good','high')
    and lower(coalesce(h.market_state #>> '{setup_family_descriptor,execution_class}', '')) = 'pullback'
    and length(btrim(coalesce(h.historical_episode_key, ''))) > 0
    and length(btrim(coalesce(h.independence_key, ''))) > 0
),
eligible as (
  select historical_episode_key, observed_at, independence_key, market_state, path_complete
  from ranked
  where rn = 1
),
pending_rows as (
  select e.historical_episode_key, e.observed_at, e.independence_key, e.market_state, e.path_complete
  from eligible e
  where not exists (
    select 1
    from public.live_trader_zone_retrace_live_policy_replays r
    where r.symbol = p_symbol
      and r.replay_version = p_replay_version
      and r.independence_key = e.independence_key
  )
  order by e.observed_at desc, e.independence_key
  limit greatest(1, least(coalesce(p_limit, 4), 100))
),
stats as (
  select
    count(*)::integer as eligible_episodes,
    count(r.replay_key)::integer as processed_episodes,
    count(r.replay_key) filter (
      where r.path_complete is true and r.status in ('scored','no_entry')
    )::integer as scorable_episodes,
    count(r.replay_key) filter (
      where r.path_complete is true
        and r.status in ('scored','no_entry')
        and r.entry_at is not null
    )::integer as triggered,
    count(r.replay_key) filter (
      where r.path_complete is true
        and r.status in ('scored','no_entry')
        and r.entry_at is not null
        and r.realised_r > 0
    )::integer as wins,
    count(r.replay_key) filter (
      where r.path_complete is true
        and r.status in ('scored','no_entry')
        and r.entry_at is not null
        and r.realised_r < 0
    )::integer as losses,
    count(r.replay_key) filter (
      where r.path_complete is true
        and r.status in ('scored','no_entry')
        and r.entry_at is not null
        and r.realised_r = 0
    )::integer as breakeven,
    coalesce(sum(
      case
        when r.path_complete is true
          and r.status in ('scored','no_entry')
          and r.realised_r is not null
        then r.realised_r
        else 0
      end
    ), 0.0)::double precision as total_r
  from eligible e
  left join public.live_trader_zone_retrace_live_policy_replays r
    on r.symbol = p_symbol
   and r.replay_version = p_replay_version
   and r.independence_key = e.independence_key
)
select jsonb_build_object(
  'version', 'eve-resource-bounded-zone-replay-v97',
  'complete_server_side_scan', true,
  'eligible_episodes', s.eligible_episodes,
  'processed_episodes', s.processed_episodes,
  'scorable_episodes', s.scorable_episodes,
  'unscorable_episodes', greatest(0, s.processed_episodes - s.scorable_episodes),
  'triggered', s.triggered,
  'wins', s.wins,
  'losses', s.losses,
  'breakeven', s.breakeven,
  'total_r', s.total_r,
  'pending', coalesce((
    select jsonb_agg(
      jsonb_build_object(
        'historical_episode_key', p.historical_episode_key,
        'observed_at', p.observed_at,
        'independence_key', p.independence_key,
        'market_state', p.market_state,
        'path_complete', p.path_complete
      )
      order by p.observed_at desc, p.independence_key
    )
    from pending_rows p
  ), '[]'::jsonb)
)
from stats s;
$$;

revoke all on function public.get_live_trader_zone_replay_work_v97(text,text,integer)
  from public, anon, authenticated;
grant execute on function public.get_live_trader_zone_replay_work_v97(text,text,integer)
  to service_role;

comment on function public.get_live_trader_zone_replay_work_v97(text,text,integer) is
'Fix 10 complete server-side eligible replay scan/aggregation. Returns only a bounded pending batch while preserving v68 replay semantics.';
