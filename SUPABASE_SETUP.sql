-- EVE Evolution Discovery Lab v1.0
-- Run once in the NEW, separate Discovery Lab Supabase project.
-- Do not run this in the existing EVE Algo Lab project.

create extension if not exists pgcrypto;

create or replace function public.set_updated_at()
returns trigger language plpgsql as $$
begin new.updated_at = now(); return new; end;
$$;

create table if not exists public.source_snapshots (
  symbol text not null,
  snapshot_interval text not null default '15min',
  source_interval text not null default '5min',
  candle_time timestamptz not null,
  open double precision not null,
  high double precision not null,
  low double precision not null,
  close double precision not null,
  volume double precision,
  weekday smallint not null,
  month smallint not null,
  quarter smallint not null,
  hour_utc smallint not null,
  week_of_month smallint not null,
  session text not null,
  direction smallint not null,
  range_price double precision not null,
  body_price double precision not null,
  upper_wick double precision not null,
  lower_wick double precision not null,
  close_location double precision,
  atr_14 double precision,
  average_range_12 double precision,
  volatility_12 double precision,
  compression_ratio double precision,
  return_1_pct double precision,
  return_3_pct double precision,
  return_12_pct double precision,
  return_48_pct double precision,
  return_288_pct double precision,
  context_m15_return_pct double precision,
  context_h1_return_pct double precision,
  context_h4_return_pct double precision,
  context_d1_return_pct double precision,
  trend_12_atr double precision,
  trend_48_atr double precision,
  streak smallint not null default 0,
  regime text not null,
  alignment_score smallint not null default 0,
  outcomes jsonb not null default '{}'::jsonb,
  outcome_horizons smallint[] not null default '{}'::smallint[],
  outcome_complete boolean not null default false,
  feature_version text not null,
  imported_at timestamptz not null default now(),
  primary key (symbol, source_interval, snapshot_interval, candle_time)
);
create index if not exists source_snapshots_time_idx on public.source_snapshots(candle_time);
create index if not exists source_snapshots_context_idx on public.source_snapshots(weekday, month, hour_utc, session, regime);

create table if not exists public.strategy_candidates (
  id uuid primary key default gen_random_uuid(),
  candidate_key text not null unique,
  generation integer not null default 1,
  priority integer not null default 50,
  family text not null,
  name text not null,
  hypothesis text not null,
  rules jsonb not null,
  composer_version text,
  status text not null default 'queued' check (status in ('queued','running','complete','failed')),
  result_status text check (result_status is null or result_status in ('rejected','promising','validated','elite')),
  rows_scanned bigint not null default 0,
  trades_total integer not null default 0,
  profit_factor double precision,
  expectancy_r double precision,
  max_drawdown_r double precision,
  win_rate double precision,
  stability_score double precision,
  fitness_score double precision,
  metrics jsonb not null default '{}'::jsonb,
  walk_forward jsonb not null default '{}'::jsonb,
  robustness jsonb not null default '{}'::jsonb,
  evidence jsonb not null default '{}'::jsonb,
  worker_id text,
  requested_at timestamptz not null default now(),
  started_at timestamptz,
  heartbeat_at timestamptz,
  finished_at timestamptz,
  error text
);
create index if not exists strategy_candidates_queue_idx on public.strategy_candidates(status, priority desc, requested_at);
create index if not exists strategy_candidates_result_idx on public.strategy_candidates(result_status, fitness_score desc nulls last);

create table if not exists public.mutation_lineages (
  id uuid primary key default gen_random_uuid(),
  lineage_key text not null unique,
  family text not null,
  name text not null,
  status text not null default 'active' check (status in ('active','paused','retired')),
  generation integer not null default 0,
  root_candidate_id uuid references public.strategy_candidates(id) on delete set null,
  champion_kind text not null default 'seed',
  champion_id uuid,
  champion_rules jsonb not null,
  champion_metrics jsonb not null default '{}'::jsonb,
  champion_fitness double precision not null default 0,
  champion_result_status text,
  last_result text,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);
drop trigger if exists mutation_lineages_updated_at on public.mutation_lineages;
create trigger mutation_lineages_updated_at before update on public.mutation_lineages for each row execute function public.set_updated_at();

create table if not exists public.mutation_candidates (
  id uuid primary key default gen_random_uuid(),
  mutation_key text not null unique,
  lineage_id uuid not null references public.mutation_lineages(id) on delete cascade,
  generation integer not null,
  priority integer not null default 50,
  family text not null,
  name text not null,
  mutation_gene text not null,
  changes jsonb not null default '{}'::jsonb,
  parent_rules jsonb not null,
  parent_metrics jsonb not null default '{}'::jsonb,
  parent_fitness double precision not null default 0,
  rules jsonb not null,
  status text not null default 'queued' check (status in ('queued','running','complete','failed')),
  result_status text check (result_status is null or result_status in ('rejected','promising','validated','elite')),
  promoted boolean not null default false,
  selection_reason text,
  locked_veto boolean,
  fitness_delta double precision,
  validation_expectancy_delta double precision,
  validation_pf_delta double precision,
  rows_scanned bigint not null default 0,
  trades_total integer not null default 0,
  profit_factor double precision,
  expectancy_r double precision,
  max_drawdown_r double precision,
  win_rate double precision,
  stability_score double precision,
  fitness_score double precision,
  metrics jsonb not null default '{}'::jsonb,
  walk_forward jsonb not null default '{}'::jsonb,
  robustness jsonb not null default '{}'::jsonb,
  evidence jsonb not null default '{}'::jsonb,
  worker_id text,
  requested_at timestamptz not null default now(),
  started_at timestamptz,
  heartbeat_at timestamptz,
  finished_at timestamptz,
  error text
);
create index if not exists mutation_candidates_queue_idx on public.mutation_candidates(status, priority desc, requested_at);
create index if not exists mutation_candidates_lineage_idx on public.mutation_candidates(lineage_id, generation desc);

create table if not exists public.mutation_memory (
  family text not null,
  gene text not null,
  attempts bigint not null default 0,
  promotions bigint not null default 0,
  rejections bigint not null default 0,
  cumulative_fitness_delta double precision not null default 0,
  average_fitness_delta double precision not null default 0,
  promotion_rate double precision not null default 0,
  score double precision not null default 0,
  updated_at timestamptz not null default now(),
  primary key (family, gene)
);

create table if not exists public.frozen_strategies (
  id uuid primary key default gen_random_uuid(),
  frozen_key text not null unique,
  strategy_code text not null unique,
  name text not null,
  family text not null,
  source_kind text not null,
  source_id uuid,
  rule_hash text not null unique,
  rules jsonb not null,
  metrics jsonb not null,
  walk_forward jsonb not null,
  robustness jsonb not null,
  evidence jsonb not null,
  stability_score double precision,
  fitness_score double precision,
  status text not null default 'frozen',
  package_status text not null default 'pending' check (package_status in ('pending','ready','failed')),
  mt5_package_id uuid,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);
drop trigger if exists frozen_strategies_updated_at on public.frozen_strategies;
create trigger frozen_strategies_updated_at before update on public.frozen_strategies for each row execute function public.set_updated_at();

create table if not exists public.mt5_packages (
  id uuid primary key default gen_random_uuid(),
  package_key text not null unique,
  frozen_strategy_id uuid references public.frozen_strategies(id) on delete set null,
  strategy_name text not null,
  family text not null,
  version text not null default '1.0',
  file_name text not null,
  mq5_file_name text not null,
  mq5_source text not null,
  package_base64 text not null,
  sha256 text not null,
  manifest jsonb not null,
  size_bytes bigint not null,
  status text not null default 'ready',
  created_at timestamptz not null default now()
);

alter table public.frozen_strategies drop constraint if exists frozen_strategies_mt5_package_id_fkey;
alter table public.frozen_strategies add constraint frozen_strategies_mt5_package_id_fkey foreign key (mt5_package_id) references public.mt5_packages(id) on delete set null;

create table if not exists public.system_events (
  id bigint generated by default as identity primary key,
  level text not null default 'info' check (level in ('info','success','warning','error')),
  component text not null,
  message text not null,
  details jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default now()
);
create index if not exists system_events_recent_idx on public.system_events(created_at desc);

create or replace function public.claim_next_discovery_candidate(p_worker_id text)
returns setof public.strategy_candidates
language plpgsql security definer set search_path=public as $$
declare v_id uuid;
begin
  select id into v_id from public.strategy_candidates where status='queued'
  order by priority desc, requested_at asc for update skip locked limit 1;
  if v_id is null then return; end if;
  update public.strategy_candidates set status='running',worker_id=p_worker_id,started_at=coalesce(started_at,now()),heartbeat_at=now(),error=null where id=v_id;
  return query select * from public.strategy_candidates where id=v_id;
end; $$;

create or replace function public.claim_next_mutation_candidate(p_worker_id text)
returns setof public.mutation_candidates
language plpgsql security definer set search_path=public as $$
declare v_id uuid;
begin
  select id into v_id from public.mutation_candidates where status='queued'
  order by priority desc, requested_at asc for update skip locked limit 1;
  if v_id is null then return; end if;
  update public.mutation_candidates set status='running',worker_id=p_worker_id,started_at=coalesce(started_at,now()),heartbeat_at=now(),error=null where id=v_id;
  return query select * from public.mutation_candidates where id=v_id;
end; $$;

create or replace function public.record_mutation_memory(
  p_family text,p_gene text,p_promoted boolean,p_delta double precision
) returns void language plpgsql security definer set search_path=public as $$
begin
  insert into public.mutation_memory(family,gene,attempts,promotions,rejections,cumulative_fitness_delta,average_fitness_delta,promotion_rate,score,updated_at)
  values(p_family,p_gene,1,case when p_promoted then 1 else 0 end,case when p_promoted then 0 else 1 end,p_delta,p_delta,case when p_promoted then 1 else 0 end,(case when p_promoted then 1 else -0.25 end)+greatest(-2,least(2,p_delta/10.0)),now())
  on conflict(family,gene) do update set
    attempts=public.mutation_memory.attempts+1,
    promotions=public.mutation_memory.promotions+case when p_promoted then 1 else 0 end,
    rejections=public.mutation_memory.rejections+case when p_promoted then 0 else 1 end,
    cumulative_fitness_delta=public.mutation_memory.cumulative_fitness_delta+p_delta,
    average_fitness_delta=(public.mutation_memory.cumulative_fitness_delta+p_delta)/(public.mutation_memory.attempts+1),
    promotion_rate=(public.mutation_memory.promotions+case when p_promoted then 1 else 0 end)::double precision/(public.mutation_memory.attempts+1),
    score=((public.mutation_memory.promotions+case when p_promoted then 1 else 0 end)::double precision/(public.mutation_memory.attempts+1))*2.0 + greatest(-2,least(2,((public.mutation_memory.cumulative_fitness_delta+p_delta)/(public.mutation_memory.attempts+1))/10.0)),
    updated_at=now();
end; $$;

create or replace function public.get_discovery_dashboard()
returns jsonb language sql stable security definer set search_path=public as $$
select jsonb_build_object(
  'source_snapshots',(select count(*) from public.source_snapshots),
  'source_from',(select min(candle_time) from public.source_snapshots),
  'source_to',(select max(candle_time) from public.source_snapshots),
  'candidates_queued',(select count(*) from public.strategy_candidates where status='queued'),
  'candidates_running',(select count(*) from public.strategy_candidates where status='running'),
  'candidates_tested',(select count(*) from public.strategy_candidates where status='complete'),
  'candidates_promising',(select count(*) from public.strategy_candidates where result_status='promising'),
  'candidates_validated',(select count(*) from public.strategy_candidates where result_status='validated'),
  'candidates_elite',(select count(*) from public.strategy_candidates where result_status='elite'),
  'lineages_active',(select count(*) from public.mutation_lineages where status='active'),
  'mutations_queued',(select count(*) from public.mutation_candidates where status='queued'),
  'mutations_tested',(select count(*) from public.mutation_candidates where status='complete'),
  'mutations_promoted',(select count(*) from public.mutation_candidates where promoted=true),
  'frozen_strategies',(select count(*) from public.frozen_strategies),
  'mt5_packages',(select count(*) from public.mt5_packages where status='ready'),
  'top_candidate',(select to_jsonb(x) from (select id,name,family,result_status,fitness_score,profit_factor,expectancy_r,stability_score from public.strategy_candidates where status='complete' order by fitness_score desc nulls last limit 1) x),
  'top_lineage',(select to_jsonb(x) from (select id,name,family,generation,champion_fitness,champion_result_status,last_result from public.mutation_lineages order by champion_fitness desc nulls last limit 1) x),
  'recent_events',(select coalesce(jsonb_agg(to_jsonb(e) order by e.created_at desc),'[]'::jsonb) from (select id,level,component,message,details,created_at from public.system_events order by created_at desc limit 20) e)
);
$$;

-- All experiment tables are private. Only the Railway service role can access them.
alter table public.source_snapshots enable row level security;
alter table public.strategy_candidates enable row level security;
alter table public.mutation_lineages enable row level security;
alter table public.mutation_candidates enable row level security;
alter table public.mutation_memory enable row level security;
alter table public.frozen_strategies enable row level security;
alter table public.mt5_packages enable row level security;
alter table public.system_events enable row level security;


-- EVE Evolution Discovery Lab v2.0 — Research Integrity Foundation
-- Run only in the separate Discovery Lab Supabase project.
-- Never run this migration in EVE Algo Lab production.

-- Make the evidence store genuinely multi-timeframe-safe. The old key could
-- not retain M1 and M5 research states for the same symbol, anchor and time.
alter table public.source_snapshots
  drop constraint if exists source_snapshots_pkey;
alter table public.source_snapshots
  add primary key (symbol, source_interval, snapshot_interval, candle_time);
create index if not exists source_snapshots_dataset_idx
  on public.source_snapshots(symbol, source_interval, snapshot_interval, candle_time);

alter table public.strategy_candidates
  add column if not exists symbol text not null default 'XAU/USD',
  add column if not exists timeframe text not null default 'M5',
  add column if not exists research_stage text not null default 'selection',
  add column if not exists research_integrity_version text,
  add column if not exists dataset_version text,
  add column if not exists monte_carlo jsonb not null default '{}'::jsonb,
  add column if not exists execution_costs jsonb not null default '{}'::jsonb,
  add column if not exists ready_for_final boolean not null default false;

alter table public.mutation_candidates
  add column if not exists symbol text not null default 'XAU/USD',
  add column if not exists timeframe text not null default 'M5',
  add column if not exists research_stage text not null default 'selection',
  add column if not exists research_integrity_version text,
  add column if not exists dataset_version text,
  add column if not exists monte_carlo jsonb not null default '{}'::jsonb,
  add column if not exists execution_costs jsonb not null default '{}'::jsonb,
  add column if not exists ready_for_final boolean not null default false,
  add column if not exists validation_drawdown_delta double precision,
  add column if not exists holdout_used_for_selection boolean not null default false;

alter table public.mutation_lineages
  add column if not exists symbol text not null default 'XAU/USD',
  add column if not exists timeframe text not null default 'M5',
  add column if not exists dataset_version text,
  add column if not exists final_result_status text,
  add column if not exists final_metrics jsonb not null default '{}'::jsonb,
  add column if not exists final_evidence jsonb not null default '{}'::jsonb,
  add column if not exists holdout_opened_at timestamptz;

alter table public.frozen_strategies
  add column if not exists symbol text not null default 'XAU/USD',
  add column if not exists timeframe text not null default 'M5',
  add column if not exists research_stage text not null default 'final',
  add column if not exists result_status text,
  add column if not exists research_integrity_version text,
  add column if not exists dataset_version text,
  add column if not exists monte_carlo jsonb not null default '{}'::jsonb,
  add column if not exists execution_costs jsonb not null default '{}'::jsonb,
  add column if not exists m1_replay jsonb not null default '{}'::jsonb,
  add column if not exists trading_passport jsonb not null default '{}'::jsonb,
  add column if not exists compile_status text not null default 'required';

alter table public.mt5_packages
  add column if not exists trading_passport jsonb not null default '{}'::jsonb,
  add column if not exists compile_status text not null default 'required';

create index if not exists strategy_candidates_dataset_idx
  on public.strategy_candidates(dataset_version, timeframe, result_status);
create index if not exists mutation_candidates_dataset_idx
  on public.mutation_candidates(dataset_version, timeframe, result_status);
create index if not exists mutation_lineages_final_idx
  on public.mutation_lineages(status, holdout_opened_at desc nulls last);
create index if not exists frozen_strategies_passport_idx
  on public.frozen_strategies(symbol, timeframe, created_at desc);

-- Operator dashboard. "Online" is supplied separately by Railway runtime state;
-- this function reports persistent research state only.
create or replace function public.get_discovery_dashboard()
returns jsonb language sql stable as $$
select jsonb_build_object(
  'snapshots',(select count(*) from public.source_snapshots),
  'snapshot_from',(select min(candle_time) from public.source_snapshots),
  'snapshot_to',(select max(candle_time) from public.source_snapshots),
  'candidates_queued',(select count(*) from public.strategy_candidates where status='queued'),
  'candidates_running',(select count(*) from public.strategy_candidates where status='running'),
  'candidates_tested',(select count(*) from public.strategy_candidates where status='complete'),
  'candidates_promising',(select count(*) from public.strategy_candidates where result_status='promising'),
  'candidates_validated',(select count(*) from public.strategy_candidates where result_status='validated'),
  'candidates_elite',(select count(*) from public.strategy_candidates where result_status='elite'),
  'lineages_active',(select count(*) from public.mutation_lineages where status='active'),
  'lineages_finalised',(select count(*) from public.mutation_lineages where holdout_opened_at is not null),
  'mutations_queued',(select count(*) from public.mutation_candidates where status='queued'),
  'mutations_tested',(select count(*) from public.mutation_candidates where status='complete'),
  'mutations_promoted',(select count(*) from public.mutation_candidates where promoted=true),
  'frozen_strategies',(select count(*) from public.frozen_strategies),
  'mt5_packages',(select count(*) from public.mt5_packages where status='ready'),
  'latest_dataset_version',(
    select dataset_version from (
      select dataset_version, finished_at as at from public.mutation_candidates where dataset_version is not null
      union all
      select dataset_version, finished_at as at from public.strategy_candidates where dataset_version is not null
      union all
      select dataset_version, created_at as at from public.frozen_strategies where dataset_version is not null
    ) d order by at desc nulls last limit 1
  ),
  'top_candidate',(select to_jsonb(x) from (
    select id,name,family,symbol,timeframe,research_stage,result_status,fitness_score,profit_factor,expectancy_r,stability_score,dataset_version,ready_for_final
    from public.strategy_candidates where status='complete' order by fitness_score desc nulls last limit 1
  ) x),
  'top_lineage',(select to_jsonb(x) from (
    select id,name,family,symbol,timeframe,status,generation,champion_fitness,champion_result_status,last_result,final_result_status,holdout_opened_at,dataset_version
    from public.mutation_lineages order by champion_fitness desc nulls last limit 1
  ) x),
  'recent_events',(select coalesce(jsonb_agg(to_jsonb(x)),'[]'::jsonb) from (
    select id,level,component,message,details,created_at from public.system_events order by created_at desc limit 30
  ) x)
);
$$;

-- Data Health replaces deployment instructions in the operating UI.
create or replace function public.get_discovery_data_health()
returns jsonb language sql stable as $$
with base as (
  select
    count(*)::bigint as snapshots,
    min(candle_time) as snapshot_from,
    max(candle_time) as snapshot_to,
    count(*) filter (where outcome_complete)::bigint as completed_outcomes,
    count(*) filter (where not outcome_complete)::bigint as incomplete_outcomes,
    count(*) filter (where atr_14 is null or atr_14 <= 0)::bigint as invalid_atr_rows,
    count(*) filter (where feature_version is null or btrim(feature_version)='')::bigint as missing_feature_version_rows,
    count(distinct symbol)::integer as symbol_count,
    count(distinct snapshot_interval)::integer as snapshot_interval_count,
    count(distinct source_interval)::integer as source_interval_count,
    count(distinct feature_version)::integer as feature_version_count
  from public.source_snapshots
), dimensions as (
  select
    coalesce(jsonb_agg(distinct symbol) filter (where symbol is not null),'[]'::jsonb) as symbols,
    coalesce(jsonb_agg(distinct snapshot_interval) filter (where snapshot_interval is not null),'[]'::jsonb) as snapshot_intervals,
    coalesce(jsonb_agg(distinct source_interval) filter (where source_interval is not null),'[]'::jsonb) as source_intervals,
    coalesce(jsonb_agg(distinct feature_version) filter (where feature_version is not null),'[]'::jsonb) as feature_versions
  from public.source_snapshots
), grouped as (
  select coalesce(jsonb_agg(to_jsonb(x) order by x.symbol,x.snapshot_interval),'[]'::jsonb) as datasets
  from (
    select symbol,snapshot_interval,source_interval,min(candle_time) as from_time,max(candle_time) as to_time,
           count(*)::bigint as rows,
           count(*) filter (where outcome_complete)::bigint as completed_outcomes,
           max(imported_at) as last_imported_at
    from public.source_snapshots
    group by symbol,snapshot_interval,source_interval
  ) x
)
select jsonb_build_object(
  'status', case when b.snapshots=0 then 'empty'
                 when b.incomplete_outcomes>0 or b.invalid_atr_rows>0 or b.missing_feature_version_rows>0 then 'attention'
                 else 'healthy' end,
  'snapshots',b.snapshots,
  'snapshot_from',b.snapshot_from,
  'snapshot_to',b.snapshot_to,
  'completed_outcomes',b.completed_outcomes,
  'incomplete_outcomes',b.incomplete_outcomes,
  'outcome_completion_percent',case when b.snapshots>0 then round((b.completed_outcomes::numeric/b.snapshots::numeric)*100,2) else 0 end,
  'invalid_atr_rows',b.invalid_atr_rows,
  'missing_feature_version_rows',b.missing_feature_version_rows,
  'symbol_count',b.symbol_count,
  'snapshot_interval_count',b.snapshot_interval_count,
  'source_interval_count',b.source_interval_count,
  'feature_version_count',b.feature_version_count,
  'symbols',d.symbols,
  'snapshot_intervals',d.snapshot_intervals,
  'source_intervals',d.source_intervals,
  'feature_versions',d.feature_versions,
  'datasets',g.datasets,
  'latest_imported_at',(select max(imported_at) from public.source_snapshots),
  'latest_dataset_version',(
    select dataset_version from (
      select dataset_version, finished_at as at from public.mutation_candidates where dataset_version is not null
      union all
      select dataset_version, finished_at as at from public.strategy_candidates where dataset_version is not null
      union all
      select dataset_version, created_at as at from public.frozen_strategies where dataset_version is not null
    ) z order by at desc nulls last limit 1
  ),
  'primary_key_protection','symbol + source interval + snapshot interval + candle time prevents duplicate research states'
) from base b cross join dimensions d cross join grouped g;
$$;
-- EVE Evolution Discovery Lab v2.1 — Phase 1: Strategy Profiling Gate
-- Run only in the separate Discovery Lab Supabase project.
-- This migration is required before deploying the v2.1 Railway code.

alter table public.frozen_strategies
  add column if not exists profile_status text not null default 'pending',
  add column if not exists profile_version text,
  add column if not exists profile_reason text,
  add column if not exists profiled_at timestamptz,
  add column if not exists profile_attempts integer not null default 0,
  add column if not exists legacy_survivor boolean not null default false;

alter table public.mt5_packages
  add column if not exists profile_status text not null default 'pending',
  add column if not exists profile_version text,
  add column if not exists profile_reason text,
  add column if not exists profiled_at timestamptz,
  add column if not exists profile_attempts integer not null default 0,
  add column if not exists download_eligible boolean not null default false,
  add column if not exists profile_source text;

-- Add explicit status constraints without assuming they already exist.
alter table public.frozen_strategies drop constraint if exists frozen_strategies_profile_status_check;
alter table public.frozen_strategies add constraint frozen_strategies_profile_status_check
  check (profile_status in ('pending','profiling','retry','complete','failed'));

alter table public.mt5_packages drop constraint if exists mt5_packages_profile_status_check;
alter table public.mt5_packages add constraint mt5_packages_profile_status_check
  check (profile_status in ('pending','profiling','retry','complete','failed'));

create index if not exists frozen_strategies_profile_queue_idx
  on public.frozen_strategies(profile_status, created_at);
create index if not exists mt5_packages_profile_queue_idx
  on public.mt5_packages(profile_status, created_at);
create index if not exists mt5_packages_download_gate_idx
  on public.mt5_packages(download_eligible, status, created_at desc);

-- Every package that predates v2.1 must be examined by EVE. We deliberately
-- do not infer missing Passport values from the old filename or UI.
update public.mt5_packages
set profile_status = 'pending',
    profile_version = null,
    profile_reason = 'Legacy package detected. EVE must re-test the linked frozen rules and complete its Trading Passport.',
    profiled_at = null,
    download_eligible = false,
    profile_source = 'legacy_package_recovery'
where profile_status is distinct from 'complete'
   or profile_version is null
   or coalesce((trading_passport->'completeness'->>'complete')::boolean, false) = false;

update public.frozen_strategies f
set profile_status = 'pending',
    profile_version = null,
    profile_reason = 'Legacy survivor awaiting current-standard profiling.',
    profiled_at = null,
    legacy_survivor = true
where exists (select 1 from public.mt5_packages p where p.frozen_strategy_id = f.id)
  and (f.profile_version is null
       or coalesce((f.trading_passport->'completeness'->>'complete')::boolean, false) = false);

-- Dashboard counts only complete, download-eligible packages as usable MT5 packages.
create or replace function public.get_discovery_dashboard()
returns jsonb language sql stable as $$
select jsonb_build_object(
  'snapshots',(select count(*) from public.source_snapshots),
  'snapshot_from',(select min(candle_time) from public.source_snapshots),
  'snapshot_to',(select max(candle_time) from public.source_snapshots),
  'candidates_queued',(select count(*) from public.strategy_candidates where status='queued'),
  'candidates_running',(select count(*) from public.strategy_candidates where status='running'),
  'candidates_tested',(select count(*) from public.strategy_candidates where status='complete'),
  'candidates_promising',(select count(*) from public.strategy_candidates where result_status='promising'),
  'candidates_validated',(select count(*) from public.strategy_candidates where result_status='validated'),
  'candidates_elite',(select count(*) from public.strategy_candidates where result_status='elite'),
  'lineages_active',(select count(*) from public.mutation_lineages where status='active'),
  'lineages_finalised',(select count(*) from public.mutation_lineages where holdout_opened_at is not null),
  'mutations_queued',(select count(*) from public.mutation_candidates where status='queued'),
  'mutations_tested',(select count(*) from public.mutation_candidates where status='complete'),
  'mutations_promoted',(select count(*) from public.mutation_candidates where promoted=true),
  'frozen_strategies',(select count(*) from public.frozen_strategies),
  'mt5_packages',(select count(*) from public.mt5_packages where status='ready' and profile_status='complete' and download_eligible=true),
  'packages_profile_pending',(select count(*) from public.mt5_packages where profile_status in ('pending','profiling','retry')),
  'packages_profile_failed',(select count(*) from public.mt5_packages where profile_status='failed'),
  'latest_dataset_version',(
    select dataset_version from (
      select dataset_version, finished_at as at from public.mutation_candidates where dataset_version is not null
      union all
      select dataset_version, finished_at as at from public.strategy_candidates where dataset_version is not null
      union all
      select dataset_version, created_at as at from public.frozen_strategies where dataset_version is not null
    ) d order by at desc nulls last limit 1
  ),
  'top_candidate',(select to_jsonb(x) from (
    select id,name,family,symbol,timeframe,research_stage,result_status,fitness_score,profit_factor,expectancy_r,stability_score,dataset_version,ready_for_final
    from public.strategy_candidates where status='complete' order by fitness_score desc nulls last limit 1
  ) x),
  'top_lineage',(select to_jsonb(x) from (
    select id,name,family,symbol,timeframe,status,generation,champion_fitness,champion_result_status,last_result,final_result_status,holdout_opened_at,dataset_version
    from public.mutation_lineages order by champion_fitness desc nulls last limit 1
  ) x),
  'recent_events',(select coalesce(jsonb_agg(to_jsonb(x)),'[]'::jsonb) from (
    select id,level,component,message,details,created_at from public.system_events order by created_at desc limit 30
  ) x)
);
$$;
