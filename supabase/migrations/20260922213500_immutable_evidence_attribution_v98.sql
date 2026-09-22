-- Final acceptance remediation Fix 5.
-- Enforce that every attributed evidence row is bound immutably to the exact
-- policy/scorer/stage tuple registered by its cohort. Legacy rows stay legacy.


alter table public.live_trader_evaluation_cohorts
  drop constraint if exists uq_live_trader_cohort_binding_v98;
alter table public.live_trader_evaluation_cohorts
  add constraint uq_live_trader_cohort_binding_v98
  unique (cohort_id, policy_id, scorer_id, evaluation_stage, identity_version);

alter table public.live_trader_opinions
  drop constraint if exists fk_live_trader_opinions_identity_tuple_v98;
alter table public.live_trader_opinions
  add constraint fk_live_trader_opinions_identity_tuple_v98
  foreign key (cohort_id, policy_id, scorer_id, evaluation_stage, evidence_identity_version)
  references public.live_trader_evaluation_cohorts
    (cohort_id, policy_id, scorer_id, evaluation_stage, identity_version)
  on delete restrict;

alter table public.live_trader_campaigns
  drop constraint if exists fk_live_trader_campaigns_identity_tuple_v98;
alter table public.live_trader_campaigns
  add constraint fk_live_trader_campaigns_identity_tuple_v98
  foreign key (cohort_id, policy_id, scorer_id, evaluation_stage, evidence_identity_version)
  references public.live_trader_evaluation_cohorts
    (cohort_id, policy_id, scorer_id, evaluation_stage, identity_version)
  on delete restrict;

alter table public.live_trader_trade_reviews
  drop constraint if exists fk_live_trader_trade_reviews_identity_tuple_v98;
alter table public.live_trader_trade_reviews
  add constraint fk_live_trader_trade_reviews_identity_tuple_v98
  foreign key (cohort_id, policy_id, scorer_id, evaluation_stage, evidence_identity_version)
  references public.live_trader_evaluation_cohorts
    (cohort_id, policy_id, scorer_id, evaluation_stage, identity_version)
  on delete restrict;

alter table public.live_trader_historical_learning
  drop constraint if exists fk_live_trader_historical_identity_tuple_v98;
alter table public.live_trader_historical_learning
  add constraint fk_live_trader_historical_identity_tuple_v98
  foreign key (cohort_id, policy_id, scorer_id, evaluation_stage, evidence_identity_version)
  references public.live_trader_evaluation_cohorts
    (cohort_id, policy_id, scorer_id, evaluation_stage, identity_version)
  on delete restrict;

alter table public.live_trader_evaluation_cohorts
  drop constraint if exists uq_live_trader_cohort_manual_binding_v98;
alter table public.live_trader_evaluation_cohorts
  add constraint uq_live_trader_cohort_manual_binding_v98
  unique (cohort_id, policy_id, scorer_id, identity_version);

alter table public.live_trader_manual_fills
  drop constraint if exists fk_live_trader_manual_fills_identity_tuple_v98;
alter table public.live_trader_manual_fills
  drop constraint if exists fk_live_trader_manual_fills_campaign_tuple_v98;
alter table public.live_trader_manual_fills
  add constraint fk_live_trader_manual_fills_campaign_tuple_v98
  foreign key (cohort_id, policy_id, scorer_id, evidence_identity_version)
  references public.live_trader_evaluation_cohorts
    (cohort_id, policy_id, scorer_id, identity_version)
  on delete restrict;

alter table public.live_trader_zone_retrace_current_policy_opportunities
  drop constraint if exists fk_live_trader_current_opps_identity_tuple_v98;
alter table public.live_trader_zone_retrace_current_policy_opportunities
  add constraint fk_live_trader_current_opps_identity_tuple_v98
  foreign key (cohort_id, policy_id, scorer_id, evaluation_stage, evidence_identity_version)
  references public.live_trader_evaluation_cohorts
    (cohort_id, policy_id, scorer_id, evaluation_stage, identity_version)
  on delete restrict;

alter table public.live_trader_zone_retrace_current_policy_cohort_state
  drop constraint if exists fk_live_trader_current_state_identity_tuple_v98;
alter table public.live_trader_zone_retrace_current_policy_cohort_state
  add constraint fk_live_trader_current_state_identity_tuple_v98
  foreign key (cohort_id, policy_id, scorer_id, evaluation_stage, evidence_identity_version)
  references public.live_trader_evaluation_cohorts
    (cohort_id, policy_id, scorer_id, evaluation_stage, identity_version)
  on delete restrict;

create or replace function public.guard_live_trader_evidence_attribution_v98()
returns trigger
language plpgsql
set search_path = public
as $$
declare
  v_new jsonb := to_jsonb(new);
  v_old jsonb := case when tg_op = 'UPDATE' then to_jsonb(old) else '{}'::jsonb end;
  v_all_null boolean;
  v_all_bound boolean;
  v_cohort public.live_trader_evaluation_cohorts%rowtype;
  v_old_all_null boolean := true;
begin
  v_all_null := new.policy_id is null and new.scorer_id is null and new.cohort_id is null;
  v_all_bound := new.policy_id is not null and new.scorer_id is not null and new.cohort_id is not null;

  if not (v_all_null or v_all_bound) then
    raise exception 'Live Trader evidence identity must be fully legacy or fully attributed';
  end if;

  if tg_op = 'UPDATE' then
    v_old_all_null := old.policy_id is null and old.scorer_id is null and old.cohort_id is null;

    if v_old_all_null and not v_all_null then
      raise exception 'Legacy Live Trader evidence cannot be retrospectively rebound to a prospective cohort';
    end if;

    if not v_old_all_null then
      if new.policy_id is distinct from old.policy_id
         or new.scorer_id is distinct from old.scorer_id
         or new.cohort_id is distinct from old.cohort_id
         or new.evaluation_stage is distinct from old.evaluation_stage
         or new.evidence_identity_version is distinct from old.evidence_identity_version
         or (
           (v_new ? 'learning_version') and
           (v_old ? 'learning_version') and
           (v_new->>'learning_version') is distinct from (v_old->>'learning_version')
         )
      then
        raise exception 'Attributed Live Trader evidence identity is immutable';
      end if;
    end if;
  end if;

  if v_all_null then
    return new;
  end if;

  select *
    into v_cohort
  from public.live_trader_evaluation_cohorts
  where cohort_id = new.cohort_id;

  if not found then
    raise exception 'Unknown Live Trader evidence cohort %', new.cohort_id;
  end if;

  if new.policy_id is distinct from v_cohort.policy_id
     or new.scorer_id is distinct from v_cohort.scorer_id
  then
    raise exception 'Live Trader evidence policy/scorer tuple does not match cohort %', new.cohort_id;
  end if;

  if tg_table_name = 'live_trader_manual_fills' then
    if new.evaluation_stage is distinct from 'actual_manual_fill' then
      raise exception 'Attributed manual fill must use actual_manual_fill evaluation stage';
    end if;
  elsif new.evaluation_stage is distinct from v_cohort.evaluation_stage then
    raise exception 'Live Trader evidence evaluation_stage does not match cohort %', new.cohort_id;
  end if;

  if new.evidence_identity_version is distinct from v_cohort.identity_version then
    raise exception 'Live Trader evidence identity version does not match cohort %', new.cohort_id;
  end if;

  if (v_new ? 'learning_version')
     and nullif(v_new->>'learning_version','') is not null
     and (v_new->>'learning_version') is distinct from v_cohort.learning_version
  then
    raise exception 'Live Trader evidence learning_version does not match cohort %', new.cohort_id;
  end if;

  return new;
end;
$$;

do $$
declare
  v_table text;
begin
  foreach v_table in array array[
    'live_trader_opinions',
    'live_trader_campaigns',
    'live_trader_trade_reviews',
    'live_trader_historical_learning',
    'live_trader_manual_fills',
    'live_trader_zone_retrace_current_policy_opportunities',
    'live_trader_zone_retrace_current_policy_cohort_state'
  ]
  loop
    execute format('drop trigger if exists trg_guard_evidence_attribution_v98 on public.%I', v_table);
    execute format(
      'create trigger trg_guard_evidence_attribution_v98 before insert or update on public.%I for each row execute function public.guard_live_trader_evidence_attribution_v98()',
      v_table
    );
  end loop;
end;
$$;

comment on function public.guard_live_trader_evidence_attribution_v98() is
'Fix 5: immutable evidence-to-cohort binding and exact policy/scorer/stage tuple enforcement; legacy rows cannot be retrospectively rebound.';
