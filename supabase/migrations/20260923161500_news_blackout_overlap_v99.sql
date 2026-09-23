-- Final acceptance remediation Fix 9 v99.
-- Select the complete news safety inventory by blackout-window overlap rather
-- than by the event's storage/sort anchor. This keeps all-day events present
-- for their full Europe/London calendar-day blackout, including afternoons.

create or replace function public.get_live_trader_news_window_v99(
  p_symbol text,
  p_start timestamptz,
  p_end timestamptz
)
returns jsonb
language sql
stable
security invoker
set search_path = public
as $$
  with eligible as (
    select
      event_id,
      currency,
      event_name,
      scheduled_at,
      event_class,
      pre_minutes,
      post_minutes,
      source,
      case
        when event_class = 'all_day' then
          date_trunc('day', scheduled_at at time zone 'Europe/London')
            at time zone 'Europe/London'
        else
          scheduled_at - make_interval(mins => greatest(coalesce(pre_minutes, 30), 0))
      end as blackout_start,
      case
        when event_class = 'all_day' then
          (date_trunc('day', scheduled_at at time zone 'Europe/London') + interval '1 day')
            at time zone 'Europe/London'
        else
          scheduled_at + make_interval(mins => greatest(coalesce(post_minutes, 15), 0))
      end as blackout_end
    from public.live_trader_news_events
    where symbol = p_symbol
      and currency in ('USD','ALL')
      and enabled is true
  ),
  overlapping as (
    select *
    from eligible
    where blackout_end > p_start
      and blackout_start < p_end
  )
  select jsonb_build_object(
    'version', 'eve-live-news-blackout-window-v99',
    'complete', true,
    'source', 'server_side_blackout_overlap_aggregation',
    'selection', 'blackout_interval_overlap',
    'event_count', count(*)::integer,
    'events',
      coalesce(
        jsonb_agg(
          jsonb_build_object(
            'event_id', event_id,
            'currency', currency,
            'event_name', event_name,
            'scheduled_at', scheduled_at,
            'event_class', event_class,
            'pre_minutes', pre_minutes,
            'post_minutes', post_minutes,
            'source', source,
            'blackout_start', blackout_start,
            'blackout_end', blackout_end
          )
          order by scheduled_at asc, event_id asc
        ) filter (where event_id is not null),
        '[]'::jsonb
      )
  )
  from overlapping;
$$;

revoke all on function public.get_live_trader_news_window_v99(text,timestamptz,timestamptz)
  from public, anon, authenticated;
grant execute on function public.get_live_trader_news_window_v99(text,timestamptz,timestamptz)
  to service_role;

comment on function public.get_live_trader_news_window_v99(text,timestamptz,timestamptz) is
'Fix 9 v99: complete blackout inventory selected by overlap with each event blackout interval; all-day events use Europe/London local-day boundaries.';
