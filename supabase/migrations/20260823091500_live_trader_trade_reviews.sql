create table if not exists public.live_trader_trade_reviews (
  campaign_id text primary key references public.live_trader_campaigns(id) on delete cascade,
  symbol text not null default 'XAU/USD',
  completed_at timestamptz not null,
  week_start date not null,
  outcome text not null,
  triggered boolean not null default false,
  realised_r numeric not null default 0,
  setup_family text,
  setup_family_descriptor jsonb not null default '{}'::jsonb,
  publication_context jsonb not null default '{}'::jsonb,
  completion_context jsonb not null default '{}'::jsonb,
  review jsonb not null default '{}'::jsonb,
  review_version text not null,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  constraint live_trader_trade_reviews_outcome_check
    check (outcome in ('won','lost','invalidated','expired'))
);

create index if not exists live_trader_trade_reviews_week_idx
  on public.live_trader_trade_reviews (symbol, week_start, completed_at desc);

create index if not exists live_trader_trade_reviews_family_idx
  on public.live_trader_trade_reviews (symbol, setup_family, completed_at desc)
  where setup_family is not null;

alter table public.live_trader_trade_reviews enable row level security;
revoke all on table public.live_trader_trade_reviews from anon, authenticated;
grant select, insert, update, delete on table public.live_trader_trade_reviews to service_role;

comment on table public.live_trader_trade_reviews is
  'One idempotent post-trade learning review per locked EVE Live Trader campaign. Campaign outcomes are execution evidence; they do not double-count as an independent second vote in the forward family governor.';
