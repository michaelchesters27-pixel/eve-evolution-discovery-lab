-- Discovery Lab backend-only RPC hardening.
-- These functions are called by the Railway service role, never directly by browsers.

alter function public.set_updated_at() set search_path = public;
alter function public.get_discovery_dashboard() set search_path = public;
alter function public.get_discovery_data_health() set search_path = public;
alter function public.claim_next_discovery_candidate(text) set search_path = public;
alter function public.claim_next_mutation_candidate(text) set search_path = public;
alter function public.record_mutation_memory(text, text, boolean, double precision) set search_path = public;

revoke execute on function public.claim_next_discovery_candidate(text) from public, anon, authenticated;
revoke execute on function public.claim_next_mutation_candidate(text) from public, anon, authenticated;
revoke execute on function public.record_mutation_memory(text, text, boolean, double precision) from public, anon, authenticated;
revoke execute on function public.get_discovery_dashboard() from public, anon, authenticated;
revoke execute on function public.get_discovery_data_health() from public, anon, authenticated;

grant execute on function public.claim_next_discovery_candidate(text) to service_role;
grant execute on function public.claim_next_mutation_candidate(text) to service_role;
grant execute on function public.record_mutation_memory(text, text, boolean, double precision) to service_role;
grant execute on function public.get_discovery_dashboard() to service_role;
grant execute on function public.get_discovery_data_health() to service_role;
