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
  primary key (symbol, snapshot_interval, candle_time)
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
