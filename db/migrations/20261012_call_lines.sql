-- FaceTime lines (Chert): a client reserves a free line from their /go link, then FaceTimes it; the worker on that line
-- matches the incoming call to the reservation (calls carry no caller identity we can rely on).
-- One line = one call at a time, and Chert takes a line offline for a few minutes after each call (cooldown_s).

create table if not exists call_lines (
  id               text primary key,                 -- 'line1': the worker's BRODIE_LINE env
  facetime_handle  text not null,                    -- what the client FaceTimes: phone number or Apple ID email
  enabled          boolean not null default true,
  cooldown_s       int not null default 180,         -- offline after each call
  busy_until       timestamptz,                      -- set on release: now() + cooldown_s
  created_at       timestamptz not null default now()
);

create table if not exists line_claims (
  id          uuid primary key default gen_random_uuid(),
  line_id     text not null references call_lines(id) on delete cascade,
  client_id   uuid not null references clients(id) on delete cascade,
  created_at  timestamptz not null default now(),
  expires_at  timestamptz not null,                  -- the FaceTime call must arrive by then
  used_at     timestamptz,                           -- the worker matched a call to it
  ended_at    timestamptz                            -- the call ended (or the worker gave up on it)
);
create index if not exists line_claims_line_idx on line_claims (line_id, created_at desc);
create index if not exists line_claims_client_idx on line_claims (client_id, created_at desc);

alter table call_lines enable row level security;
alter table line_claims enable row level security;   -- service role only, like the other tables

-- A claim holds its line while it waits for the call (until expires_at) and while the call runs (used, not ended; capped
-- at 90 minutes in case a worker dies without releasing).
create or replace function line_claim_active(c line_claims) returns boolean language sql stable as $$
  select c.ended_at is null and (
    (c.used_at is null and c.expires_at > now()) or
    (c.used_at is not null and c.used_at > now() - interval '90 minutes'));
$$;

-- Web (/go "Start workout"): reserve a free line for this client, or return the one they already hold.
-- Returns no row when every line is busy; next_free_at says when the earliest one frees up (null if unknown).
create or replace function claim_line(p_client uuid, p_ttl_s int default 180)
returns table (claim_id uuid, line_id text, facetime_handle text, expires_at timestamptz, next_free_at timestamptz)
language plpgsql security definer set search_path = public as $$
declare
  l call_lines; c line_claims;
begin
  perform pg_advisory_xact_lock(hashtext('claim_line'));            -- claims are rare: one at a time keeps this simple and race-free
  select lc.* into c from line_claims lc join call_lines cl on cl.id = lc.line_id
   where lc.client_id = p_client and cl.enabled and line_claim_active(lc) and lc.used_at is null
   order by lc.created_at desc limit 1;
  if found then
    update line_claims set expires_at = greatest(line_claims.expires_at, now() + make_interval(secs => p_ttl_s)) where id = c.id
      returning * into c;
    return query select c.id, c.line_id, (select x.facetime_handle from call_lines x where x.id = c.line_id), c.expires_at, null::timestamptz;
    return;
  end if;
  select cl.* into l from call_lines cl
   where cl.enabled and (cl.busy_until is null or cl.busy_until <= now())
     and not exists (select 1 from line_claims lc where lc.line_id = cl.id and line_claim_active(lc))
   order by cl.id limit 1;
  if not found then
    return query select null::uuid, null::text, null::text, null::timestamptz,
      (select min(greatest(coalesce(cl.busy_until, now()),
                           coalesce((select max(lc.expires_at) from line_claims lc where lc.line_id = cl.id and line_claim_active(lc) and lc.used_at is null), now())))
         from call_lines cl where cl.enabled
          and not exists (select 1 from line_claims lc where lc.line_id = cl.id and lc.used_at is not null and line_claim_active(lc)));
    return;
  end if;
  insert into line_claims (line_id, client_id, expires_at) values (l.id, p_client, now() + make_interval(secs => p_ttl_s)) returning * into c;
  return query select c.id, c.line_id, l.facetime_handle, c.expires_at, null::timestamptz;
end $$;

-- Worker: a call just arrived on this line. Take the waiting claim (60 s grace past expiry for a slow ring) and return its
-- client; no row means a walk-in caller with no reservation.
create or replace function take_line_claim(p_line text)
returns table (claim_id uuid, client_id uuid)
language plpgsql security definer set search_path = public as $$
declare c line_claims;
begin
  update line_claims set used_at = now()
   where id = (select lc.id from line_claims lc
                where lc.line_id = p_line and lc.used_at is null and lc.ended_at is null and lc.expires_at > now() - interval '60 seconds'
                order by lc.created_at desc limit 1 for update skip locked)
  returning * into c;
  if found then return query select c.id, c.client_id; return; end if;
  update call_lines set busy_until = now() + interval '90 minutes' where id = p_line;   -- walk-in: hold the line until release
end $$;

-- Worker: the call on this line ended. Close its claim and start the line's cooldown.
create or replace function release_line(p_line text, p_claim uuid default null)
returns void language plpgsql security definer set search_path = public as $$
begin
  update line_claims set ended_at = now() where id = p_claim and ended_at is null;
  update call_lines set busy_until = now() + make_interval(secs => cooldown_s) where id = p_line;
end $$;

revoke all on function claim_line(uuid, int), take_line_claim(text), release_line(text, uuid) from public, anon, authenticated;
grant execute on function claim_line(uuid, int), take_line_claim(text), release_line(text, uuid) to service_role;

notify pgrst, 'reload schema';
