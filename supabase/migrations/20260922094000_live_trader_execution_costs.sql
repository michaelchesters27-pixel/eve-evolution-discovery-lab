-- Audit remediation Fix 4: preserve theoretical gross R and add explicit,
-- broker-stress estimated net R.  Existing rows are never rewritten by this
-- migration; runtime/regrade workers populate the new fields prospectively.

alter table public.live_trader_opinions
  add column if not exists gross_realised_r double precision,
  add column if not exists estimated_cost_r double precision,
  add column if not exists net_realised_r double precision,
  add column if not exists net_learning_success boolean,
  add column if not exists cost_model_version text,
  add column if not exists execution_costs jsonb;

alter table public.live_trader_historical_learning
  add column if not exists gross_realised_r double precision,
  add column if not exists estimated_cost_r double precision,
  add column if not exists net_realised_r double precision,
  add column if not exists net_learning_success boolean,
  add column if not exists cost_model_version text,
  add column if not exists execution_costs jsonb;

alter table public.live_trader_trade_reviews
  add column if not exists gross_realised_r numeric,
  add column if not exists estimated_cost_r numeric,
  add column if not exists net_realised_r numeric,
  add column if not exists cost_model_version text,
  add column if not exists execution_costs jsonb;

alter table public.live_trader_campaigns
  add column if not exists cost_model_version text,
  add column if not exists execution_cost_model jsonb,
  add column if not exists manual_delay_seconds integer,
  add column if not exists activation_price double precision,
  add column if not exists gross_realised_r double precision,
  add column if not exists estimated_cost_r double precision,
  add column if not exists net_realised_r double precision,
  add column if not exists execution_costs jsonb;

create index if not exists idx_live_trader_opinions_cost_verified
  on public.live_trader_opinions (learning_version, cost_model_version, status, observed_at);

create index if not exists idx_live_trader_historical_cost_verified
  on public.live_trader_historical_learning (cost_model_version, observed_at);

create table if not exists public.live_trader_manual_fills (
  id uuid primary key default gen_random_uuid(),
  campaign_id text not null references public.live_trader_campaigns(id) on delete restrict,
  symbol text not null default 'XAU/USD',
  side text not null,
  order_type text,
  requested_entry double precision,
  actual_entry double precision not null,
  actual_exit double precision,
  published_at timestamptz,
  order_sent_at timestamptz,
  filled_at timestamptz not null,
  exited_at timestamptz,
  spread_price double precision,
  entry_slippage_price double precision,
  exit_slippage_price double precision,
  commission_cash numeric,
  lot_size double precision,
  contract_size double precision,
  gross_realised_r double precision,
  net_realised_r double precision,
  source text not null default 'manual_mt5_report',
  notes text,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

alter table public.live_trader_manual_fills enable row level security;
revoke all privileges on table public.live_trader_manual_fills from public, anon, authenticated;
grant all privileges on table public.live_trader_manual_fills to service_role;

create unique index if not exists uq_live_trader_manual_fills_campaign_fill
  on public.live_trader_manual_fills (campaign_id, filled_at);

comment on table public.live_trader_manual_fills is
'Separate ledger for actual user-reported MT5 fills. Stress-estimated paper costs never masquerade as actual fills.';
comment on column public.live_trader_opinions.net_realised_r is
'Cost-stress adjusted R; theoretical realised_r/gross_realised_r remains separately preserved.';
comment on column public.live_trader_historical_learning.net_realised_r is
'Versioned cost-stress adjusted historical R, normalized by the original planned entry-stop risk.';
