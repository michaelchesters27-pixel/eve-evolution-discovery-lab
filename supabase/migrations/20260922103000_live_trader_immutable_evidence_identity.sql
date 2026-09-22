-- Audit remediation Fix 5: immutable policy/scorer/cohort identities.
-- Existing evidence is preserved as legacy/unattributed. New prospective evidence
-- is required to carry a registered immutable identity.

create table if not exists public.live_trader_policy_registry (
  policy_id text primary key,
  identity_version text not null,
  policy_kind text not null,
  policy_key text not null,
  definition_hash text not null,
  definition jsonb not null,
  created_at timestamptz not null default now()
);

create table if not exists public.live_trader_scorer_registry (
  scorer_id text primary key,
  identity_version text not null,
  definition_hash text not null,
  definition jsonb not null,
  created_at timestamptz not null default now()
);

create table if not exists public.live_trader_evaluation_cohorts (
  cohort_id text primary key,
  identity_version text not null,
  cohort_protocol_version text not null,
  policy_id text not null references public.live_trader_policy_registry(policy_id) on delete restrict,
  scorer_id text not null references public.live_trader_scorer_registry(scorer_id) on delete restrict,
  learning_version text not null,
  evaluation_stage text not null,
  definition_hash text not null,
  definition jsonb not null,
  started_at timestamptz not null default now(),
  created_at timestamptz not null default now()
);

create unique index if not exists uq_live_trader_policy_registry_definition
  on public.live_trader_policy_registry (definition_hash);
create unique index if not exists uq_live_trader_scorer_registry_definition
  on public.live_trader_scorer_registry (definition_hash);
create index if not exists idx_live_trader_cohort_policy_scorer
  on public.live_trader_evaluation_cohorts (policy_id, scorer_id, evaluation_stage, started_at);

create or replace function public.reject_live_trader_identity_mutation()
returns trigger
language plpgsql
set search_path = public
as $$
begin
  raise exception 'Live Trader evidence identity registries are immutable; create a new identity/cohort instead';
end;
$$;

drop trigger if exists trg_live_trader_policy_registry_immutable on public.live_trader_policy_registry;
create trigger trg_live_trader_policy_registry_immutable
before update or delete on public.live_trader_policy_registry
for each row execute function public.reject_live_trader_identity_mutation();

drop trigger if exists trg_live_trader_scorer_registry_immutable on public.live_trader_scorer_registry;
create trigger trg_live_trader_scorer_registry_immutable
before update or delete on public.live_trader_scorer_registry
for each row execute function public.reject_live_trader_identity_mutation();

drop trigger if exists trg_live_trader_evaluation_cohorts_immutable on public.live_trader_evaluation_cohorts;
create trigger trg_live_trader_evaluation_cohorts_immutable
before update or delete on public.live_trader_evaluation_cohorts
for each row execute function public.reject_live_trader_identity_mutation();

alter table public.live_trader_policy_registry enable row level security;
alter table public.live_trader_scorer_registry enable row level security;
alter table public.live_trader_evaluation_cohorts enable row level security;

revoke all on table public.live_trader_policy_registry from public, anon, authenticated;
revoke all on table public.live_trader_scorer_registry from public, anon, authenticated;
revoke all on table public.live_trader_evaluation_cohorts from public, anon, authenticated;
grant select on table public.live_trader_policy_registry to service_role;
grant select on table public.live_trader_scorer_registry to service_role;
grant select on table public.live_trader_evaluation_cohorts to service_role;

alter table public.live_trader_opinions
  add column if not exists evidence_identity_version text,
  add column if not exists policy_id text references public.live_trader_policy_registry(policy_id) on delete restrict,
  add column if not exists scorer_id text references public.live_trader_scorer_registry(scorer_id) on delete restrict,
  add column if not exists cohort_id text references public.live_trader_evaluation_cohorts(cohort_id) on delete restrict,
  add column if not exists evaluation_stage text;

alter table public.live_trader_campaigns
  add column if not exists evidence_identity_version text,
  add column if not exists policy_id text references public.live_trader_policy_registry(policy_id) on delete restrict,
  add column if not exists scorer_id text references public.live_trader_scorer_registry(scorer_id) on delete restrict,
  add column if not exists cohort_id text references public.live_trader_evaluation_cohorts(cohort_id) on delete restrict,
  add column if not exists evaluation_stage text;

alter table public.live_trader_trade_reviews
  add column if not exists evidence_identity_version text,
  add column if not exists policy_id text references public.live_trader_policy_registry(policy_id) on delete restrict,
  add column if not exists scorer_id text references public.live_trader_scorer_registry(scorer_id) on delete restrict,
  add column if not exists cohort_id text references public.live_trader_evaluation_cohorts(cohort_id) on delete restrict,
  add column if not exists evaluation_stage text;

alter table public.live_trader_historical_learning
  add column if not exists evidence_identity_version text,
  add column if not exists policy_id text references public.live_trader_policy_registry(policy_id) on delete restrict,
  add column if not exists scorer_id text references public.live_trader_scorer_registry(scorer_id) on delete restrict,
  add column if not exists cohort_id text references public.live_trader_evaluation_cohorts(cohort_id) on delete restrict,
  add column if not exists evaluation_stage text;

alter table public.live_trader_manual_fills
  add column if not exists evidence_identity_version text,
  add column if not exists policy_id text references public.live_trader_policy_registry(policy_id) on delete restrict,
  add column if not exists scorer_id text references public.live_trader_scorer_registry(scorer_id) on delete restrict,
  add column if not exists cohort_id text references public.live_trader_evaluation_cohorts(cohort_id) on delete restrict,
  add column if not exists evaluation_stage text;

create unique index if not exists uq_live_trader_opinions_current_cohort_episode
  on public.live_trader_opinions (learning_version, cohort_id, setup_family, episode_key)
  where cohort_id is not null and setup_family is not null and episode_key is not null;

create index if not exists idx_live_trader_opinions_cohort_time
  on public.live_trader_opinions (cohort_id, observed_at);
create index if not exists idx_live_trader_campaigns_cohort_time
  on public.live_trader_campaigns (cohort_id, created_at);
create index if not exists idx_live_trader_trade_reviews_cohort_time
  on public.live_trader_trade_reviews (cohort_id, completed_at);
create index if not exists idx_live_trader_historical_cohort_time
  on public.live_trader_historical_learning (cohort_id, observed_at);

create or replace function public.register_live_trader_evidence_identity(
  p_identity_version text,
  p_policy_id text,
  p_policy_kind text,
  p_policy_key text,
  p_policy_definition_hash text,
  p_policy_definition jsonb,
  p_scorer_id text,
  p_scorer_definition_hash text,
  p_scorer_definition jsonb,
  p_cohort_id text,
  p_cohort_definition_hash text,
  p_cohort_definition jsonb,
  p_cohort_protocol_version text,
  p_learning_version text,
  p_evaluation_stage text
)
returns jsonb
language plpgsql
security definer
set search_path = public
as $$
declare
  v_policy_hash text;
  v_policy_definition jsonb;
  v_scorer_hash text;
  v_scorer_definition jsonb;
  v_cohort_hash text;
  v_cohort_definition jsonb;
begin
  if coalesce(p_policy_id,'') = '' or coalesce(p_scorer_id,'') = '' or coalesce(p_cohort_id,'') = '' then
    raise exception 'policy_id, scorer_id and cohort_id are required';
  end if;

  insert into public.live_trader_policy_registry (
    policy_id, identity_version, policy_kind, policy_key, definition_hash, definition
  ) values (
    p_policy_id, p_identity_version, p_policy_kind, p_policy_key, p_policy_definition_hash, p_policy_definition
  ) on conflict (policy_id) do nothing;

  select definition_hash, definition into v_policy_hash, v_policy_definition
  from public.live_trader_policy_registry where policy_id = p_policy_id;
  if v_policy_hash is distinct from p_policy_definition_hash or v_policy_definition is distinct from p_policy_definition then
    raise exception 'policy identity collision or attempted policy mutation for %', p_policy_id;
  end if;

  insert into public.live_trader_scorer_registry (
    scorer_id, identity_version, definition_hash, definition
  ) values (
    p_scorer_id, p_identity_version, p_scorer_definition_hash, p_scorer_definition
  ) on conflict (scorer_id) do nothing;

  select definition_hash, definition into v_scorer_hash, v_scorer_definition
  from public.live_trader_scorer_registry where scorer_id = p_scorer_id;
  if v_scorer_hash is distinct from p_scorer_definition_hash or v_scorer_definition is distinct from p_scorer_definition then
    raise exception 'scorer identity collision or attempted scorer mutation for %', p_scorer_id;
  end if;

  insert into public.live_trader_evaluation_cohorts (
    cohort_id, identity_version, cohort_protocol_version, policy_id, scorer_id,
    learning_version, evaluation_stage, definition_hash, definition
  ) values (
    p_cohort_id, p_identity_version, p_cohort_protocol_version, p_policy_id, p_scorer_id,
    p_learning_version, p_evaluation_stage, p_cohort_definition_hash, p_cohort_definition
  ) on conflict (cohort_id) do nothing;

  select definition_hash, definition into v_cohort_hash, v_cohort_definition
  from public.live_trader_evaluation_cohorts where cohort_id = p_cohort_id;
  if v_cohort_hash is distinct from p_cohort_definition_hash or v_cohort_definition is distinct from p_cohort_definition then
    raise exception 'cohort identity collision or attempted cohort mutation for %', p_cohort_id;
  end if;

  return jsonb_build_object(
    'identity_version', p_identity_version,
    'policy_id', p_policy_id,
    'scorer_id', p_scorer_id,
    'cohort_id', p_cohort_id,
    'registered', true
  );
end;
$$;

revoke all on function public.register_live_trader_evidence_identity(
  text,text,text,text,text,jsonb,text,text,jsonb,text,text,jsonb,text,text,text
) from public, anon, authenticated;
grant execute on function public.register_live_trader_evidence_identity(
  text,text,text,text,text,jsonb,text,text,jsonb,text,text,jsonb,text,text,text
) to service_role;

comment on table public.live_trader_policy_registry is
'Immutable content-addressed Live Trader policy definitions. A policy change creates a new policy_id.';
comment on table public.live_trader_scorer_registry is
'Immutable content-addressed execution/scoring contracts including timing and cost assumptions.';
comment on table public.live_trader_evaluation_cohorts is
'Immutable prospective evidence cohorts. A policy or scorer change necessarily creates a new cohort_id.';
