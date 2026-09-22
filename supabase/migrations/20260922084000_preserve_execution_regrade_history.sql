-- Preserve the pre-correction execution evidence whenever a new scorer version
-- rewrites a historical learning row.  This gives the audit trail an immutable
-- before/after record instead of silently replacing prior scores.

create table if not exists public.live_trader_execution_regrade_audit (
  id bigint generated always as identity primary key,
  historical_episode_key text not null,
  symbol text not null,
  observed_at timestamptz,
  previous_regrader_version text,
  new_regrader_version text not null,
  previous_execution_schema text,
  new_execution_schema text,
  previous_trade_outcome text,
  previous_realised_r double precision,
  previous_learning_success boolean,
  previous_challenger_results jsonb,
  previous_best_challenger text,
  new_trade_outcome text,
  new_realised_r double precision,
  new_learning_success boolean,
  new_challenger_results jsonb,
  new_best_challenger text,
  archived_at timestamptz not null default now(),
  unique (historical_episode_key, new_regrader_version)
);

alter table public.live_trader_execution_regrade_audit enable row level security;
revoke all privileges on table public.live_trader_execution_regrade_audit from public, anon, authenticated;
grant all privileges on table public.live_trader_execution_regrade_audit to service_role;
grant usage, select on sequence public.live_trader_execution_regrade_audit_id_seq to service_role;

create or replace function public.archive_live_trader_execution_regrade()
returns trigger
language plpgsql
set search_path = public
as $$
declare
  v_previous_version text;
  v_new_version text;
  v_previous_schema text;
  v_new_schema text;
begin
  v_previous_version := old.market_state #>> '{execution_regrade,version}';
  v_new_version := new.market_state #>> '{execution_regrade,version}';
  v_previous_schema := old.market_state #>> '{execution_regrade,execution_schema}';
  v_new_schema := new.market_state #>> '{execution_regrade,execution_schema}';

  if v_new_version is null or v_new_version is not distinct from v_previous_version then
    return new;
  end if;

  insert into public.live_trader_execution_regrade_audit (
    historical_episode_key,
    symbol,
    observed_at,
    previous_regrader_version,
    new_regrader_version,
    previous_execution_schema,
    new_execution_schema,
    previous_trade_outcome,
    previous_realised_r,
    previous_learning_success,
    previous_challenger_results,
    previous_best_challenger,
    new_trade_outcome,
    new_realised_r,
    new_learning_success,
    new_challenger_results,
    new_best_challenger
  ) values (
    old.historical_episode_key,
    old.symbol,
    old.observed_at,
    v_previous_version,
    v_new_version,
    v_previous_schema,
    v_new_schema,
    old.trade_outcome,
    old.realised_r,
    old.learning_success,
    old.challenger_results,
    old.best_challenger,
    new.trade_outcome,
    new.realised_r,
    new.learning_success,
    new.challenger_results,
    new.best_challenger
  )
  on conflict (historical_episode_key, new_regrader_version) do nothing;

  return new;
end;
$$;

revoke all on function public.archive_live_trader_execution_regrade() from public, anon, authenticated;
grant execute on function public.archive_live_trader_execution_regrade() to service_role;

drop trigger if exists trg_archive_live_trader_execution_regrade
  on public.live_trader_historical_learning;

create trigger trg_archive_live_trader_execution_regrade
before update of trade_outcome, realised_r, learning_success, challenger_results, best_challenger, market_state
on public.live_trader_historical_learning
for each row
execute function public.archive_live_trader_execution_regrade();

create index if not exists idx_live_trader_execution_regrade_audit_version
  on public.live_trader_execution_regrade_audit (new_regrader_version, archived_at desc);

comment on table public.live_trader_execution_regrade_audit is
'Append-only audit trail of historical execution-score rewrites. Stores the prior and corrected result for each scorer version; direct browser-role access is disabled.';
