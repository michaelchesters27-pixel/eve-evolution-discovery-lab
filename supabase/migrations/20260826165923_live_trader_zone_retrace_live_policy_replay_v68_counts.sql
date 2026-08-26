-- Add explicit scorable/unscorable replay coverage counters.
-- Mirrors production migration 20260826165923.

alter table public.live_trader_zone_retrace_live_policy_state
  add column if not exists scorable_episodes integer not null default 0,
  add column if not exists unscorable_episodes integer not null default 0;
