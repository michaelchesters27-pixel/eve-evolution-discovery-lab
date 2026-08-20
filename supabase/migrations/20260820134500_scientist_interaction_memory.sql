-- EVE Scientist pairwise interaction memory.
-- Derived only from the idempotent selection-stage learning ledger.
-- Confirmation and final holdout never enter scientist_learning_events and
-- therefore can never influence this view.

create or replace view public.scientist_interaction_memory
with (security_invoker = true)
as
with expanded as (
    select
        e.candidate_key,
        e.scientist_version,
        e.research_dataset,
        e.contribution,
        e.validation_pf,
        e.validation_expectancy_r,
        e.validation_trades,
        a.value as feature_a,
        b.value as feature_b
    from public.scientist_learning_events e
    cross join lateral jsonb_array_elements_text(e.feature_keys) with ordinality a(value, pos_a)
    cross join lateral jsonb_array_elements_text(e.feature_keys) with ordinality b(value, pos_b)
    where a.pos_a < b.pos_b
      and a.value <> b.value
), canonical as (
    select
        candidate_key,
        scientist_version,
        research_dataset,
        contribution,
        validation_pf,
        validation_expectancy_r,
        validation_trades,
        least(feature_a, feature_b) as feature_a,
        greatest(feature_a, feature_b) as feature_b
    from expanded
)
select
    scientist_version,
    research_dataset,
    feature_a,
    feature_b,
    count(*)::integer as trials,
    count(*) filter (where contribution > 0)::integer as positive_trials,
    avg(contribution)::double precision as score,
    avg(validation_pf)::double precision as mean_validation_pf,
    avg(validation_expectancy_r)::double precision as mean_validation_expectancy_r,
    avg(validation_trades)::double precision as mean_validation_trades,
    max(candidate_key) as latest_candidate_key
from canonical
group by scientist_version, research_dataset, feature_a, feature_b;

revoke all on table public.scientist_interaction_memory from public, anon, authenticated;
grant select on table public.scientist_interaction_memory to service_role;

comment on view public.scientist_interaction_memory is
'Pairwise feature interactions learned only from completed selection-stage Scientist experiments. Derived from scientist_learning_events; confirmation/final holdout are excluded by construction.';
