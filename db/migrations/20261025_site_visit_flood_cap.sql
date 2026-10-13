-- Security review (High): /api/visit can be scripted, so ch_site_visit drops writes past 600/min or 200k/day
-- (keeps the database from filling and the metrics from being swamped). create or replace; idempotent.
CREATE OR REPLACE FUNCTION public.ch_site_visit(p_kind text, p_path text, p_source text, p_ref_code text, p_referrer_host text, p_now timestamp with time zone)
 RETURNS jsonb
 LANGUAGE plpgsql
 SECURITY DEFINER
 SET search_path TO 'public'
AS $function$
declare
  v_path text := left(split_part(split_part(coalesce(p_path, '/'), '?', 1), '#', 1), 120);
  v_host text := lower(btrim(p_referrer_host));
begin
  if p_kind is null or p_kind not in ('landing', 'join_tap') then
    raise exception 'bad_kind' using errcode = '22023';
  end if;
  if p_now is null then
    raise exception 'p_now required' using errcode = '22023';
  end if;
  if v_path !~ '^/' then
    v_path := '/';
  end if;
  if v_host !~ '^[a-z0-9.-]{1,100}$' then
    v_host := null;
  end if;
  -- Flood cap (security review): the endpoint's same-origin check is spoofable, so bound writes globally.
  if (select count(*) from site_visits where at > p_now - interval '1 minute') >= 600
     or (select count(*) from site_visits where at > p_now - interval '1 day') >= 200000 then
    return jsonb_build_object('ok', true, 'dropped', true);
  end if;
  insert into site_visits (at, kind, path, source, ref_code, referrer_host)
    values (p_now, p_kind, v_path, ch_norm_source(p_source), ch_norm_ref_code(p_ref_code), v_host);
  return jsonb_build_object('ok', true);
end;
$function$;

create index if not exists site_visits_at_idx on site_visits (at);
