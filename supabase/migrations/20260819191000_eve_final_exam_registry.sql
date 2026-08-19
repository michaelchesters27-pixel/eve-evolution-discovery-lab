-- EVE Scientist v2: global final-exam spending registry.
-- This is additive and belongs only in the separate Evolution Discovery Lab.

create table if not exists public.final_exam_registry (
    id uuid primary key default gen_random_uuid(),
    holdout_epoch text not null,
    lineage_id uuid,
    mutation_id uuid,
    rule_hash text not null,
    dataset_version text,
    status text not null default 'opened' check (status in ('opened', 'finished')),
    result_status text,
    m1_status text,
    frozen boolean not null default false,
    details jsonb not null default '{}'::jsonb,
    opened_at timestamptz not null default now(),
    finished_at timestamptz,
    unique (lineage_id)
);

create index if not exists idx_final_exam_registry_epoch
    on public.final_exam_registry (holdout_epoch, opened_at desc);

create index if not exists idx_final_exam_registry_rule_hash
    on public.final_exam_registry (rule_hash);

-- Count historical final-holdout openings so v2 does not pretend the budget
-- starts at zero. JSONB text is canonical enough for a durable historical key.
insert into public.final_exam_registry (
    holdout_epoch,
    lineage_id,
    mutation_id,
    rule_hash,
    dataset_version,
    status,
    result_status,
    m1_status,
    frozen,
    details,
    opened_at,
    finished_at
)
select
    to_char(ml.holdout_opened_at at time zone 'UTC', 'YYYY-MM'),
    ml.id,
    null,
    encode(digest(coalesce(ml.champion_rules, '{}'::jsonb)::text, 'sha256'), 'hex'),
    ml.dataset_version,
    'finished',
    ml.final_result_status,
    coalesce(ml.final_evidence->'m1_replay'->>'status', ml.final_evidence->>'m1_status'),
    coalesce(ml.final_result_status in ('validated','elite'), false),
    jsonb_build_object(
        'backfilled', true,
        'source', 'mutation_lineages.holdout_opened_at',
        'generation', ml.generation
    ),
    ml.holdout_opened_at,
    ml.holdout_opened_at
from public.mutation_lineages ml
where ml.holdout_opened_at is not null
on conflict (lineage_id) do nothing;

-- Internal backend research state only.
alter table public.final_exam_registry enable row level security;
revoke all on table public.final_exam_registry from anon, authenticated;
grant select, insert, update, delete on table public.final_exam_registry to service_role;

comment on table public.final_exam_registry is
    'Global accounting for every opening of confirmation/final holdout. Used to cap repeated final testing within a fresh-data epoch.';
