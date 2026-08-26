alter table public.live_trader_zone_retrace_current_policy_state
  add column if not exists scan_lease_token text,
  add column if not exists scan_lease_acquired_at timestamptz,
  add column if not exists scan_lease_until timestamptz,
  add column if not exists scan_lease_owner text;

create or replace function public.claim_live_trader_zone_retrace_current_policy_scan(
  p_symbol text,
  p_academy_version text,
  p_owner text default null,
  p_lease_seconds integer default 300
)
returns table(
  claimed boolean,
  claim_token text,
  cursor_time timestamptz,
  rows_scanned bigint,
  lease_until timestamptz
)
language plpgsql
set search_path = public
as $$
declare
  v_now timestamptz := now();
  v_token text := md5(coalesce(p_symbol,'') || coalesce(p_academy_version,'') || clock_timestamp()::text || random()::text);
  v_cursor timestamptz;
  v_rows bigint;
  v_until timestamptz;
begin
  insert into public.live_trader_zone_retrace_current_policy_state(symbol, academy_version, status)
  values (p_symbol, p_academy_version, 'scanning')
  on conflict (symbol) do nothing;

  update public.live_trader_zone_retrace_current_policy_state as s
  set scan_lease_token = v_token,
      scan_lease_acquired_at = v_now,
      scan_lease_until = v_now + make_interval(secs => greatest(p_lease_seconds, 30)),
      scan_lease_owner = nullif(p_owner, '')
  where s.symbol = p_symbol
    and (s.scan_lease_until is null or s.scan_lease_until <= v_now)
  returning s.cursor_time, s.rows_scanned, s.scan_lease_until
  into v_cursor, v_rows, v_until;

  if found then
    return query select true, v_token, v_cursor, coalesce(v_rows,0), v_until;
    return;
  end if;

  select s.cursor_time, s.rows_scanned, s.scan_lease_until
  into v_cursor, v_rows, v_until
  from public.live_trader_zone_retrace_current_policy_state as s
  where s.symbol = p_symbol;

  return query select false, null::text, v_cursor, coalesce(v_rows,0), v_until;
end;
$$;

create or replace function public.release_live_trader_zone_retrace_current_policy_scan(
  p_symbol text,
  p_claim_token text
)
returns boolean
language plpgsql
set search_path = public
as $$
declare
  v_released boolean := false;
begin
  update public.live_trader_zone_retrace_current_policy_state as s
  set scan_lease_token = null,
      scan_lease_acquired_at = null,
      scan_lease_until = null,
      scan_lease_owner = null
  where s.symbol = p_symbol
    and s.scan_lease_token = p_claim_token;
  v_released := found;
  return v_released;
end;
$$;

revoke all on function public.claim_live_trader_zone_retrace_current_policy_scan(text,text,text,integer) from public;
revoke all on function public.release_live_trader_zone_retrace_current_policy_scan(text,text) from public;
grant execute on function public.claim_live_trader_zone_retrace_current_policy_scan(text,text,text,integer) to service_role;
grant execute on function public.release_live_trader_zone_retrace_current_policy_scan(text,text) to service_role;
