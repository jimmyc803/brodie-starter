"""Scheduled jobs (SPEC §2/§7/§8/§10). `Jobs.run_due(now)` is the single entrypoint: idempotent, safe to
call at any frequency (2s in prod, synthetic `now` in simulation). Every step is isolated, cadence-
throttled on the injected time, and keyed by dedupe keys / job_state so repeated runs never re-send.

Stale proactive texts are skipped in quiet hours, never deferred (each time-of-day job has a short
validity window). Only final results defer to the morning, since they are not stale."""
from __future__ import annotations

import asyncio
import logging
import os
from datetime import date, datetime, timedelta
from typing import Any, Callable

from challenge.dispatcher.alerts import Alerts
from challenge.dispatcher.powerhour import PowerHours, fmt_range
from challenge.store import Json, Store, StoreError
from challenge.timeutil import ET, et_day, in_quiet_hours, parse_ts

logger = logging.getLogger("challenge.jobs")

POSTCALL_EVERY = timedelta(seconds=30)
POSTCALL_MAX_ATTEMPTS = 10
POSTCALL_MAX_AGE = timedelta(hours=1)
HEARTBEAT_EVERY = timedelta(seconds=10)
ALERTS_EVERY = timedelta(seconds=30)
QUEUE_UPDATE_EVERY = timedelta(seconds=10)
QUEUE_UPDATE_MIN_GAP = timedelta(minutes=10)
QUEUE_UPDATE_MIN_GAIN = 3
QUEUE_UPDATE_ETA_MIN = 10
PH_WARN_LEAD = timedelta(minutes=15)
PH_START_VALID = timedelta(minutes=10)
DAILY_VALID = timedelta(hours=2)  # recap / streak risk / ending soon are stale after this


def _hour_start(day: date, hour: int) -> datetime:
    return datetime(day.year, day.month, day.day, hour, tzinfo=ET)


class Jobs:
    def __init__(self, store: Store, cfg: Any, outbox: Any, clock: Callable[[], datetime]):
        self.store, self.cfg, self.outbox, self.clock = store, cfg, outbox, clock
        self.power = PowerHours(store, cfg)
        self.alerts = Alerts(store, cfg, outbox)
        self._last: dict[str, datetime] = {}
        self._done: set[str] = set()
        self._audience: tuple[datetime, list[dict]] | None = None
        self.errors: dict[str, str] = {}

    # ------------------------------------------------------------ plumbing
    def _due(self, name: str, now: datetime, every: timedelta) -> bool:
        last = self._last.get(name)
        if last is not None and last <= now < last + every:
            return False
        self._last[name] = now
        return True

    def _is_done(self, key: str) -> bool:
        if key in self._done:
            return True
        if self.store.rpc("ch_job_get", {"p_key": "done:" + key}) is not None:
            self._done.add(key)
            return True
        return False

    def _mark_done(self, key: str, now: datetime) -> None:
        self.store.rpc("ch_job_set", {"p_key": "done:" + key, "p_value": Json({"at": now.isoformat()}), "p_now": now})
        self._done.add(key)

    def _users(self, now: datetime) -> list[dict]:
        if self._audience is None or self._audience[0] != now:
            self._audience = (now, self.store.rpc("ch_jobs_audience", {"p_now": now}) or [])
        return self._audience[1]

    def _send(self, user_id: str, template: str, ctx: dict, key: str,
              expires_at: datetime | None = None) -> bool:
        if expires_at is not None:  # stale after this instant: the outbox suppresses instead of sending late
            ctx = {**ctx, "expires_at": expires_at.isoformat()}
        try:
            r = self.outbox.enqueue(user_id=user_id, template=template, ctx=ctx, dedupe_key=key, proactive=True)
        except StoreError as e:
            if "handle_required" in str(e):
                logger.warning("no handle for %s; %s not sent", user_id, template)
                return False
            raise
        return not r.get("duplicate")

    def _quiet(self, now: datetime) -> bool:
        return in_quiet_hours(now, self.cfg.get("quiet_hours"))

    def _power_text(self, now: datetime) -> str:
        row = self.store.rpc("ch_power_hour_row", {"p_date_et": et_day(now)})
        return fmt_range(row["starts_at"], row["ends_at"]) if row else "TBA"

    def _site(self) -> str:
        return str(self.cfg.get("site_url")).rstrip("/")

    def _in_window(self, now: datetime) -> bool:
        return parse_ts(self.cfg.get("window_start")) <= now < parse_ts(self.cfg.get("window_end"))

    # ------------------------------------------------------------ entrypoint
    def run_due(self, now: datetime) -> dict:
        """Run every due step once; a failing step is logged and does not stop the others."""
        now = parse_ts(now)
        out: dict[str, Any] = {}
        steps: list[tuple[str, Callable[[], Any]]] = [
            ("tick", lambda: self.tick(now)),
            ("power_hours", lambda: self.power.ensure(now)),
            ("freeze", lambda: self.freeze_and_final(now)),
            ("power_announce", lambda: self.power_announcements(now)),
            ("recap", lambda: self.daily_recap(now)),
            ("streak_risk", lambda: self.streak_risk(now)),
            ("ending_soon", lambda: self.ending_soon(now)),
            ("postcall", lambda: self.postcall_sweep(now) if self._due("postcall", now, POSTCALL_EVERY) else None),
            ("queue_updates", lambda: self.queue_updates(now) if self._due("queue", now, QUEUE_UPDATE_EVERY) else None),
            ("alerts", lambda: self.alerts.check(now) if self._due("alerts", now, ALERTS_EVERY) else None),
            ("heartbeat", lambda: self.heartbeat(now) if self._due("heartbeat", now, HEARTBEAT_EVERY) else None),
            ("outbox", lambda: self.outbox.run_once(now)),
        ]
        for name, fn in steps:
            try:
                out[name] = fn()
                self.errors.pop(name, None)
            except Exception as exc:
                logger.exception("job step %s failed", name)
                self.errors[name] = type(exc).__name__
                out[name] = {"error": type(exc).__name__}
        return out

    run_once = run_due

    # ------------------------------------------------------------ steps
    def tick(self, now: datetime) -> dict:
        r = self.store.rpc("ch_tick", {"p_now": now})
        if r and (r.get("claims") or r.get("no_shows") or r.get("timeouts")):
            logger.info("tick: %s", {k: len(v) for k, v in r.items() if isinstance(v, list)})
        return r

    def heartbeat(self, now: datetime) -> None:
        self.store.rpc("ch_heartbeat", {"p_component": "dispatcher",
                                        "p_detail": {"errors": dict(self.errors)}, "p_now": now})

    def freeze_and_final(self, now: datetime) -> str | None:
        """At window_end: freeze scoring (once, actor 'system'), then send final results (once per user)."""
        if now < parse_ts(self.cfg.get("window_end")):
            return None
        if not self._is_done("freeze"):
            self.store.rpc("ch_config_set", {"p_key": "competition_frozen", "p_value": Json(True),
                                             "p_actor": "system", "p_reason": "window_end reached"})
            # scoring is timestamp-based: reps count iff ts < min(window_end, frozen_at)
            self.store.rpc("ch_set_frozen_at", {"p_at": parse_ts(self.cfg.get("window_end")),
                                                "p_actor": "system", "p_reason": "window_end reached"})
            self._mark_done("freeze", now)
            logger.warning("competition frozen at window_end")
        if self._is_done("final"):
            return None
        site = self._site()
        for u in self._users(now):
            self._send(u["user_id"], "final_results",
                       {"points": u["points"], "rank": u["rank"], "site_url": site}, f"final:{u['user_id']}")
        self._mark_done("final", now)
        return "final_results"

    def power_announcements(self, now: datetime) -> list[str]:
        """ph_warn at start-15m and ph_start at start (validity 10m); announced_at stamped at recap time."""
        row = self.store.rpc("ch_power_hour_row", {"p_date_et": et_day(now)})
        if not row or not self._in_window(now):
            return []
        day, done = et_day(now), []
        starts = parse_ts(row["starts_at"])
        if row["announced_at"] is None and now >= _hour_start(day, int(self.cfg.get("recap_hour"))):
            self.store.rpc("ch_power_hour_mark", {"p_date_et": day, "p_kind": "announced", "p_now": now})
        for kind, template, lo, hi, field in (
                ("warned", "ph_warn", starts - PH_WARN_LEAD, starts, "warned_at"),
                ("started", "ph_start", starts, starts + PH_START_VALID, "started_announced_at")):
            if row[field] is not None or not (lo <= now < hi):
                continue
            if not self._quiet(now):
                for u in self._users(now):
                    self._send(u["user_id"], template, {"power_hour": fmt_range(row["starts_at"], row["ends_at"])},
                               f"{template}:{day}:{u['user_id']}",
                               expires_at=starts if template == "ph_warn" else parse_ts(row["ends_at"]))
            # exactly once either way: quiet hours skip the text, they do not defer it
            self.store.rpc("ch_power_hour_mark", {"p_date_et": day, "p_kind": kind, "p_now": now})
            done.append(template)
        return done

    def _daily(self, now: datetime, name: str, hour: int, valid: timedelta = DAILY_VALID) -> bool:
        """True once per ET day inside [hour:00, hour:00 + valid) during the competition window."""
        if not self._in_window(now):
            return False
        day = et_day(now)
        start = _hour_start(day, hour)
        if not (start <= now < start + valid):
            return False
        return not self._is_done(f"{name}:{day}")

    def daily_recap(self, now: datetime) -> int:
        if not self._daily(now, "recap", int(self.cfg.get("recap_hour"))):
            return 0
        day, n = et_day(now), 0
        self.store.rpc("ch_power_hour_mark", {"p_date_et": day, "p_kind": "announced", "p_now": now})
        if not self._quiet(now):
            ph, site = self._power_text(now), self._site()
            for u in self._users(now):
                n += self._send(u["user_id"], "daily_recap", {
                    "yesterday_points": u["yesterday_points"], "points": u["points"], "rank": u["rank"],
                    "streak": u["streak"], "power_hour": ph, "site_url": site}, f"recap:{day}:{u['user_id']}")
        self._mark_done(f"recap:{day}", now)
        return n

    def streak_risk(self, now: datetime) -> int:
        if not self._daily(now, "streak", int(self.cfg.get("streak_risk_hour"))):
            return 0
        day, n = et_day(now), 0
        if not self._quiet(now):
            for u in self._users(now):
                if u["streak"] >= 2 and not u["qualified_today"]:
                    n += self._send(u["user_id"], "streak_risk", {"streak": u["streak"]},
                                    f"streak_risk:{day}:{u['user_id']}")
        self._mark_done(f"streak:{day}", now)
        return n

    def ending_soon(self, now: datetime) -> int:
        end = parse_ts(self.cfg.get("window_end"))
        if et_day(now) != et_day(end) or not self._daily(now, "ending", 20):
            return 0
        n = 0
        if not self._quiet(now):
            when = end.astimezone(ET).strftime("%I:%M %p").lstrip("0") + " ET"
            for u in self._users(now):
                n += self._send(u["user_id"], "ending_soon", {"ends_at": f"tonight at {when}"},
                                f"ending_soon:{u['user_id']}", expires_at=end)
        self._mark_done(f"ending:{et_day(now)}", now)
        return n

    def postcall_sweep(self, now: datetime) -> dict:
        """Retry ch_postcall for committed calls; give up after 10 attempts or 1h (logged + health warning)."""
        res = {"done": 0, "failed": 0, "gave_up": 0}
        for item in self.store.rpc("ch_postcall_pending", {"p_now": now, "p_limit": 50}) or []:
            cid, key = item["call_id"], "postcall:" + item["call_id"]
            st = self.store.rpc("ch_job_incr", {"p_key": key, "p_now": now})
            if st["n"] > POSTCALL_MAX_ATTEMPTS or now - parse_ts(st["first_at"]) > POSTCALL_MAX_AGE:
                reason = f"gave up after {st['n'] - 1} attempts since {st['first_at']}"
                logger.error("postcall %s: %s", cid, reason)
                self.store.rpc("ch_job_set", {"p_key": "postcall_giveup:" + cid,
                                              "p_value": Json({"at": now.isoformat(), "reason": reason}), "p_now": now})
                self.store.rpc("ch_heartbeat", {"p_component": "warn:postcall:" + cid,
                                                "p_detail": {"call_id": cid, "reason": reason}, "p_now": now})
                res["gave_up"] += 1
                continue
            try:
                r = self.store.rpc("ch_postcall", {"p_call_id": cid, "p_now": now, "p_card_delivery": self._card()})
                ok = bool(r and r.get("ok"))
            except StoreError as e:
                logger.warning("postcall %s attempt %s failed: %s", cid, st["n"], e)
                ok = False
            if ok:
                self.store.rpc("ch_job_delete", {"p_key": key})
                res["done"] += 1
            else:
                res["failed"] += 1
        return res

    @staticmethod
    def _card() -> str:
        return os.environ.get("CARD_DELIVERY", "link")

    def queue_updates(self, now: datetime) -> int:
        """Text a waiting user when their position improved by >=3 or ETA moved >=10 min since the last
        notice; at most one per 10 min; never in quiet hours. First sight only records a baseline."""
        view = self.store.rpc("ch_queue_view", {"p_now": now})
        cycle = float(view.get("avg_cycle_s") or 0)
        waiting = [q for q in view.get("queue", []) if q["status"] == "waiting"]
        states = self.store.rpc("ch_job_list", {"p_prefix": "qpos:"}) or {}
        live = set()
        sent = 0
        quiet = self._quiet(now)
        for q in waiting:
            key = f"qpos:{q['user_id']}"
            live.add(key)
            pos, eta = int(q["position"]), (int(q["position"]) - 1) * cycle / 60
            prev = states.get(key)
            if not prev or prev.get("queue_id") != q["queue_id"]:
                self.store.rpc("ch_job_set", {"p_key": key, "p_now": now, "p_value": Json({
                    "queue_id": q["queue_id"], "position": pos, "eta_min": eta, "sent_at": None})})
                continue
            moved = prev["position"] - pos >= QUEUE_UPDATE_MIN_GAIN or abs(prev["eta_min"] - eta) >= QUEUE_UPDATE_ETA_MIN
            gap_ok = prev["sent_at"] is None or now - parse_ts(prev["sent_at"]) >= QUEUE_UPDATE_MIN_GAP
            if pos < 2 or quiet or not moved or not gap_ok:
                continue
            lo = int(eta // 5 * 5)
            ctx = {"position": pos, "eta": f"~{lo}–{lo + 5} min", "_proactive": True,
                   "expires_at": (now + QUEUE_UPDATE_MIN_GAP).isoformat()}
            state = {"queue_id": q["queue_id"], "position": pos, "eta_min": eta, "sent_at": now.isoformat()}
            try:  # intent + baseline in one DB transaction, deduped per user and 10-minute bucket
                r = self.store.rpc("ch_queue_update_notify", {
                    "p_user_id": q["user_id"], "p_state_key": key, "p_state": Json(state), "p_ctx": ctx,
                    "p_bucket_s": int(QUEUE_UPDATE_MIN_GAP.total_seconds()), "p_now": now})
            except StoreError as e:
                if "handle_required" not in str(e):
                    raise
                continue
            sent += 0 if r.get("duplicate") else 1
        for key in set(states) - live:
            self.store.rpc("ch_job_delete", {"p_key": key})
        return sent


async def run_loop(jobs: Jobs, interval_s: float = 2.0) -> None:
    """Background loop for the FastAPI lifespan; never dies on a step error."""
    while True:
        try:
            await asyncio.to_thread(jobs.run_due, jobs.clock())
        except Exception:
            logger.exception("jobs loop iteration failed")
        await asyncio.sleep(interval_s)
