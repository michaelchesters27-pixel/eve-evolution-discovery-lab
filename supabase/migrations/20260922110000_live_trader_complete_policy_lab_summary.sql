-- Audit remediation Fix 7: complete Policy Lab summaries without client/API row caps.
-- Qualification still uses the same v92 evidence protocol. This migration only changes
-- how current-cohort evidence is summarized: complete server-side SQL aggregation.

create or replace function public.get_live_trader_policy_lab_complete_summary_v93(
  p_learning_version text,
  p_cohort_ids text[],
  p_timing_contract_version text,
  p_cost_model_version text
)
returns jsonb
language sql
stable
security definer
set search_path = public
as $$
with requested as (
  select distinct unnest(coalesce(p_cohort_ids, array[]::text[])) as cohort_id
),
verified as (
  select
    o.id,
    o.cohort_id,
    o.observed_at,
    o.entry_triggered,
    o.gross_realised_r,
    o.net_realised_r
  from public.live_trader_opinions o
  join requested r on r.cohort_id = o.cohort_id
  where o.learning_version = p_learning_version
    and o.status = 'resolved'
    and o.timing_contract_version = p_timing_contract_version
    and o.cost_model_version = p_cost_model_version
),
resolved_counts as (
  select cohort_id, count(*)::bigint as resolved
  from verified
  group by cohort_id
),
triggered as (
  select *
  from verified
  where entry_triggered is true
    and net_realised_r is not null
),
triggered_counts as (
  select
    cohort_id,
    count(*)::bigint as triggered,
    count(*) filter (where net_realised_r > 0)::bigint as wins,
    count(*) filter (where net_realised_r < 0)::bigint as losses,
    count(*) filter (where net_realised_r = 0)::bigint as breakeven,
    coalesce(sum(gross_realised_r),0.0)::double precision as total_gross_r,
    coalesce(sum(net_realised_r),0.0)::double precision as total_net_r
  from triggered
  group by cohort_id
),
daily as (
  select
    cohort_id,
    observed_at::date as day,
    count(*)::bigint as triggered,
    count(*) filter (where net_realised_r > 0)::bigint as wins,
    count(*) filter (where net_realised_r < 0)::bigint as losses,
    count(*) filter (where net_realised_r = 0)::bigint as breakeven,
    coalesce(sum(gross_realised_r),0.0)::double precision as gross_r,
    coalesce(sum(net_realised_r),0.0)::double precision as net_r
  from triggered
  group by cohort_id, observed_at::date
),
ordered as (
  select
    cohort_id,
    observed_at,
    id,
    sum(net_realised_r) over (
      partition by cohort_id
      order by observed_at asc, id asc
      rows between unbounded preceding and current row
    )::double precision as equity
  from triggered
),
drawdowns as (
  select
    cohort_id,
    coalesce(max(greatest(0.0, peak - equity)),0.0)::double precision as max_drawdown_net_r
  from (
    select
      cohort_id,
      equity,
      greatest(
        0.0,
        max(equity) over (
          partition by cohort_id
          order by observed_at asc, id asc
          rows between unbounded preceding and current row
        )
      )::double precision as peak
    from ordered
  ) x
  group by cohort_id
),
daily_json as (
  select
    cohort_id,
    jsonb_agg(
      jsonb_build_object(
        'day', day::text,
        'triggered', triggered,
        'wins', wins,
        'losses', losses,
        'breakeven', breakeven,
        'gross_r', gross_r,
        'net_r', net_r
      )
      order by day asc
    ) as daily
  from daily
  group by cohort_id
),
cohort_rows as (
  select
    r.cohort_id,
    coalesce(rc.resolved,0)::bigint as resolved,
    coalesce(tc.triggered,0)::bigint as triggered,
    coalesce(tc.wins,0)::bigint as wins,
    coalesce(tc.losses,0)::bigint as losses,
    coalesce(tc.breakeven,0)::bigint as breakeven,
    coalesce(tc.total_gross_r,0.0)::double precision as total_gross_r,
    coalesce(tc.total_net_r,0.0)::double precision as total_net_r,
    coalesce(dd.max_drawdown_net_r,0.0)::double precision as max_drawdown_net_r,
    coalesce(dj.daily,'[]'::jsonb) as daily
  from requested r
  left join resolved_counts rc using (cohort_id)
  left join triggered_counts tc using (cohort_id)
  left join drawdowns dd using (cohort_id)
  left join daily_json dj using (cohort_id)
),
excluded as (
  select count(*)::bigint as n
  from public.live_trader_opinions o
  where o.learning_version = p_learning_version
    and o.status = 'resolved'
    and (
      o.cohort_id is null
      or not (o.cohort_id = any(coalesce(p_cohort_ids, array[]::text[])))
      or o.timing_contract_version is distinct from p_timing_contract_version
      or o.cost_model_version is distinct from p_cost_model_version
    )
)
select jsonb_build_object(
  'version', 'eve-live-policy-lab-complete-summary-v93',
  'summary_scope', 'complete_current_cohorts',
  'complete', true,
  'rolling', false,
  'api_row_cap_applies', false,
  'source', 'server_side_sql_aggregation',
  'cohorts', coalesce((
    select jsonb_agg(
      jsonb_build_object(
        'cohort_id', cohort_id,
        'resolved', resolved,
        'triggered', triggered,
        'wins', wins,
        'losses', losses,
        'breakeven', breakeven,
        'total_gross_r', total_gross_r,
        'total_net_r', total_net_r,
        'max_drawdown_net_r', max_drawdown_net_r,
        'daily', daily
      )
      order by cohort_id
    )
    from cohort_rows
  ), '[]'::jsonb),
  'excluded_unverified_resolved', coalesce((select n from excluded),0),
  'generated_at', now()
);
$$;

revoke all on function public.get_live_trader_policy_lab_complete_summary_v93(text,text[],text,text)
  from public, anon, authenticated;
grant execute on function public.get_live_trader_policy_lab_complete_summary_v93(text,text[],text,text)
  to service_role;

create index if not exists idx_live_trader_opinions_policy_lab_summary_v93
  on public.live_trader_opinions (learning_version, cohort_id, status, observed_at, id)
  where cohort_id is not null and status = 'resolved';

comment on function public.get_live_trader_policy_lab_complete_summary_v93(text,text[],text,text) is
'Fix 7: complete server-side aggregation for current Policy Lab cohorts. Removes client/API row caps and oldest-prefix freezes without changing signal selection or historical evidence.';
