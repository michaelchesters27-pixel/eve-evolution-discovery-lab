alter table public.live_trader_zone_retrace_current_policy_opportunities
  add column if not exists gross_realised_r double precision,
  add column if not exists estimated_cost_r double precision,
  add column if not exists net_realised_r double precision,
  add column if not exists cost_model_version text,
  add column if not exists execution_costs jsonb;

alter table public.live_trader_zone_retrace_current_policy_cohort_state
  add column if not exists total_gross_r double precision,
  add column if not exists total_net_r double precision,
  add column if not exists gross_expectancy_per_opportunity_r double precision,
  add column if not exists net_expectancy_per_opportunity_r double precision,
  add column if not exists gross_expectancy_per_triggered_r double precision,
  add column if not exists net_expectancy_per_triggered_r double precision,
  add column if not exists cost_model_version text;
