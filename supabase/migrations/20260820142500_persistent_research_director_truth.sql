-- Persist the latest completed Research Director cycle in the operator audit payload.
-- Railway process memory resets on deploy, but EVE's research direction and ablation
-- evidence must remain visible until a newer completed Director cycle replaces it.

create or replace function public.get_fabric_audit()
returns jsonb
language sql
stable
security definer
set search_path = public, pg_temp
as $$
with st as (
    select status,cursor_time,source_from,source_to,last_error,rows_written,complete_rows,m1_available_rows
    from public.fabric_build_state
    where symbol='XAU/USD'
    limit 1
), a as (
    select * from public.fabric_audit_state where symbol='XAU/USD' limit 1
), m as (
    select
        coalesce(st.status,'queued') as build_status,
        st.cursor_time,
        st.source_to,
        st.last_error,
        coalesce(st.rows_written,0)::bigint as fabric_rows_total,
        coalesce(st.complete_rows,0)::bigint as fabric_rows_complete,
        coalesce(st.m1_available_rows,0)::bigint as fabric_m1_available_rows,
        coalesce(a.rows_audited,0)::bigint as rows_audited,
        a.audited_through,
        a.first_time,
        a.last_time,
        coalesce(a.complete_rows,0)::bigint as complete_rows,
        coalesce(a.m1_rows,0)::bigint as m1_rows,
        coalesce(a.m15_rows,0)::bigint as m15_rows,
        coalesce(a.m30_rows,0)::bigint as m30_rows,
        coalesce(a.h1_rows,0)::bigint as h1_rows,
        coalesce(a.h4_rows,0)::bigint as h4_rows,
        coalesce(a.d1_rows,0)::bigint as d1_rows,
        coalesce(a.m15_violations,0)::bigint as m15_violations,
        coalesce(a.m30_violations,0)::bigint as m30_violations,
        coalesce(a.h1_violations,0)::bigint as h1_violations,
        coalesce(a.h4_violations,0)::bigint as h4_violations,
        coalesce(a.d1_violations,0)::bigint as d1_violations,
        coalesce(a.parity_rows_compared,0)::bigint as parity_rows_compared,
        coalesce(a.parity_rows_matching,0)::bigint as parity_rows_matching,
        case when coalesce(a.rows_audited,0)>0 then a.m1_rows::double precision/a.rows_audited else 0 end as m1_coverage,
        case when coalesce(a.rows_audited,0)>0 then a.m15_rows::double precision/a.rows_audited else 0 end as m15_coverage,
        case when coalesce(a.rows_audited,0)>0 then a.m30_rows::double precision/a.rows_audited else 0 end as m30_coverage,
        case when coalesce(a.rows_audited,0)>0 then a.h1_rows::double precision/a.rows_audited else 0 end as h1_coverage,
        case when coalesce(a.rows_audited,0)>0 then a.h4_rows::double precision/a.rows_audited else 0 end as h4_coverage,
        case when coalesce(a.rows_audited,0)>0 then a.d1_rows::double precision/a.rows_audited else 0 end as d1_coverage,
        case when coalesce(a.rows_audited,0)>0 then a.complete_rows::double precision/a.rows_audited else 0 end as outcome_coverage,
        case when coalesce(a.parity_rows_compared,0)>0 then a.parity_rows_matching::double precision/a.parity_rows_compared else 0 end as parity_rate,
        (a.audited_through is not null and st.cursor_time is not null and a.audited_through >= st.cursor_time) as audit_current
    from st full join a on true
), authority as (
    select active_dataset,status,fabric_version,cutover_at,last_verified_at,updated_at
    from public.scientist_dataset_state
    where scientist_version='eve-autonomous-scientist-v2'
    limit 1
), memory as (
    select count(*)::bigint as feature_count
    from public.scientist_feature_memory
    where scientist_version='eve-autonomous-scientist-v2'
      and coalesce(metadata->>'research_dataset','')='every_m5_fabric'
), science as (
    select
        count(*)::bigint as science_cycles,
        coalesce(sum(coalesce((details->>'screened')::bigint,0)),0)::bigint as screened,
        coalesce(sum(coalesce((details->>'promoted')::bigint,0)),0)::bigint as queued,
        max(created_at) as last_science_at
    from public.system_events
    where component='autonomous_scientist'
      and coalesce(details->>'scientist_version','')='eve-autonomous-scientist-v2'
), director as (
    select created_at, details
    from public.system_events
    where component='research_director'
      and coalesce(details->>'research_director_version','')='eve-research-director-v1'
    order by created_at desc
    limit 1
)
select jsonb_build_object(
    'build_status', build_status,
    'cursor_time', cursor_time,
    'source_to', source_to,
    'last_error', last_error,
    'fabric_rows_total', fabric_rows_total,
    'fabric_rows_complete', fabric_rows_complete,
    'fabric_m1_available_rows', fabric_m1_available_rows,
    'rows', rows_audited,
    'first_time', first_time,
    'last_time', last_time,
    'audited_through', audited_through,
    'audit_current', coalesce(audit_current,false),
    'coverage', jsonb_build_object(
        'M1',m1_coverage,'M15',m15_coverage,'M30',m30_coverage,'H1',h1_coverage,'H4',h4_coverage,'D1',d1_coverage,
        'historical_outcomes',outcome_coverage
    ),
    'causality_violations', jsonb_build_object(
        'M15',m15_violations,'M30',m30_violations,'H1',h1_violations,'H4',h4_violations,'D1',d1_violations,
        'total',m15_violations+m30_violations+h1_violations+h4_violations+d1_violations
    ),
    'feature_parity', jsonb_build_object(
        'rows_compared',parity_rows_compared,
        'rows_matching',parity_rows_matching,
        'pass_rate',parity_rate
    ),
    'gates', jsonb_build_object(
        'caught_up',build_status='caught_up',
        'audit_current',coalesce(audit_current,false),
        'enough_history',rows_audited>=100000,
        'm1_coverage',m1_coverage>=0.95,
        'higher_timeframe_coverage',least(m15_coverage,m30_coverage,h1_coverage,h4_coverage,d1_coverage)>=0.98,
        'historical_outcomes',outcome_coverage>=0.995,
        'zero_lookahead',(m15_violations+m30_violations+h1_violations+h4_violations+d1_violations)=0,
        'feature_parity',parity_rows_compared>=1000 and parity_rate>=0.995
    ),
    'ready_for_scientist_cutover',
        build_status='caught_up'
        and coalesce(audit_current,false)
        and rows_audited>=100000
        and m1_coverage>=0.95
        and least(m15_coverage,m30_coverage,h1_coverage,h4_coverage,d1_coverage)>=0.98
        and outcome_coverage>=0.995
        and (m15_violations+m30_violations+h1_violations+h4_violations+d1_violations)=0
        and parity_rows_compared>=1000 and parity_rate>=0.995,
    'scientist_authority', jsonb_build_object(
        'active_dataset',coalesce((select active_dataset from authority),'legacy_15m'),
        'status',coalesce((select status from authority),'pending_cutover'),
        'fabric_version',(select fabric_version from authority),
        'cutover_at',(select cutover_at from authority),
        'last_verified_at',(select last_verified_at from authority),
        'updated_at',(select updated_at from authority)
    ),
    'scientist_memory_features',coalesce((select feature_count from memory),0),
    'scientist_persistent_stats',jsonb_build_object(
        'science_cycles',coalesce((select science_cycles from science),0),
        'screened',coalesce((select screened from science),0),
        'queued',coalesce((select queued from science),0),
        'last_science_at',(select last_science_at from science)
    ),
    'scientist_persistent_director',coalesce(
        (select jsonb_build_object(
            'created_at',created_at,
            'research_director_version',details->>'research_director_version',
            'active_dataset',details->>'active_dataset',
            'memory_features',coalesce((details->>'memory_features')::bigint,0),
            'family_plan',coalesce(details->'family_plan','[]'::jsonb),
            'interaction_memory',coalesce(details->'interaction_memory','{}'::jsonb),
            'ablation',coalesce(details->'ablation','{}'::jsonb),
            'confirmation_holdout_access',details->>'confirmation_holdout_access'
        ) from director),
        '{}'::jsonb
    )
)
from m;
$$;

revoke all on function public.get_fabric_audit() from public, anon, authenticated;
grant execute on function public.get_fabric_audit() to service_role;
