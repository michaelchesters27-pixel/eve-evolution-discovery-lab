-- Final acceptance remediation Fix 10.
-- Make stage-attempt lifecycle durable before compute starts, allow explicit
-- running/interrupted states, and checkpoint in-flight budget consumption.

alter table public.bounded_research_stage_runs
  alter column finished_at drop not null,
  add column if not exists heartbeat_at timestamptz;

alter table public.bounded_research_stage_runs
  drop constraint if exists bounded_research_stage_runs_outcome_check;

alter table public.bounded_research_stage_runs
  add constraint bounded_research_stage_runs_outcome_check
  check (outcome in ('running','progressed','no_op','completed','failed','interrupted'));

create index if not exists idx_bounded_research_stage_runs_cycle_id_desc
  on public.bounded_research_stage_runs(cycle_id, id desc);

comment on column public.bounded_research_stage_runs.heartbeat_at is
'Fix 10: supervisor checkpoint time for an in-flight bounded stage attempt.';


revoke update on table public.bounded_research_stage_runs from public, anon, authenticated;
grant update on table public.bounded_research_stage_runs to service_role;
