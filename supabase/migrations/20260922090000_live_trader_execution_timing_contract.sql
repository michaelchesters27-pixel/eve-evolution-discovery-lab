-- Audit remediation Fix 3: separate market observation/receipt, decision,
-- publication confirmation and activation.  Existing rows remain untouched.

alter table public.live_trader_opinions
  add column if not exists market_observed_at timestamptz,
  add column if not exists market_received_at timestamptz,
  add column if not exists decision_at timestamptz,
  add column if not exists publication_requested_at timestamptz,
  add column if not exists publication_confirmed_at timestamptz,
  add column if not exists activation_at timestamptz,
  add column if not exists execution_start_at timestamptz,
  add column if not exists timing_contract_version text;

alter table public.live_trader_campaigns
  add column if not exists market_observed_at timestamptz,
  add column if not exists market_received_at timestamptz,
  add column if not exists decision_at timestamptz,
  add column if not exists publication_requested_at timestamptz,
  add column if not exists publication_confirmed_at timestamptz,
  add column if not exists activation_at timestamptz,
  add column if not exists timing_contract_version text;

create index if not exists idx_live_trader_opinions_activation
  on public.live_trader_opinions (learning_version, status, activation_at);

create index if not exists idx_live_trader_campaigns_activation
  on public.live_trader_campaigns (symbol, activation_at desc);

comment on column public.live_trader_opinions.activation_at is
'First instant at which a persisted forward research decision is allowed to begin accumulating executable outcome evidence.';
comment on column public.live_trader_opinions.execution_start_at is
'First full M1 candle boundary after activation; pre-activation and partial activation-minute price action is excluded from causal replay.';
comment on column public.live_trader_campaigns.activation_at is
'First instant at which a successfully persisted published paper campaign may react to live price events.';
