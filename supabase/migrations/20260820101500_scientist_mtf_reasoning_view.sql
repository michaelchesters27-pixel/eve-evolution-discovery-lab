-- Compact causal multi-timeframe features for Scientist v2.
-- The canonical context remains m5_research_snapshots.mtf_context; this view
-- exposes only small deterministic fields needed during six-year hypothesis
-- screening, so the Scientist never has to download the full JSON context.

create or replace view public.m5_scientist_research
with (security_invoker = true)
as
select
    s.*,
    coalesce(nullif(s.mtf_context #>> '{M1,available}', '')::boolean, false) as mtf_m1_available,
    nullif(s.mtf_context #>> '{M1,direction}', '')::smallint as mtf_m1_direction,
    nullif(s.mtf_context #>> '{M1,direction_score}', '')::smallint as mtf_m1_direction_score,
    nullif(s.mtf_context #>> '{M1,direction_changes}', '')::smallint as mtf_m1_direction_changes,
    nullif(s.mtf_context #>> '{M1,path_efficiency}', '')::double precision as mtf_m1_path_efficiency,
    nullif(s.mtf_context #>> '{M1,first_minute_direction}', '')::smallint as mtf_m1_first_direction,
    nullif(s.mtf_context #>> '{M1,last_minute_direction}', '')::smallint as mtf_m1_last_direction,
    nullif(s.mtf_context #>> '{M15,direction}', '')::smallint as mtf_m15_direction,
    nullif(s.mtf_context #>> '{M30,direction}', '')::smallint as mtf_m30_direction,
    nullif(s.mtf_context #>> '{H1,direction}', '')::smallint as mtf_h1_direction,
    nullif(s.mtf_context #>> '{H4,direction}', '')::smallint as mtf_h4_direction,
    nullif(s.mtf_context #>> '{D1,direction}', '')::smallint as mtf_d1_direction,
    nullif(s.mtf_context ->> 'direction_alignment_score', '')::smallint as mtf_direction_alignment_score,
    nullif(s.mtf_context ->> 'higher_timeframe_alignment_score', '')::smallint as mtf_htf_alignment_score,
    coalesce(nullif(s.mtf_context ->> 'context_complete', '')::boolean, false) as mtf_context_complete
from public.m5_research_snapshots s;

revoke all on table public.m5_scientist_research from anon, authenticated;
grant select on table public.m5_scientist_research to service_role;

comment on view public.m5_scientist_research is
    'Backend-only compact Scientist projection of the causal M1/M5/M15/M30/H1/H4/D1 context stored on every M5 research state.';
