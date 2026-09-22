-- Fix 5 extension: keep current-policy historical evaluation state per
-- immutable cohort instead of overwriting the legacy symbol-level state.

alter table public.live_trader_zone_retrace_current_policy_opportunities
  add column if not exists evidence_identity_version text,
  add column if not exists policy_id text references public.live_trader_policy_registry(policy_id) on delete restrict,
  add column if not exists scorer_id text references public.live_trader_scorer_registry(scorer_id) on delete restrict,
  add column if not exists cohort_id text references public.live_trader_evaluation_cohorts(cohort_id) on delete restrict,
  add column if not exists evaluation_stage text;

create index if not exists idx_live_trader_current_policy_opportunities_cohort
  on public.live_trader_zone_retrace_current_policy_opportunities (cohort_id, observed_at);

create table if not exists public.live_trader_zone_retrace_current_policy_cohort_state (
  cohort_id text primary key references public.live_trader_evaluation_cohorts(cohort_id) on delete restrict,
  evidence_identity_version text not null,
  policy_id text not null references public.live_trader_policy_registry(policy_id) on delete restrict,
  scorer_id text not null references public.live_trader_scorer_registry(scorer_id) on delete restrict,
  evaluation_stage text not null,
  symbol text not null,
  academy_version text not null,
  status text,
  cursor_time timestamptz,
  m1_coverage_start timestamptz,
  rows_scanned bigint not null default 0,
  opportunities_found integer not null default 0,
  scorable_opportunities integer not null default 0,
  unscorable_opportunities integer not null default 0,
  triggered integer not null default 0,
  wins integer not null default 0,
  losses integer not null default 0,
  breakeven integer not null default 0,
  total_r double precision,
  expectancy_per_opportunity_r double precision,
  expectancy_per_triggered_r double precision,
  trigger_rate double precision,
  caught_up boolean not null default false,
  promoted boolean not null default false,
  last_cycle_at timestamptz,
  last_error text,
  policy jsonb,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

alter table public.live_trader_zone_retrace_current_policy_cohort_state enable row level security;
revoke all on table public.live_trader_zone_retrace_current_policy_cohort_state from public, anon, authenticated;
grant select, insert, update on table public.live_trader_zone_retrace_current_policy_cohort_state to service_role;

create index if not exists idx_live_trader_current_policy_cohort_state_symbol
  on public.live_trader_zone_retrace_current_policy_cohort_state (symbol, academy_version, created_at desc);

comment on table public.live_trader_zone_retrace_current_policy_cohort_state is
'Cohort-scoped current-policy archive state. A policy/scorer change starts a new row and never overwrites an older evaluation cohort.';
