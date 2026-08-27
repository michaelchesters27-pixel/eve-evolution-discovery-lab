-- Repair mature every-M5 rows that were initially written before their full
-- 240-minute forward outcome path existed. The Railway backfill worker computes
-- the outcomes from source M5 candles; this function applies them atomically and
-- keeps the incremental integrity counters consistent.

create or replace function public.apply_fabric_outcome_backfill(
    p_symbol text,
    p_updates jsonb
)
returns jsonb
language plpgsql
security definer
set search_path = public, pg_temp
as $$
declare
    v_completed bigint := 0;
    v_oldest timestamptz;
    v_newest timestamptz;
begin
    if p_symbol is null or btrim(p_symbol) = '' then
        raise exception 'p_symbol is required';
    end if;
    if p_updates is null or jsonb_typeof(p_updates) <> 'array' then
        raise exception 'p_updates must be a JSON array';
    end if;

    with payload as (
        select
            (item->>'candle_time')::timestamptz as candle_time,
            coalesce(item->'outcomes', '{}'::jsonb) as outcomes,
            coalesce(
                array(
                    select value::smallint
                    from jsonb_array_elements_text(coalesce(item->'outcome_horizons', '[]'::jsonb)) as h(value)
                ),
                '{}'::smallint[]
            ) as outcome_horizons
        from jsonb_array_elements(p_updates) as x(item)
        where item ? 'candle_time'
    ), changed as (
        update public.m5_research_snapshots m
        set
            outcomes = p.outcomes,
            outcome_horizons = p.outcome_horizons,
            outcome_complete = true
        from payload p
        where m.symbol = p_symbol
          and m.snapshot_interval = '5min'
          and m.source_interval = '5min'
          and m.candle_time = p.candle_time
          and m.outcome_complete = false
          and cardinality(p.outcome_horizons) >= 5
        returning m.candle_time
    )
    select count(*), min(candle_time), max(candle_time)
    into v_completed, v_oldest, v_newest
    from changed;

    if v_completed > 0 then
        update public.fabric_audit_state
        set
            complete_rows = least(rows_audited, complete_rows + v_completed),
            updated_at = now()
        where symbol = p_symbol;

        update public.fabric_build_state
        set
            complete_rows = least(rows_written, complete_rows + v_completed),
            updated_at = now()
        where symbol = p_symbol;
    end if;

    return jsonb_build_object(
        'completed', v_completed,
        'oldest', v_oldest,
        'newest', v_newest
    );
end;
$$;

revoke all on function public.apply_fabric_outcome_backfill(text,jsonb) from public, anon, authenticated;
grant execute on function public.apply_fabric_outcome_backfill(text,jsonb) to service_role;

comment on function public.apply_fabric_outcome_backfill(text,jsonb) is
'Atomically completes mature every-M5 outcome labels and increments fabric integrity counters only for rows transitioning false -> true.';
