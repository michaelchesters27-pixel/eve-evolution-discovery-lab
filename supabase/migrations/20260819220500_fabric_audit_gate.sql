-- EVE every-M5 fabric audit gate.
-- Efficient database-side checks keep cutover decisions deterministic and auditable.

create or replace function public.get_fabric_audit()
returns jsonb
language sql
security definer
set search_path = public, pg_temp
as $$
with fabric as (
    select * from public.m5_research_snapshots where symbol = 'XAU/USD'
), bounds as (
    select count(*)::bigint as total_rows,
           min(candle_time) as first_time,
           max(candle_time) as last_time
    from fabric
), coverage as (
    select
        count(*) filter (where coalesce((mtf_context->'M1'->>'available')::boolean,false))::bigint as m1_rows,
        count(*) filter (where mtf_context->'M15' is not null and mtf_context->'M15' <> 'null'::jsonb)::bigint as m15_rows,
        count(*) filter (where mtf_context->'M30' is not null and mtf_context->'M30' <> 'null'::jsonb)::bigint as m30_rows,
        count(*) filter (where mtf_context->'H1' is not null and mtf_context->'H1' <> 'null'::jsonb)::bigint as h1_rows,
        count(*) filter (where mtf_context->'H4' is not null and mtf_context->'H4' <> 'null'::jsonb)::bigint as h4_rows,
        count(*) filter (where mtf_context->'D1' is not null and mtf_context->'D1' <> 'null'::jsonb)::bigint as d1_rows,
        count(*) filter (where outcome_complete)::bigint as complete_outcome_rows
    from fabric
), causality as (
    select
        count(*) filter (
            where mtf_context->'M15' is not null and mtf_context->'M15' <> 'null'::jsonb
              and (mtf_context->'M15'->>'completed_at')::timestamptz > (mtf_context->>'decision_time')::timestamptz
        )::bigint as m15_violations,
        count(*) filter (
            where mtf_context->'M30' is not null and mtf_context->'M30' <> 'null'::jsonb
              and (mtf_context->'M30'->>'completed_at')::timestamptz > (mtf_context->>'decision_time')::timestamptz
        )::bigint as m30_violations,
        count(*) filter (
            where mtf_context->'H1' is not null and mtf_context->'H1' <> 'null'::jsonb
              and (mtf_context->'H1'->>'completed_at')::timestamptz > (mtf_context->>'decision_time')::timestamptz
        )::bigint as h1_violations,
        count(*) filter (
            where mtf_context->'H4' is not null and mtf_context->'H4' <> 'null'::jsonb
              and (mtf_context->'H4'->>'completed_at')::timestamptz > (mtf_context->>'decision_time')::timestamptz
        )::bigint as h4_violations,
        count(*) filter (
            where mtf_context->'D1' is not null and mtf_context->'D1' <> 'null'::jsonb
              and (mtf_context->'D1'->>'completed_at')::timestamptz > (mtf_context->>'decision_time')::timestamptz
        )::bigint as d1_violations
    from fabric
), historical_labels as (
    select
        count(*) filter (where f.candle_time <= b.last_time - interval '4 hours')::bigint as eligible_rows,
        count(*) filter (where f.candle_time <= b.last_time - interval '4 hours' and f.outcome_complete)::bigint as complete_rows
    from fabric f cross join bounds b
), parity as (
    select
        count(*)::bigint as rows_compared,
        count(*) filter (
            where abs(m.open-s.open) <= 1e-8
              and abs(m.high-s.high) <= 1e-8
              and abs(m.low-s.low) <= 1e-8
              and abs(m.close-s.close) <= 1e-8
              and abs(coalesce(m.atr_14,0)-coalesce(s.atr_14,0)) <= 1e-8
              and abs(coalesce(m.average_range_12,0)-coalesce(s.average_range_12,0)) <= 1e-8
              and abs(coalesce(m.volatility_12,0)-coalesce(s.volatility_12,0)) <= 1e-8
              and abs(coalesce(m.compression_ratio,0)-coalesce(s.compression_ratio,0)) <= 1e-8
              and abs(coalesce(m.return_1_pct,0)-coalesce(s.return_1_pct,0)) <= 1e-8
              and abs(coalesce(m.return_3_pct,0)-coalesce(s.return_3_pct,0)) <= 1e-8
              and abs(coalesce(m.return_12_pct,0)-coalesce(s.return_12_pct,0)) <= 1e-8
              and abs(coalesce(m.return_48_pct,0)-coalesce(s.return_48_pct,0)) <= 1e-8
              and abs(coalesce(m.return_288_pct,0)-coalesce(s.return_288_pct,0)) <= 1e-8
              and abs(coalesce(m.trend_12_atr,0)-coalesce(s.trend_12_atr,0)) <= 1e-8
              and abs(coalesce(m.trend_48_atr,0)-coalesce(s.trend_48_atr,0)) <= 1e-8
              and m.direction = s.direction
              and m.streak = s.streak
              and m.session = s.session
              and m.regime = s.regime
        )::bigint as rows_matching
    from fabric m
    join public.source_snapshots s
      on s.symbol=m.symbol
     and s.source_interval='5min'
     and s.snapshot_interval='15min'
     and s.candle_time=m.candle_time
), state as (
    select status,cursor_time,source_to,last_error
    from public.fabric_build_state
    where symbol='XAU/USD'
    limit 1
), metrics as (
    select
        b.*,
        c.*,
        ca.*,
        h.eligible_rows,
        h.complete_rows as historical_complete_rows,
        p.rows_compared,
        p.rows_matching,
        coalesce(st.status,'queued') as build_status,
        st.cursor_time,
        st.source_to,
        st.last_error,
        case when b.total_rows > 0 then c.m1_rows::double precision/b.total_rows else 0 end as m1_coverage,
        case when b.total_rows > 0 then c.m15_rows::double precision/b.total_rows else 0 end as m15_coverage,
        case when b.total_rows > 0 then c.m30_rows::double precision/b.total_rows else 0 end as m30_coverage,
        case when b.total_rows > 0 then c.h1_rows::double precision/b.total_rows else 0 end as h1_coverage,
        case when b.total_rows > 0 then c.h4_rows::double precision/b.total_rows else 0 end as h4_coverage,
        case when b.total_rows > 0 then c.d1_rows::double precision/b.total_rows else 0 end as d1_coverage,
        case when h.eligible_rows > 0 then h.complete_rows::double precision/h.eligible_rows else 0 end as historical_label_coverage,
        case when p.rows_compared > 0 then p.rows_matching::double precision/p.rows_compared else 0 end as parity_rate
    from bounds b cross join coverage c cross join causality ca cross join historical_labels h cross join parity p left join state st on true
)
select jsonb_build_object(
    'build_status', build_status,
    'cursor_time', cursor_time,
    'source_to', source_to,
    'last_error', last_error,
    'rows', total_rows,
    'first_time', first_time,
    'last_time', last_time,
    'coverage', jsonb_build_object(
        'M1', m1_coverage, 'M15', m15_coverage, 'M30', m30_coverage,
        'H1', h1_coverage, 'H4', h4_coverage, 'D1', d1_coverage,
        'historical_outcomes', historical_label_coverage
    ),
    'causality_violations', jsonb_build_object(
        'M15', m15_violations, 'M30', m30_violations, 'H1', h1_violations,
        'H4', h4_violations, 'D1', d1_violations,
        'total', m15_violations+m30_violations+h1_violations+h4_violations+d1_violations
    ),
    'feature_parity', jsonb_build_object(
        'rows_compared', rows_compared,
        'rows_matching', rows_matching,
        'pass_rate', parity_rate
    ),
    'gates', jsonb_build_object(
        'caught_up', build_status='caught_up',
        'enough_history', total_rows >= 100000,
        'm1_coverage', m1_coverage >= 0.95,
        'higher_timeframe_coverage', least(m15_coverage,m30_coverage,h1_coverage,h4_coverage,d1_coverage) >= 0.98,
        'historical_outcomes', historical_label_coverage >= 0.995,
        'zero_lookahead', (m15_violations+m30_violations+h1_violations+h4_violations+d1_violations)=0,
        'feature_parity', rows_compared >= 1000 and parity_rate >= 0.995
    ),
    'ready_for_scientist_cutover',
        build_status='caught_up'
        and total_rows >= 100000
        and m1_coverage >= 0.95
        and least(m15_coverage,m30_coverage,h1_coverage,h4_coverage,d1_coverage) >= 0.98
        and historical_label_coverage >= 0.995
        and (m15_violations+m30_violations+h1_violations+h4_violations+d1_violations)=0
        and rows_compared >= 1000 and parity_rate >= 0.995
)
from metrics;
$$;

revoke all on function public.get_fabric_audit() from public, anon, authenticated;
grant execute on function public.get_fabric_audit() to service_role;
