-- Power hour lookup for the messaging layer (POWER / STATUS commands) and jobs.
-- ch_power_hour(p_now) -> today's (ET) power hour, or null if none is scheduled.
-- Unannounced power hours are hidden until they start (same rule as power_hour_public).
begin;

create or replace function ch_power_hour(p_now timestamptz)
returns jsonb language sql stable security definer set search_path = public as $$
  select jsonb_build_object(
           'date_et', ph.date_et,
           'starts_at', ph.starts_at,
           'ends_at', ph.ends_at,
           'announced', ph.announced_at is not null,
           'active', p_now >= ph.starts_at and p_now < ph.ends_at,
           'over', p_now >= ph.ends_at)
  from power_hours ph
  where ph.date_et = ch_et_day(p_now)
    and (ph.announced_at is not null or ph.starts_at <= p_now)
$$;

revoke all on function ch_power_hour(timestamptz) from public, anon, authenticated;
grant execute on function ch_power_hour(timestamptz) to service_role;

commit;
