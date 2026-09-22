-- Audit remediation Fix 10: one durable owner for bounded heavy research.
-- Prevents overlapping deployments/supervisors from running the same historical
-- pipeline concurrently. The token is renewed between stages and must match on
-- release.

create table if not exists public.bounded_research_supervisor_lease (
  lock_name text primary key,
  owner_id text,
  lease_token uuid,
  acquired_at timestamptz,
  renewed_at timestamptz,
  expires_at timestamptz,
  updated_at timestamptz not null default now()
);

insert into public.bounded_research_supervisor_lease(lock_name)
values ('evolution-heavy-research')
on conflict (lock_name) do nothing;

alter table public.bounded_research_supervisor_lease enable row level security;
revoke all on table public.bounded_research_supervisor_lease from public, anon, authenticated;
grant select, insert, update on table public.bounded_research_supervisor_lease to service_role;

create or replace function public.claim_bounded_research_supervisor_v96(
  p_owner_id text,
  p_lease_seconds integer default 1800
)
returns jsonb
language plpgsql
security definer
set search_path = public
as $$
declare
  v_now timestamptz := now();
  v_token uuid := gen_random_uuid();
  v_row public.bounded_research_supervisor_lease%rowtype;
  v_seconds integer := greatest(60, least(coalesce(p_lease_seconds,1800),7200));
begin
  perform pg_advisory_xact_lock(hashtext('eve-evolution-heavy-research-v96'));

  select * into v_row
  from public.bounded_research_supervisor_lease
  where lock_name='evolution-heavy-research'
  for update;

  if v_row.expires_at is not null
     and v_row.expires_at > v_now
     and coalesce(v_row.owner_id,'') <> coalesce(p_owner_id,'') then
    return jsonb_build_object(
      'acquired', false,
      'owner_id', v_row.owner_id,
      'expires_at', v_row.expires_at,
      'reason', 'lease_held'
    );
  end if;

  update public.bounded_research_supervisor_lease
  set owner_id=p_owner_id,
      lease_token=v_token,
      acquired_at=v_now,
      renewed_at=v_now,
      expires_at=v_now + make_interval(secs => v_seconds),
      updated_at=v_now
  where lock_name='evolution-heavy-research';

  return jsonb_build_object(
    'acquired', true,
    'owner_id', p_owner_id,
    'lease_token', v_token,
    'expires_at', v_now + make_interval(secs => v_seconds)
  );
end;
$$;

create or replace function public.renew_bounded_research_supervisor_v96(
  p_owner_id text,
  p_lease_token uuid,
  p_lease_seconds integer default 1800
)
returns jsonb
language plpgsql
security definer
set search_path = public
as $$
declare
  v_now timestamptz := now();
  v_seconds integer := greatest(60, least(coalesce(p_lease_seconds,1800),7200));
  v_updated integer := 0;
begin
  update public.bounded_research_supervisor_lease
  set renewed_at=v_now,
      expires_at=v_now + make_interval(secs => v_seconds),
      updated_at=v_now
  where lock_name='evolution-heavy-research'
    and owner_id=p_owner_id
    and lease_token=p_lease_token
    and expires_at > v_now;
  get diagnostics v_updated = row_count;

  return jsonb_build_object(
    'renewed', v_updated = 1,
    'owner_id', p_owner_id,
    'lease_token', p_lease_token,
    'expires_at', case when v_updated=1 then v_now + make_interval(secs => v_seconds) else null end
  );
end;
$$;

create or replace function public.release_bounded_research_supervisor_v96(
  p_owner_id text,
  p_lease_token uuid
)
returns jsonb
language plpgsql
security definer
set search_path = public
as $$
declare
  v_updated integer := 0;
begin
  update public.bounded_research_supervisor_lease
  set owner_id=null,
      lease_token=null,
      acquired_at=null,
      renewed_at=null,
      expires_at=null,
      updated_at=now()
  where lock_name='evolution-heavy-research'
    and owner_id=p_owner_id
    and lease_token=p_lease_token;
  get diagnostics v_updated = row_count;
  return jsonb_build_object('released', v_updated = 1);
end;
$$;

revoke all on function public.claim_bounded_research_supervisor_v96(text,integer) from public, anon, authenticated;
revoke all on function public.renew_bounded_research_supervisor_v96(text,uuid,integer) from public, anon, authenticated;
revoke all on function public.release_bounded_research_supervisor_v96(text,uuid) from public, anon, authenticated;
grant execute on function public.claim_bounded_research_supervisor_v96(text,integer) to service_role;
grant execute on function public.renew_bounded_research_supervisor_v96(text,uuid,integer) to service_role;
grant execute on function public.release_bounded_research_supervisor_v96(text,uuid) to service_role;

comment on table public.bounded_research_supervisor_lease is
'Fix 10 durable singleton lease preventing overlapping Evolution heavy-research supervisors.';
