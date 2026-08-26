revoke all privileges on table public.live_trader_specialisations from anon, authenticated;
grant all privileges on table public.live_trader_specialisations to service_role;

revoke insert, update, delete, truncate, references, trigger on table public.live_trader_zone_retrace_evidence from anon, authenticated;
revoke insert, update, delete, truncate, references, trigger on table public.live_trader_zone_retrace_summary from anon, authenticated;
grant select on table public.live_trader_zone_retrace_evidence to anon, authenticated;
grant select on table public.live_trader_zone_retrace_summary to anon, authenticated;
grant all privileges on table public.live_trader_zone_retrace_evidence to service_role;
grant all privileges on table public.live_trader_zone_retrace_summary to service_role;

comment on table public.live_trader_specialisations is
'Server-owned Live Trader strategy configuration. Anonymous/authenticated browser roles have no direct privileges; service_role owns mutation.';
