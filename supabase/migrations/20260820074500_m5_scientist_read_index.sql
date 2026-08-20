-- Optimise Scientist v2's full every-M5 research scan.
-- The scientist reads only completed M5 rows, ordered chronologically.
-- A partial index lets keyset pagination advance by candle_time without
-- rescanning incomplete/live rows or paying OFFSET costs.

create index if not exists idx_m5_scientist_complete_symbol_time
    on public.m5_research_snapshots (symbol, snapshot_interval, source_interval, candle_time)
    where outcome_complete = true;

comment on index public.idx_m5_scientist_complete_symbol_time is
    'Supports bounded keyset scans of completed every-M5 research states for EVE Scientist v2.';
