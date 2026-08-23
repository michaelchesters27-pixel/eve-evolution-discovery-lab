create table if not exists public.live_trader_execution_regrade_state (
  symbol text primary key,
  version text not null,
  cursor_time timestamptz,
  rows_checked bigint not null default 0,
  rows_regraded bigint not null default 0,
  outcome_changes bigint not null default 0,
  challenger_changes bigint not null default 0,
  completed boolean not null default false,
  completed_at timestamptz,
  last_cycle_at timestamptz,
  last_error text,
  updated_at timestamptz not null default now()
);

alter table public.live_trader_execution_regrade_state enable row level security;
revoke all on table public.live_trader_execution_regrade_state from anon, authenticated;
grant select, insert, update, delete on table public.live_trader_execution_regrade_state to service_role;

comment on table public.live_trader_execution_regrade_state is
  'Persistent cursor and audit state for the v39 invalidation-aware causal execution regrade of Historical Academy evidence.';

-- The campaign ledger already had RLS with no anon/auth policies, so these broad
-- default grants were not exploitable. Revoke them anyway to enforce least privilege
-- even if an RLS policy is added in the future.
revoke all on table public.live_trader_campaigns from anon, authenticated;
grant select, insert, update, delete on table public.live_trader_campaigns to service_role;

-- Quarantine campaign follow-through and terminal UI states that were previously
-- recorded as if they were fresh independent decisions. Keep every row for audit.
update public.live_trader_opinions o
set independent_sample = false,
    market_state = jsonb_set(
      coalesce(o.market_state, '{}'::jsonb),
      '{learning_remediation_v39}',
      jsonb_build_object(
        'version','eve-live-forward-campaign-remediation-v1',
        'excluded_reason','locked_campaign_followthrough_or_terminal_state_is_not_a_new_decision',
        'remediated_at',now()
      ),
      true
    )
from public.live_trader_campaigns c
where o.symbol = c.symbol
  and o.learning_version = 'eve-live-learning-family-v1'
  and o.independent_sample = true
  and o.trade_idea->>'campaign_id' = c.id
  and (
    coalesce(o.trade_idea->>'campaign_status','') in ('won','lost','invalidated','expired')
    or (
      coalesce(o.trade_idea->>'campaign_status','') = 'active'
      and abs(extract(epoch from (o.observed_at - c.created_at))) > 120
    )
  );

-- A genuine publication decision may remain independent even if it invalidated
-- before entry, but it must not be scored as a win/loss because no capital was
-- exposed. The locked campaign ledger is authoritative for these past rows.
update public.live_trader_opinions o
set learning_success = null,
    entry_triggered = false,
    trade_outcome = 'invalidated_before_entry',
    realised_r = 0,
    market_state = jsonb_set(
      coalesce(o.market_state, '{}'::jsonb),
      '{learning_remediation_v39}',
      jsonb_build_object(
        'version','eve-live-forward-campaign-remediation-v1',
        'corrected_reason','authoritative_locked_campaign_invalidated_before_entry',
        'remediated_at',now()
      ),
      true
    )
from public.live_trader_campaigns c
where o.symbol = c.symbol
  and o.learning_version = 'eve-live-learning-family-v1'
  and o.independent_sample = true
  and o.trade_idea->>'campaign_id' = c.id
  and coalesce(o.trade_idea->>'campaign_status','') = 'pending'
  and c.status = 'invalidated'
  and c.triggered_at is null;

-- Backfill one idempotent post-trade review for every campaign that finished before
-- the v38 review writer existed. Do not invent the missing original market context.
insert into public.live_trader_trade_reviews (
  campaign_id,
  symbol,
  completed_at,
  week_start,
  outcome,
  triggered,
  realised_r,
  setup_family,
  setup_family_descriptor,
  publication_context,
  completion_context,
  review,
  review_version,
  created_at,
  updated_at
)
select
  c.id,
  c.symbol,
  c.completed_at,
  ((c.completed_at at time zone 'Europe/London')::date
     - extract(dow from c.completed_at at time zone 'Europe/London')::int),
  c.status,
  c.triggered_at is not null,
  case
    when c.status = 'lost' then -1::numeric
    when c.status = 'won' then coalesce(c.risk_reward,0)::numeric
    else 0::numeric
  end,
  nullif(c.campaign->>'setup_family',''),
  coalesce(c.campaign->'setup_family_descriptor','{}'::jsonb),
  coalesce(
    c.campaign->'outcome_learning_v38'->'publication_context',
    jsonb_build_object(
      'trade',coalesce(c.campaign->'published_trade','{}'::jsonb),
      'note','Legacy campaign completed before persistent post-trade reviews were enabled; original setup-family context was not reconstructed.'
    )
  ),
  jsonb_build_object(
    'note','Legacy terminal campaign backfilled from the authoritative locked-campaign ledger.',
    'campaign_result',c.result,
    'backfilled_at',now()
  ),
  jsonb_build_object(
    'signal',case when c.status='lost' then 'negative' when c.status='won' then 'positive' else 'neutral' end,
    'priority',case when c.status='lost' then 'high' else 'normal' end,
    'lesson',case
      when c.status='lost' then 'This published execution lost 1R. Preserve it as negative execution evidence. One loss must not rewrite EVE rules; repeated independent evidence is required before confidence or execution preference changes.'
      when c.status='won' then 'This published execution reached its target. Preserve it as positive execution evidence without treating one win as proof of an edge.'
      when c.status='invalidated' then 'The setup invalidated before entry. Preserve this as setup-selection evidence, not a trading loss, because capital was never exposed.'
      else 'The setup expired without triggering. Preserve this as opportunity/entry-selection evidence, not a trading win or loss.'
    end,
    'context_quality','legacy_partial',
    'order_type',c.order_type,
    'side',c.side,
    'risk_reward',c.risk_reward,
    'realised_r',case when c.status='lost' then -1 when c.status='won' then coalesce(c.risk_reward,0) else 0 end,
    'evidence_role','execution_postmortem_not_second_independent_sample',
    'forward_family_policy','Forward family calibration remains the authority for confidence/veto changes; this review diagnoses the exact locked-campaign result without double-counting it.'
  ),
  'eve-live-post-trade-review-v1',
  now(),
  now()
from public.live_trader_campaigns c
where c.status in ('won','lost','invalidated','expired')
  and c.completed_at is not null
on conflict (campaign_id) do nothing;
