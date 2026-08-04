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
