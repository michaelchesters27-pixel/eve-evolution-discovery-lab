-- EVE every-M5 fabric incremental audit cache.
-- The dashboard must never rescan hundreds of thousands of JSONB rows on every refresh.

create table if not exists public.fabric_audit_state (
    symbol text primary key,
    fabric_version text not null,
    audited_through timestamptz,
    first_time timestamptz,
    last_time timestamptz,
    rows_audited bigint not null default 0,
    complete_rows bigint not null default 0,
    m1_rows bigint not null default 0,
    m15_rows bigint not null default 0,
    m30_rows bigint not null default 0,
    h1_rows bigint not null default 0,
    h4_rows bigint not null default 0,
    d1_rows bigint not null default 0,
    m15_violations bigint not null default 0,
    m30_violations bigint not null default 0,
    h1_violations bigint not null default 0,
    h4_violations bigint not null default 0,
    d1_violations bigint not null default 0,
    parity_rows_compared bigint not null default 0,
    parity_rows_matching bigint not null default 0,
    updated_at timestamptz not null default now()
);

alter table public.fabric_audit_state enable row level security;
revoke all on table public.fabric_audit_state from anon, authenticated;
grant select, insert, update, delete on table public.fabric_audit_state to service_role;

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
)
select jsonb_build_object(
    'build_status', build_status,
    'cursor_time', cursor_time,
    'source_to', source_to,
    'last_error', last_error,
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
        and parity_rows_compared>=1000 and parity_rate>=0.995
)
from m;
$$;

revoke all on function public.get_fabric_audit() from public, anon, authenticated;
grant execute on function public.get_fabric_audit() to service_role;

comment on table public.fabric_audit_state is
'Incremental integrity counters for the every-M5 fabric. Updated by the Railway fabric builder so operator reads stay constant-time as history grows.';
