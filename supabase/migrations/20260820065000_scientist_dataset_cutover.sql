-- Persist which research dataset Scientist v2 is allowed to use.
-- Initial activation requires the full every-M5 audit to pass. After activation,
-- hard integrity failures can suspend the fabric without silently changing rules.

create table if not exists public.scientist_dataset_state (
    scientist_version text primary key,
    active_dataset text not null default 'legacy_15m'
        check (active_dataset in ('legacy_15m','every_m5_fabric')),
    status text not null default 'pending_cutover'
        check (status in ('pending_cutover','active','suspended_integrity')),
    fabric_version text,
    cutover_at timestamptz,
    last_verified_at timestamptz,
    audit_snapshot jsonb not null default '{}'::jsonb,
    updated_at timestamptz not null default now()
);

alter table public.scientist_dataset_state enable row level security;
revoke all on table public.scientist_dataset_state from anon, authenticated;
grant select, insert, update, delete on table public.scientist_dataset_state to service_role;

comment on table public.scientist_dataset_state is
'Persistent dataset authority for EVE Scientist. every_m5_fabric can activate only after the hard fabric audit passes.';
