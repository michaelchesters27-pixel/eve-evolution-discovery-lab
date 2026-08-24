-- Prevent a retiring/lagging runtime from resurrecting an already-finished
-- Live Trader campaign during a rolling deployment. Terminal campaign states
-- are monotonic: once won/lost/invalidated/expired, they cannot return to
-- pending/active for the same campaign id.

create or replace function public.guard_live_trader_terminal_campaign_state()
returns trigger
language plpgsql
set search_path = public
as $$
begin
  if old.status in ('won', 'lost', 'invalidated', 'expired')
     and new.status in ('pending', 'active') then
    return old;
  end if;
  return new;
end;
$$;

drop trigger if exists trg_guard_live_trader_terminal_campaign_state
  on public.live_trader_campaigns;

create trigger trg_guard_live_trader_terminal_campaign_state
before update on public.live_trader_campaigns
for each row
execute function public.guard_live_trader_terminal_campaign_state();
