-- Anti call-stealing: the public line status no longer reveals the 90 s claim window (someone's turn is starting),
-- which told a would-be stealer exactly when to FaceTime in. A claimed line now reads as in_call publicly; the holder
-- still gets the you're-up text and sees their own claim on /me. Same columns; create or replace (idempotent).
create or replace view line_status_public as
 WITH cfg AS (
         SELECT ( SELECT (competition_config.value #>> '{}'::text[])::timestamp with time zone AS timestamptz
                   FROM competition_config
                  WHERE competition_config.key = 'window_start'::text) AS window_start,
            ( SELECT (competition_config.value #>> '{}'::text[])::timestamp with time zone AS timestamptz
                   FROM competition_config
                  WHERE competition_config.key = 'window_end'::text) AS window_end,
            COALESCE(( SELECT competition_config.value = 'true'::jsonb
                   FROM competition_config
                  WHERE competition_config.key = 'competition_frozen'::text), false) AS frozen,
            COALESCE(( SELECT (competition_config.value #>> '{}'::text[])::integer AS int4
                   FROM competition_config
                  WHERE competition_config.key = 'call_count_s'::text), 180) AS count_s,
            COALESCE(( SELECT (competition_config.value #>> '{}'::text[])::integer AS int4
                   FROM competition_config
                  WHERE competition_config.key = 'call_reveal_s'::text), 15) AS reveal_s,
            COALESCE(( SELECT (competition_config.value #>> '{}'::text[])::integer AS int4
                   FROM competition_config
                  WHERE competition_config.key = 'line_offline_gap_s'::text), 180) AS gap_s
        ), ls AS (
         SELECT s.state,
            s.updated_at
           FROM line_state s
             JOIN lines l ON l.id = s.line_id
          WHERE l.active
        ), recent AS (
         SELECT EXTRACT(epoch FROM calls.ended_at - calls.connected_at) AS dur
           FROM calls
          WHERE calls.decision = 'accept'::text AND calls.ended_at IS NOT NULL
          ORDER BY calls.connected_at DESC
         LIMIT 10
        )
 SELECT
        CASE
            WHEN frozen OR window_start IS NOT NULL AND now() < window_start OR window_end IS NOT NULL AND now() >= window_end OR NOT (EXISTS ( SELECT 1
               FROM ls)) THEN 'closed'::text
            WHEN (EXISTS ( SELECT 1
               FROM ls
              WHERE ls.state = 'idle'::text)) THEN 'idle'::text
            WHEN (EXISTS ( SELECT 1
               FROM ls
              WHERE ls.state = 'claimed'::text)) THEN 'in_call'::text
            WHEN (EXISTS ( SELECT 1
               FROM ls
              WHERE ls.state = 'in_call'::text)) THEN 'in_call'::text
            ELSE 'offline'::text
        END AS state_summary,
    (( SELECT count(*) AS count
           FROM queue
          WHERE queue.status = 'waiting'::text))::integer AS queue_length,
    (( SELECT count(*) AS count
           FROM ls))::integer AS lines_active,
    (COALESCE(( SELECT round(avg(recent.dur)) AS round
           FROM recent), (count_s + reveal_s)::numeric) + gap_s::numeric)::integer AS eta_cycle_s,
    ( SELECT max(ls.updated_at) AS max
           FROM ls) AS updated_at
   FROM cfg;
