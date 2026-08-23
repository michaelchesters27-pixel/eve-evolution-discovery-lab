create table if not exists public.live_trader_news_weeks (
  week_key text primary key,
  symbol text not null default 'XAU/USD',
  week_start date not null,
  source text not null default 'Forex Factory manual',
  source_timezone text not null default 'Europe/London',
  confirmed_at timestamptz not null default now(),
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  unique (symbol, week_start)
);

create index if not exists live_trader_news_weeks_symbol_start_idx
  on public.live_trader_news_weeks (symbol, week_start desc);

alter table public.live_trader_news_weeks enable row level security;
revoke all on table public.live_trader_news_weeks from anon, authenticated;
grant select, insert, update, delete on table public.live_trader_news_weeks to service_role;

comment on table public.live_trader_news_weeks is
  'Explicit operator confirmation that the Sunday-Saturday Forex Factory USD RED calendar was checked for EVE Live Trader.';
