-- EVE Scientist learning loop v1
-- Selection-stage validation may teach future research. Confirmation and final
-- holdout are deliberately absent from every function below.

create table if not exists public.scientist_learning_events (
    candidate_key text primary key,
    scientist_version text not null,
    research_dataset text not null,
    result_status text not null,
    contribution double precision not null default 0,
    validation_pf double precision not null default 0,
    validation_expectancy_r double precision not null default 0,
    validation_trades integer not null default 0,
    fitness_score double precision not null default 0,
    failed_gates jsonb not null default '[]'::jsonb,
    feature_keys jsonb not null default '[]'::jsonb,
    learned_at timestamptz not null default now(),
    updated_at timestamptz not null default now()
);

create index if not exists idx_scientist_learning_events_version_dataset
    on public.scientist_learning_events (scientist_version, research_dataset, learned_at desc);

alter table public.scientist_learning_events enable row level security;
revoke all on table public.scientist_learning_events from anon, authenticated;
grant select, insert, update, delete on table public.scientist_learning_events to service_role;

comment on table public.scientist_learning_events is
    'Idempotent selection-stage learning ledger for EVE Scientist. Confirmation and final holdout never teach this table.';

create or replace function public.eve_scientist_condition_key(p_condition jsonb)
returns text
language sql
immutable
set search_path = public, pg_temp
as $$
    with params as (
        select key, value
        from jsonb_each_text(coalesce(p_condition, '{}'::jsonb) - 'type')
    )
    select
        'condition:' || coalesce(p_condition ->> 'type', 'unknown') ||
        case
            when exists (select 1 from params) then ':' || (
                select string_agg(key || '=' || value, ',' order by key) from params
            )
            else ''
        end;
$$;

create or replace function public.eve_scientist_rule_feature_keys(p_rules jsonb)
returns table(feature_key text)
language sql
stable
set search_path = public, pg_temp
as $$
    with conditions as (
        select public.eve_scientist_condition_key(value) as feature_key
        from jsonb_array_elements(coalesce(p_rules #> '{entry,conditions}', '[]'::jsonb))
    ),
    schedule_feature as (
        select case
            when jsonb_array_length(coalesce(p_rules #> '{schedule,sessions}', '[]'::jsonb)) > 0
                then 'schedule:session:' || (p_rules #> '{schedule,sessions}' ->> 0)
            when jsonb_array_length(coalesce(p_rules #> '{schedule,hours_utc}', '[]'::jsonb)) > 0
                 and jsonb_array_length(coalesce(p_rules #> '{schedule,hours_utc}', '[]'::jsonb)) < 24
                then 'schedule:hours:' || (
                    select min(value::integer)::text || '-' || max(value::integer)::text
                    from jsonb_array_elements_text(p_rules #> '{schedule,hours_utc}')
                )
            else 'schedule:all_day'
        end as feature_key
    ),
    all_features as (
        select 'direction:' || coalesce(p_rules #>> '{entry,direction_rule}', 'current_direction') as feature_key
        union all select feature_key from conditions
        union all select feature_key from schedule_feature
        union all select 'environment:trend12:' || (p_rules #>> '{environment,trend_12}')
            where coalesce(p_rules #>> '{environment,trend_12}', 'any') <> 'any'
        union all select 'environment:trend48:' || (p_rules #>> '{environment,trend_48}')
            where coalesce(p_rules #>> '{environment,trend_48}', 'any') <> 'any'
        union all select 'environment:compression:' || (p_rules #>> '{environment,compression}')
            where coalesce(p_rules #>> '{environment,compression}', 'any') <> 'any'
        union all select 'environment:regime:' || (p_rules #> '{environment,regimes}' ->> 0)
            where jsonb_array_length(coalesce(p_rules #> '{environment,regimes}', '[]'::jsonb)) > 0
    )
    select distinct feature_key from all_features where feature_key is not null and feature_key <> '';
$$;

create or replace function public.eve_scientist_selection_contribution(
    p_result_status text,
    p_metrics jsonb
)
returns double precision
language sql
immutable
set search_path = public, pg_temp
as $$
    select greatest(
        -4.0,
        least(
            6.0,
            (coalesce((p_metrics #>> '{validation,profit_factor}')::double precision, 0.0) - 1.0) * 2.0
            + coalesce((p_metrics #>> '{validation,expectancy_r}')::double precision, 0.0) * 10.0
            + case coalesce(p_result_status, 'rejected')
                when 'elite' then 3.5
                when 'validated' then 2.5
                when 'promising' then 1.25
                when 'rejected' then -0.5
                else -0.25
              end
        )
    );
$$;

create or replace function public.eve_refresh_scientist_feature_memory(
    p_scientist_version text,
    p_research_dataset text
)
returns integer
language plpgsql
security definer
set search_path = public, pg_temp
as $$
declare
    affected integer := 0;
begin
    with candidate_learning as (
        select
            c.candidate_key,
            c.rules,
            public.eve_scientist_selection_contribution(c.result_status, c.metrics) as contribution,
            coalesce((c.metrics #>> '{validation,profit_factor}')::double precision, 0.0) as pf,
            coalesce((c.metrics #>> '{validation,expectancy_r}')::double precision, 0.0) as expectancy,
            coalesce((c.metrics #>> '{validation,trades}')::double precision, 0.0) as trades
        from public.strategy_candidates c
        where c.composer_version = p_scientist_version
          and c.research_stage = 'selection'
          and c.status = 'complete'
          and coalesce(c.rules #>> '{market,research_dataset}', 'legacy_15m') = p_research_dataset
    ),
    exploded as (
        select
            f.feature_key,
            c.contribution,
            c.pf,
            c.expectancy,
            c.trades
        from candidate_learning c
        cross join lateral public.eve_scientist_rule_feature_keys(c.rules) f
    ),
    aggregated as (
        select
            feature_key,
            count(*)::integer as trials,
            count(*) filter (where contribution > 0)::integer as positive_trials,
            avg(contribution) as score,
            avg(pf) as mean_pf,
            avg(expectancy) as mean_expectancy,
            avg(trades) as mean_trades
        from exploded
        group by feature_key
    )
    insert into public.scientist_feature_memory (
        feature_key,
        scientist_version,
        trials,
        positive_trials,
        score,
        mean_validation_pf,
        mean_validation_expectancy_r,
        mean_validation_trades,
        metadata,
        updated_at
    )
    select
        a.feature_key,
        p_scientist_version,
        a.trials,
        a.positive_trials,
        round(a.score::numeric, 6)::double precision,
        round(a.mean_pf::numeric, 6)::double precision,
        round(a.mean_expectancy::numeric, 6)::double precision,
        round(a.mean_trades::numeric, 3)::double precision,
        jsonb_build_object(
            'research_dataset', p_research_dataset,
            'snapshot_interval', case when p_research_dataset = 'every_m5_fabric' then '5min' else '15min' end,
            'learning_version', 'eve-scientist-learning-loop-v1',
            'selection_only', true,
            'confirmation_holdout_access', 'forbidden'
        ),
        now()
    from aggregated a
    on conflict (feature_key) do update set
        scientist_version = excluded.scientist_version,
        trials = excluded.trials,
        positive_trials = excluded.positive_trials,
        score = excluded.score,
        mean_validation_pf = excluded.mean_validation_pf,
        mean_validation_expectancy_r = excluded.mean_validation_expectancy_r,
        mean_validation_trades = excluded.mean_validation_trades,
        metadata = excluded.metadata,
        updated_at = excluded.updated_at;

    get diagnostics affected = row_count;
    return affected;
end;
$$;

create or replace function public.eve_capture_scientist_selection_learning()
returns trigger
language plpgsql
security definer
set search_path = public, pg_temp
as $$
declare
    dataset_name text;
    features jsonb;
    contribution_value double precision;
    failed jsonb;
    already_known boolean;
    memory_count integer;
begin
    if new.status <> 'complete'
       or new.research_stage <> 'selection'
       or coalesce(new.composer_version, '') <> 'eve-autonomous-scientist-v2' then
        return new;
    end if;

    dataset_name := coalesce(new.rules #>> '{market,research_dataset}', 'legacy_15m');
    contribution_value := public.eve_scientist_selection_contribution(new.result_status, new.metrics);
    failed := coalesce(new.evidence #> '{decision,failed_gates}', '[]'::jsonb);

    select coalesce(jsonb_agg(feature_key order by feature_key), '[]'::jsonb)
      into features
      from public.eve_scientist_rule_feature_keys(new.rules);

    select exists(
        select 1 from public.scientist_learning_events where candidate_key = new.candidate_key
    ) into already_known;

    insert into public.scientist_learning_events (
        candidate_key,
        scientist_version,
        research_dataset,
        result_status,
        contribution,
        validation_pf,
        validation_expectancy_r,
        validation_trades,
        fitness_score,
        failed_gates,
        feature_keys,
        learned_at,
        updated_at
    ) values (
        new.candidate_key,
        new.composer_version,
        dataset_name,
        coalesce(new.result_status, 'rejected'),
        contribution_value,
        coalesce((new.metrics #>> '{validation,profit_factor}')::double precision, 0.0),
        coalesce((new.metrics #>> '{validation,expectancy_r}')::double precision, 0.0),
        coalesce((new.metrics #>> '{validation,trades}')::integer, 0),
        coalesce(new.fitness_score, 0.0),
        failed,
        features,
        coalesce(new.finished_at, now()),
        now()
    )
    on conflict (candidate_key) do update set
        result_status = excluded.result_status,
        contribution = excluded.contribution,
        validation_pf = excluded.validation_pf,
        validation_expectancy_r = excluded.validation_expectancy_r,
        validation_trades = excluded.validation_trades,
        fitness_score = excluded.fitness_score,
        failed_gates = excluded.failed_gates,
        feature_keys = excluded.feature_keys,
        updated_at = excluded.updated_at;

    update public.scientist_hypotheses h
       set state = case
            when new.result_status in ('promising', 'validated', 'elite') then 'passed_selection'
            else 'rejected_selection'
           end,
           evidence = jsonb_set(
               coalesce(h.evidence, '{}'::jsonb),
               '{selection}',
               jsonb_build_object(
                   'result_status', new.result_status,
                   'fitness_score', new.fitness_score,
                   'validation', coalesce(new.metrics -> 'validation', '{}'::jsonb),
                   'failed_gates', failed,
                   'plain_reason', new.evidence #>> '{decision,plain_reason}',
                   'confirmation_holdout_access', 'forbidden'
               ),
               true
           ),
           updated_at = now()
     where h.candidate_key = new.candidate_key
       and h.scientist_version = new.composer_version;

    memory_count := public.eve_refresh_scientist_feature_memory(new.composer_version, dataset_name);

    if not already_known then
        insert into public.system_events(level, component, message, details)
        values (
            case when new.result_status in ('promising', 'validated', 'elite') then 'success' else 'info' end,
            'scientist_learning',
            'EVE learned from completed selection candidate ' || new.candidate_key || '.',
            jsonb_build_object(
                'candidate_key', new.candidate_key,
                'result_status', new.result_status,
                'research_dataset', dataset_name,
                'contribution', contribution_value,
                'memory_features_refreshed', memory_count,
                'failed_gates', failed,
                'learning_version', 'eve-scientist-learning-loop-v1',
                'confirmation_holdout_access', 'forbidden'
            )
        );
    end if;

    return new;
end;
$$;

drop trigger if exists trg_eve_scientist_selection_learning on public.strategy_candidates;
create trigger trg_eve_scientist_selection_learning
after insert or update on public.strategy_candidates
for each row execute function public.eve_capture_scientist_selection_learning();

-- Backfill already-completed Scientist v2 selection candidates through the same
-- trigger path. This changes no candidate research result; it only reconciles
-- the learning ledger, memory and hypothesis state.
update public.strategy_candidates
   set heartbeat_at = heartbeat_at
 where composer_version = 'eve-autonomous-scientist-v2'
   and research_stage = 'selection'
   and status = 'complete';

-- Scientist v2 is now authorised on every-M5. Make that dataset the final memory
-- authority after the mixed historical backfill above.
select public.eve_refresh_scientist_feature_memory('eve-autonomous-scientist-v2', 'every_m5_fabric');

revoke all on function public.eve_scientist_condition_key(jsonb) from public, anon, authenticated;
revoke all on function public.eve_scientist_rule_feature_keys(jsonb) from public, anon, authenticated;
revoke all on function public.eve_scientist_selection_contribution(text, jsonb) from public, anon, authenticated;
revoke all on function public.eve_refresh_scientist_feature_memory(text, text) from public, anon, authenticated;
revoke all on function public.eve_capture_scientist_selection_learning() from public, anon, authenticated;

grant execute on function public.eve_scientist_condition_key(jsonb) to service_role;
grant execute on function public.eve_scientist_rule_feature_keys(jsonb) to service_role;
grant execute on function public.eve_scientist_selection_contribution(text, jsonb) to service_role;
grant execute on function public.eve_refresh_scientist_feature_memory(text, text) to service_role;
