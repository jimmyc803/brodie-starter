-- Two prizes instead of one (D-47): first_prize still goes to the top scorer, drawing_prize goes to a weighted random
-- drawing where one valid rep is one ticket (challenge/scoring.py draw_winner). competition_public is recreated with
-- every existing column in the same order, then the new one, so the web mapper keeps reading the old names.
--
-- drawing_prize defaults to "$100" to match first_prize's default: both are display copy an operator sets per run
-- (the live run is $500 each), and the defaults are what db/tests assert, so neither is changed here.

insert into competition_config (key, value) values
  ('drawing_prize', to_jsonb('$100'::text))
on conflict (key) do nothing;

drop view if exists competition_public;
create view competition_public with (security_barrier = true) as
with k as (select key, value from competition_config)
select (select (value #>> '{}')::timestamptz from k where key = 'window_start') as window_start,
       (select (value #>> '{}')::timestamptz from k where key = 'window_end') as window_end,
       (coalesce((select value = 'true'::jsonb from k where key = 'competition_frozen'), false)
        or coalesce(now() >= (select (value #>> '{}')::timestamptz from k where key = 'window_end'), false)) as frozen,
       (select value #>> '{}' from k where key = 'brodie_number') as brodie_number,
       (select value #>> '{}' from k where key = 'site_url') as site_url,
       (select value from k where key = 'avatar_level_thresholds') as avatar_level_thresholds,
       (select value #>> '{}' from k where key = 'ufc_fighter') as ufc_fighter,
       (select value #>> '{}' from k where key = 'first_prize') as first_prize,
       (select value #>> '{}' from k where key = 'drawing_prize') as drawing_prize;

revoke all on table competition_public from public, anon, authenticated;
grant select on table competition_public to anon, authenticated, service_role;
