alter table public.live_trader_news_events
  drop constraint if exists live_trader_news_currency_check;

alter table public.live_trader_news_events
  add constraint live_trader_news_currency_check
  check (currency in ('USD', 'ALL'));

alter table public.live_trader_news_events
  drop constraint if exists live_trader_news_class_check;

alter table public.live_trader_news_events
  add constraint live_trader_news_class_check
  check (event_class in ('high', 'major', 'all_day'));

comment on table public.live_trader_news_events is
  'Manual Forex Factory high-impact calendar for EVE Live Trader: timed USD RED events plus explicitly entered ALL-day/tentative macro-risk events relevant to XAU/USD.';
