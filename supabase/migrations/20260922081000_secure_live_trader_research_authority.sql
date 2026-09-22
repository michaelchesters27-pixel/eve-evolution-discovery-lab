-- Audit remediation 2026-09-22:
-- Keep Live Trader research/state authority server-owned. Browser roles have
-- no direct access to these ledgers; the Railway backend uses service_role.

alter table public.research_data_quarantine enable row level security;
alter table public.live_trader_zone_retrace_learning_state enable row level security;
alter table public.live_trader_zone_retrace_live_policy_replays enable row level security;
alter table public.live_trader_zone_retrace_live_policy_state enable row level security;
alter table public.live_trader_zone_retrace_current_policy_opportunities enable row level security;
alter table public.live_trader_zone_retrace_current_policy_state enable row level security;

revoke all privileges on table public.research_data_quarantine from public, anon, authenticated;
revoke all privileges on table public.live_trader_zone_retrace_learning_state from public, anon, authenticated;
revoke all privileges on table public.live_trader_zone_retrace_live_policy_replays from public, anon, authenticated;
revoke all privileges on table public.live_trader_zone_retrace_live_policy_state from public, anon, authenticated;
revoke all privileges on table public.live_trader_zone_retrace_current_policy_opportunities from public, anon, authenticated;
revoke all privileges on table public.live_trader_zone_retrace_current_policy_state from public, anon, authenticated;

grant all privileges on table public.research_data_quarantine to service_role;
grant all privileges on table public.live_trader_zone_retrace_learning_state to service_role;
grant all privileges on table public.live_trader_zone_retrace_live_policy_replays to service_role;
grant all privileges on table public.live_trader_zone_retrace_live_policy_state to service_role;
grant all privileges on table public.live_trader_zone_retrace_current_policy_opportunities to service_role;
grant all privileges on table public.live_trader_zone_retrace_current_policy_state to service_role;

revoke execute on function public.claim_live_trader_zone_retrace_current_policy_scan(text,text,text,integer)
  from public, anon, authenticated;
revoke execute on function public.release_live_trader_zone_retrace_current_policy_scan(text,text)
  from public, anon, authenticated;
revoke execute on function public.claim_live_trader_zone_retrace_cycle(text,integer,integer)
  from public, anon, authenticated;
revoke execute on function public.complete_live_trader_zone_retrace_cycle(text,text,text,bigint,bigint,jsonb,text,text,text)
  from public, anon, authenticated;

grant execute on function public.claim_live_trader_zone_retrace_current_policy_scan(text,text,text,integer)
  to service_role;
grant execute on function public.release_live_trader_zone_retrace_current_policy_scan(text,text)
  to service_role;
grant execute on function public.claim_live_trader_zone_retrace_cycle(text,integer,integer)
  to service_role;
grant execute on function public.complete_live_trader_zone_retrace_cycle(text,text,text,bigint,bigint,jsonb,text,text,text)
  to service_role;

comment on table public.live_trader_zone_retrace_learning_state is
'Server-owned Live Trader specialist learning state. Direct browser-role access is disabled; service_role owns mutation.';
comment on table public.live_trader_zone_retrace_current_policy_state is
'Server-owned current-policy academy state. Direct browser-role access is disabled; service_role owns mutation.';
comment on table public.live_trader_zone_retrace_current_policy_opportunities is
'Server-owned current-policy evidence ledger. Direct browser-role access is disabled; service_role owns mutation.';
