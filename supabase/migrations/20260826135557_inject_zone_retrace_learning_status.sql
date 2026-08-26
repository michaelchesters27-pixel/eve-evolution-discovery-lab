-- Historical migration marker for the Supabase-only 2026-08-26 13:55 state-injection experiment.
--
-- The original migration installed a trigger/function that overwrote persisted
-- Live Trader learning state with a broad, obsolete retracement headline. The
-- hard audit proved that behavior was misleading and it was intentionally
-- removed by 20260826154700_remove_obsolete_zone_retrace_state_trigger_v65.sql.
--
-- Do NOT recreate the obsolete trigger on a clean database. This no-op preserves
-- migration/source history while the later v65 migration remains idempotently safe.

do $$
begin
    null;
end
$$;
