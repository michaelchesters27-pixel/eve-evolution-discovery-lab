-- Fix 5 hotfix: legacy uniqueness must not block a new prospective cohort
-- from observing the same semantic episode under a changed policy/scorer.
drop index if exists public.uq_live_trader_v2_family_episode;

create unique index if not exists uq_live_trader_v2_family_episode_legacy
  on public.live_trader_opinions (learning_version, setup_family, episode_key)
  where independent_sample = true
    and cohort_id is null
    and setup_family is not null
    and episode_key is not null;

-- Current identified evidence is protected separately by
-- uq_live_trader_opinions_current_cohort_episode, whose key includes cohort_id.
