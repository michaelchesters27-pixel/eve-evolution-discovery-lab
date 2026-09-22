alter table public.live_trader_execution_regrade_audit
  add column if not exists previous_net_realised_r double precision,
  add column if not exists new_net_realised_r double precision,
  add column if not exists previous_cost_model_version text,
  add column if not exists new_cost_model_version text,
  add column if not exists previous_execution_costs jsonb,
  add column if not exists new_execution_costs jsonb;

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
    new_best_challenger,
    previous_net_realised_r,
    new_net_realised_r,
    previous_cost_model_version,
    new_cost_model_version,
    previous_execution_costs,
    new_execution_costs
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
    new.best_challenger,
    old.net_realised_r,
    new.net_realised_r,
    old.cost_model_version,
    new.cost_model_version,
    old.execution_costs,
    new.execution_costs
  )
  on conflict (historical_episode_key, new_regrader_version) do nothing;

  return new;
end;
$$;

revoke all on function public.archive_live_trader_execution_regrade() from public, anon, authenticated;
grant execute on function public.archive_live_trader_execution_regrade() to service_role;
