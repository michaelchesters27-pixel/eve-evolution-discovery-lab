alter table if exists public.live_trader_opinions
    add column if not exists setup_family text,
    add column if not exists episode_key text,
    add column if not exists learning_version text not null default 'eve-live-learning-v1',
    add column if not exists independent_sample boolean not null default false,
    add column if not exists learning_success boolean,
    add column if not exists score_threshold_pct double precision,
    add column if not exists entry_triggered boolean,
    add column if not exists trade_outcome text,
    add column if not exists realised_r double precision;

-- Preserve all v1 observations for audit, but stop unresolved v1 rows from being
-- mistaken for evidence in the independent v2 learner.
update public.live_trader_opinions
set status = 'legacy_archived'
where learning_version = 'eve-live-learning-v1'
  and status = 'open';

create index if not exists idx_live_trader_opinions_learning_family
    on public.live_trader_opinions (learning_version, setup_family, status, observed_at desc);

create index if not exists idx_live_trader_opinions_episode
    on public.live_trader_opinions (learning_version, episode_key, observed_at desc);

create unique index if not exists uq_live_trader_v2_family_episode
    on public.live_trader_opinions (learning_version, setup_family, episode_key)
    where independent_sample = true
      and setup_family is not null
      and episode_key is not null;

comment on column public.live_trader_opinions.setup_family is
    'Generalised Live Trader market-condition family. It deliberately excludes exact zone IDs so learning can transfer across days.';
comment on column public.live_trader_opinions.episode_key is
    'Market-episode identity used to prevent repeated snapshots of the same move from inflating sample counts.';
comment on column public.live_trader_opinions.learning_success is
    'Decision-learning outcome. Actionable trade ideas use execution outcome; no-trade opinions use directional outcome.';
