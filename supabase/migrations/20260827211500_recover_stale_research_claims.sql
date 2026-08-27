-- A Railway restart can leave a claimed candidate/mutation permanently marked
-- running because the original claim functions only ever selected queued rows.
-- Recover claims whose heartbeat has been dead for two hours before each new
-- atomic claim. Normal research jobs complete far inside this window; this is a
-- crash/restart recovery path, not a parallel-execution shortcut.

create or replace function public.claim_next_discovery_candidate(p_worker_id text)
returns setof public.strategy_candidates
language plpgsql
security definer
set search_path = public
as $$
declare
    v_id uuid;
begin
    update public.strategy_candidates
    set
        status = 'queued',
        worker_id = null,
        started_at = null,
        heartbeat_at = null,
        error = 'Recovered stale running claim after worker restart.'
    where status = 'running'
      and coalesce(heartbeat_at, started_at, requested_at) < now() - interval '2 hours';

    select id into v_id
    from public.strategy_candidates
    where status = 'queued'
    order by priority desc, requested_at asc
    for update skip locked
    limit 1;

    if v_id is null then
        return;
    end if;

    update public.strategy_candidates
    set
        status = 'running',
        worker_id = p_worker_id,
        started_at = now(),
        heartbeat_at = now(),
        error = null
    where id = v_id;

    return query select * from public.strategy_candidates where id = v_id;
end;
$$;

create or replace function public.claim_next_mutation_candidate(p_worker_id text)
returns setof public.mutation_candidates
language plpgsql
security definer
set search_path = public
as $$
declare
    v_id uuid;
begin
    update public.mutation_candidates
    set
        status = 'queued',
        worker_id = null,
        started_at = null,
        heartbeat_at = null,
        error = 'Recovered stale running claim after worker restart.'
    where status = 'running'
      and coalesce(heartbeat_at, started_at, requested_at) < now() - interval '2 hours';

    select id into v_id
    from public.mutation_candidates
    where status = 'queued'
    order by priority desc, requested_at asc
    for update skip locked
    limit 1;

    if v_id is null then
        return;
    end if;

    update public.mutation_candidates
    set
        status = 'running',
        worker_id = p_worker_id,
        started_at = now(),
        heartbeat_at = now(),
        error = null
    where id = v_id;

    return query select * from public.mutation_candidates where id = v_id;
end;
$$;

revoke all on function public.claim_next_discovery_candidate(text) from public, anon, authenticated;
revoke all on function public.claim_next_mutation_candidate(text) from public, anon, authenticated;
grant execute on function public.claim_next_discovery_candidate(text) to service_role;
grant execute on function public.claim_next_mutation_candidate(text) to service_role;
