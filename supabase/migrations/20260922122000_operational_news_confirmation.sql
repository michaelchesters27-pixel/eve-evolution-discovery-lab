-- Audit remediation Fix 9: operational, fail-closed weekly news confirmation.
-- A weekly confirmation is valid only for the exact enabled event inventory that
-- was explicitly checked. Any later event add/remove/change makes it stale.

alter table public.live_trader_news_weeks
  add column if not exists confirmation_version text,
  add column if not exists confirmation_method text,
  add column if not exists calendar_checked_at timestamptz,
  add column if not exists confirmed_event_count integer,
  add column if not exists confirmed_event_digest text,
  add column if not exists confirmed_event_ids jsonb,
  add column if not exists source_reference text,
  add column if not exists confirmation_note text,
  add column if not exists confirmation_details jsonb;

comment on column public.live_trader_news_weeks.confirmed_event_digest is
'Hash of the exact enabled Sunday-Saturday news inventory explicitly checked at confirmation time. A mismatch invalidates the confirmation.';
comment on column public.live_trader_news_weeks.confirmation_method is
'Fix 9 requires explicit operator attestation. No automatic confirmation is permitted.';
