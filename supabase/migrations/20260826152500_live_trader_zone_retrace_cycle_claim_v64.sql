alter table public.live_trader_zone_retrace_learning_state
  add column if not exists legacy_cycle_count bigint,
  add column if not exists cycle_counter_version text,
  add column if not exists cycle_counter_accurate_since timestamptz,
  add column if not exists cycle_claimed_at timestamptz,
  add column if not exists cycle_claim_token text;

update public.live_trader_zone_retrace_learning_state
set legacy_cycle_count = coalesce(legacy_cycle_count, cycle_count),
    cycle_count = 0,
    last_cycle_at = null,
    cycle_counter_version = 'cross_process_completed_cycle_v64',
    cycle_counter_accurate_since = now(),
    cycle_claimed_at = null,
    cycle_claim_token = null,
    updated_at = now()
where cycle_counter_version is distinct from 'cross_process_completed_cycle_v64';

create or replace function public.claim_live_trader_zone_retrace_cycle(
  p_symbol text,
  p_min_interval_seconds integer default 300,
  p_lease_seconds integer default 420
)
returns table(
  claimed boolean,
  claim_token text,
  cycle_count bigint,
  last_cycle_at timestamptz,
  legacy_cycle_count bigint,
  accurate_since timestamptz
)
language plpgsql
set search_path = public
as $$
declare
  v_now timestamptz := now();
  v_token text := md5(coalesce(p_symbol,'') || clock_timestamp()::text || random()::text);
  v_count bigint;
  v_last timestamptz;
  v_legacy bigint;
  v_since timestamptz;
begin
  insert into public.live_trader_zone_retrace_learning_state(
    symbol, strategy_key, version, cycle_count, status,
    cycle_counter_version, cycle_counter_accurate_since, updated_at
  ) values (
    p_symbol, 'zone_retrace_v1', 'eve-live-zone-retrace-specialist-v58', 0, 'learning',
    'cross_process_completed_cycle_v64', v_now, v_now
  )
  on conflict (symbol) do nothing;

  update public.live_trader_zone_retrace_learning_state as s
  set cycle_claimed_at = v_now,
      cycle_claim_token = v_token,
      updated_at = v_now
  where s.symbol = p_symbol
    and (s.last_cycle_at is null or s.last_cycle_at <= v_now - make_interval(secs => greatest(p_min_interval_seconds, 60)))
    and (s.cycle_claimed_at is null or s.cycle_claimed_at <= v_now - make_interval(secs => greatest(p_lease_seconds, 60)))
  returning s.cycle_count, s.last_cycle_at, s.legacy_cycle_count, s.cycle_counter_accurate_since
  into v_count, v_last, v_legacy, v_since;

  if found then
    return query select true, v_token, v_count, v_last, v_legacy, v_since;
    return;
  end if;

  select s.cycle_count, s.last_cycle_at, s.legacy_cycle_count, s.cycle_counter_accurate_since
  into v_count, v_last, v_legacy, v_since
  from public.live_trader_zone_retrace_learning_state as s
  where s.symbol = p_symbol;

  return query select false, null::text, coalesce(v_count, 0), v_last, v_legacy, v_since;
end;
$$;

create or replace function public.complete_live_trader_zone_retrace_cycle(
  p_symbol text,
  p_claim_token text,
  p_version text,
  p_rows_evaluated bigint,
  p_relevant_episodes bigint,
  p_execution_evidence jsonb,
  p_best_execution text,
  p_promoted_execution text,
  p_status text
)
returns table(
  completed boolean,
  cycle_count bigint,
  completed_at timestamptz,
  legacy_cycle_count bigint,
  accurate_since timestamptz
)
language plpgsql
set search_path = public
as $$
declare
  v_now timestamptz := now();
  v_count bigint;
  v_legacy bigint;
  v_since timestamptz;
begin
  update public.live_trader_zone_retrace_learning_state as s
  set cycle_count = s.cycle_count + 1,
      last_cycle_at = v_now,
      version = coalesce(nullif(p_version,''), s.version),
      rows_evaluated = greatest(coalesce(p_rows_evaluated,0),0),
      relevant_episodes = greatest(coalesce(p_relevant_episodes,0),0),
      execution_evidence = coalesce(p_execution_evidence,'{}'::jsonb),
      best_execution = p_best_execution,
      promoted_execution = p_promoted_execution,
      status = coalesce(nullif(p_status,''),'learning'),
      cycle_claimed_at = null,
      cycle_claim_token = null,
      cycle_counter_version = 'cross_process_completed_cycle_v64',
      updated_at = v_now
  where s.symbol = p_symbol
    and s.cycle_claim_token = p_claim_token
  returning s.cycle_count, s.legacy_cycle_count, s.cycle_counter_accurate_since
  into v_count, v_legacy, v_since;

  if found then
    return query select true, v_count, v_now, v_legacy, v_since;
    return;
  end if;

  select s.cycle_count, s.legacy_cycle_count, s.cycle_counter_accurate_since
  into v_count, v_legacy, v_since
  from public.live_trader_zone_retrace_learning_state as s
  where s.symbol = p_symbol;

  return query select false, coalesce(v_count,0), null::timestamptz, v_legacy, v_since;
end;
$$;

revoke all on function public.claim_live_trader_zone_retrace_cycle(text,integer,integer) from public;
revoke all on function public.complete_live_trader_zone_retrace_cycle(text,text,text,bigint,bigint,jsonb,text,text,text) from public;
grant execute on function public.claim_live_trader_zone_retrace_cycle(text,integer,integer) to service_role;
grant execute on function public.complete_live_trader_zone_retrace_cycle(text,text,text,bigint,bigint,jsonb,text,text,text) to service_role;
