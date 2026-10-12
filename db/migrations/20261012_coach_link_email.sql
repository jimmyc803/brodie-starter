-- "Email me my link" (/link): when we last emailed a coach their private link, for the 10-minute resend guard
-- and the site-wide hourly cap (web/lib/coach-emails.ts mayEmailLink).
alter table public.coaches add column if not exists link_emailed_at timestamptz;
create index if not exists coaches_link_emailed_at on public.coaches (link_emailed_at) where link_emailed_at is not null;
