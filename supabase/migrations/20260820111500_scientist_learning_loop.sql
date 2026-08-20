-- EVE Scientist learning loop v1
-- Selection-stage results may teach future research. Confirmation/final holdout never enter this ledger.

create table if not exists public.scientist_learning_events (
    candidate_key text primary key,
    scientist_version text not null,
    research_dataset text not null,
    result_status text not null,
    contribution double precision not null default 0,
    validation_pf double precision not null default 0,
    validation_expectancy_r double precision not null default 0,
    validation_trades integer not null default 0,
    fitness_score double precision not null default 0,
    failed_gates jsonb not null default '[]'::jsonb,
    feature_keys jsonb not null default '[]'::jsonb,
    learned_at timestamptz not null default now(),
    updated_at timestamptz not null default now()
);

create index if not exists idx_scientist_learning_events_version_dataset
    on public.scientist_learning_events (scientist_version, research_dataset, learned_at desc);

alter table public.scientist_learning_events enable row level security;
revoke all on table public.scientist_learning_events from anon, authenticated;
grant select, insert, update, delete on table public.scientist_learning_events to service_role;

comment on table public.scientist_learning_events is
    'Idempotent selection-stage learning ledger for EVE Scientist. Only completed selection validation may teach; sealed confirmation/final holdout are forbidden.';
