create or replace function public.get_live_trader_news_inventory_v96(
  p_symbol text,
  p_week_start timestamptz,
  p_week_end timestamptz
)
returns jsonb
language sql
stable
security invoker
set search_path = public
as $$
  select jsonb_build_object(
    'version', 'eve-live-news-inventory-v96',
    'complete', true,
    'source', 'server_side_sql_aggregation',
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
            'source', source
          )
          order by scheduled_at asc, event_id asc, event_name asc
        ) filter (where event_id is not null),
        '[]'::jsonb
      )
  )
  from public.live_trader_news_events
  where symbol = p_symbol
    and currency in ('USD', 'ALL')
    and enabled is true
    and scheduled_at >= p_week_start
    and scheduled_at < p_week_end;
$$;

revoke all on function public.get_live_trader_news_inventory_v96(text, timestamptz, timestamptz) from public;
revoke all on function public.get_live_trader_news_inventory_v96(text, timestamptz, timestamptz) from anon;
revoke all on function public.get_live_trader_news_inventory_v96(text, timestamptz, timestamptz) from authenticated;
grant execute on function public.get_live_trader_news_inventory_v96(text, timestamptz, timestamptz) to service_role;
