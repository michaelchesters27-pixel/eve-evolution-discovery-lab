-- Fix 10 follow-up: failed bounded stages are retried after restart.
-- The original one-row-per-stage uniqueness made a successful retry impossible
-- to persist durably. Preserve every attempt and let the supervisor restore the
-- newest successful attempt by telemetry id.

alter table public.bounded_research_stage_runs
  drop constraint if exists bounded_research_stage_runs_cycle_id_stage_name_key;

drop index if exists public.bounded_research_stage_runs_cycle_id_stage_name_key;

create index if not exists idx_bounded_research_stage_runs_cycle_stage_attempt
  on public.bounded_research_stage_runs(cycle_id, stage_name, id desc);

comment on index public.idx_bounded_research_stage_runs_cycle_stage_attempt is
'Fix 10: permits multiple durable retry attempts per stage; newest attempt is ordered by id desc.';
