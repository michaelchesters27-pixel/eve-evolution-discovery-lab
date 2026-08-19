-- EVE every-M5 multi-timeframe observation fabric.
-- Additive only. Existing 15-minute source_snapshots remain untouched while
-- the six-year M5 foundation is built and audited.

create table if not exists public.m5_research_snapshots (
    like public.source_snapshots including defaults
);

alter table public.m5_research_snapshots
    alter column snapshot_interval set default '5min';

alter table public.m5_research_snapshots
    add column if not exists context_m30_return_pct double precision,
    add column if not exists mtf_context jsonb not null default '{}'::jsonb,
    add column if not exists fabric_version text,
    add column if not exists built_at timestamptz not null default now();

create unique index if not exists uq_m5_research_snapshots_identity
    on public.m5_research_snapshots (symbol, snapshot_interval, source_interval, candle_time);

create index if not exists idx_m5_research_snapshots_symbol_time
    on public.m5_research_snapshots (symbol, candle_time);

create index if not exists idx_m5_research_snapshots_complete_time
    on public.m5_research_snapshots (outcome_complete, candle_time);

create table if not exists public.fabric_build_state (
    symbol text primary key,
    fabric_version text not null,
    status text not null default 'queued'
        check (status in ('queued', 'building', 'caught_up', 'error')),
    cursor_time timestamptz,
    source_from timestamptz,
    source_to timestamptz,
    rows_written bigint not null default 0,
    complete_rows bigint not null default 0,
    m1_available_rows bigint not null default 0,
    last_batch_rows integer not null default 0,
    last_error text,
    started_at timestamptz,
    updated_at timestamptz not null default now()
);

-- Backend-only research state.
alter table public.m5_research_snapshots enable row level security;
alter table public.fabric_build_state enable row level security;
revoke all on table public.m5_research_snapshots from anon, authenticated;
revoke all on table public.fabric_build_state from anon, authenticated;
grant select, insert, update, delete on table public.m5_research_snapshots to service_role;
grant select, insert, update, delete on table public.fabric_build_state to service_role;

comment on table public.m5_research_snapshots is
    'Every completed XAU/USD M5 research state with causal M1/M15/M30/H1/H4/D1 context and forward labels. Built inside isolated Discovery Lab.';
comment on table public.fabric_build_state is
    'Progress and health for the isolated every-M5 multi-timeframe research foundation builder.';
