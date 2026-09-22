-- Audit remediation Fix 8: authoritative final state + honest bounded-stage telemetry.
-- No trading rules or evidence rows are modified.

create table if not exists public.bounded_research_cycles (
  cycle_id uuid primary key,
  worker_pid integer not null,
  started_at timestamptz not null,
  finished_at timestamptz,
  outcome text not null default 'running',
  stages_total integer not null default 0,
  stages_progressed integer not null default 0,
  stages_no_op integer not null default 0,
  stages_completed integer not null default 0,
  stages_failed integer not null default 0,
  elapsed_ms double precision,
  result_summary jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  constraint bounded_research_cycles_outcome_check check (
    outcome in (
      'running',
      'completed_with_progress',
      'completed_without_measured_progress',
      'completed_no_op',
      'failed'
    )
  )
);

create table if not exists public.bounded_research_stage_runs (
  id bigserial primary key,
  cycle_id uuid not null references public.bounded_research_cycles(cycle_id) on delete restrict,
  stage_name text not null,
  ordinal integer not null,
  outcome text not null,
  operation_ok boolean not null,
  started_at timestamptz not null,
  finished_at timestamptz not null,
  elapsed_ms double precision not null,
  cpu_user_ms double precision,
  cpu_system_ms double precision,
  process_max_rss_mb double precision,
  result_summary jsonb not null default '{}'::jsonb,
  error text,
  created_at timestamptz not null default now(),
  constraint bounded_research_stage_runs_outcome_check check (
    outcome in ('progressed','no_op','completed','failed')
  ),
  unique (cycle_id, stage_name)
);

create index if not exists idx_bounded_research_cycles_started
  on public.bounded_research_cycles (started_at desc);
create index if not exists idx_bounded_research_stage_runs_cycle_ordinal
  on public.bounded_research_stage_runs (cycle_id, ordinal);

alter table public.bounded_research_cycles enable row level security;
alter table public.bounded_research_stage_runs enable row level security;

revoke all on table public.bounded_research_cycles from public, anon, authenticated;
revoke all on table public.bounded_research_stage_runs from public, anon, authenticated;
revoke all on sequence public.bounded_research_stage_runs_id_seq from public, anon, authenticated;

grant select, insert, update on table public.bounded_research_cycles to service_role;
grant select, insert on table public.bounded_research_stage_runs to service_role;
grant usage, select on sequence public.bounded_research_stage_runs_id_seq to service_role;

comment on table public.bounded_research_cycles is
'Fix 8 process-level telemetry for each disposable Evolution research cycle. No-op work is not labelled successful progress.';
comment on table public.bounded_research_stage_runs is
'Fix 8 stage-level telemetry: outcome, elapsed time, CPU deltas, process peak RSS and bounded result summary.';
