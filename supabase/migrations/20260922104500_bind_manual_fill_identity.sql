create or replace function public.bind_live_trader_manual_fill_identity()
returns trigger
language plpgsql
security definer
set search_path = public
as $$
declare
  v_campaign public.live_trader_campaigns%rowtype;
begin
  select * into v_campaign
  from public.live_trader_campaigns
  where id = new.campaign_id;

  if not found then
    raise exception 'Unknown Live Trader campaign_id %', new.campaign_id;
  end if;

  new.evidence_identity_version := v_campaign.evidence_identity_version;
  new.policy_id := v_campaign.policy_id;
  new.scorer_id := v_campaign.scorer_id;
  new.cohort_id := v_campaign.cohort_id;
  new.evaluation_stage := case
    when v_campaign.cohort_id is null then 'legacy_manual_fill_unattributed'
    else 'actual_manual_fill'
  end;
  return new;
end;
$$;

drop trigger if exists trg_bind_live_trader_manual_fill_identity on public.live_trader_manual_fills;
create trigger trg_bind_live_trader_manual_fill_identity
before insert or update of campaign_id, policy_id, scorer_id, cohort_id, evidence_identity_version, evaluation_stage
on public.live_trader_manual_fills
for each row execute function public.bind_live_trader_manual_fill_identity();

revoke all on function public.bind_live_trader_manual_fill_identity() from public, anon, authenticated;
grant execute on function public.bind_live_trader_manual_fill_identity() to service_role;

comment on function public.bind_live_trader_manual_fill_identity() is
'Forces every actual/manual fill record to inherit the immutable evidence identity of its campaign; caller-supplied cohort labels cannot override it.';
