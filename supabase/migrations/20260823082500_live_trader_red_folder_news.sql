create table if not exists public.live_trader_news_events (
  event_id text primary key,
  symbol text not null default 'XAU/USD',
  currency text not null default 'USD',
  event_name text not null,
  scheduled_at timestamptz not null,
  scheduled_local text not null,
  source_timezone text not null default 'Europe/London',
  impact text not null default 'high',
  event_class text not null default 'high',
  pre_minutes integer not null default 30 check (pre_minutes between 0 and 180),
  post_minutes integer not null default 15 check (post_minutes between 0 and 180),
  source text not null default 'Forex Factory manual',
  enabled boolean not null default true,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  constraint live_trader_news_currency_check check (currency = 'USD'),
  constraint live_trader_news_impact_check check (impact = 'high'),
  constraint live_trader_news_class_check check (event_class in ('high','major'))
);

create index if not exists live_trader_news_events_symbol_time_idx
  on public.live_trader_news_events (symbol, scheduled_at)
  where enabled = true;

alter table public.live_trader_news_events enable row level security;
revoke all on table public.live_trader_news_events from anon, authenticated;
grant select, insert, update, delete on table public.live_trader_news_events to service_role;

comment on table public.live_trader_news_events is
  'Manual weekly USD high-impact economic calendar entered from Forex Factory for EVE Live Trader news-risk protection.';
