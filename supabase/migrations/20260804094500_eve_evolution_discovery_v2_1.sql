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
