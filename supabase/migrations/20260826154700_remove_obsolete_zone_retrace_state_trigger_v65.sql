drop trigger if exists trg_inject_zone_retrace_learning_status on public.live_trader_state;
drop function if exists public.inject_zone_retrace_learning_status();

update public.live_trader_state
set state = jsonb_set(
              state - 'strategy_learning_banner',
              '{learning,strategy_specialist}',
              coalesce(state->'zone_retrace_learning','{}'::jsonb),
              true
            ),
    updated_at = now()
where symbol = 'XAU/USD'
  and state ? 'zone_retrace_learning';
