"""Stuck-state alerts (SPEC §10): line_state stuck, outbound failure spike, stale worker heartbeat.

Each condition alerts at most once per 30 minutes. Alerts go to team_alert_handles through the outbox
(template 'alert', non-proactive so quiet hours and opt-out do not apply) and are always logged."""
from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import Any

from challenge.config import alert_handles
from challenge.store import Json, Store
from challenge.timeutil import ET, parse_ts

logger = logging.getLogger("challenge.alerts")

DEDUPE = timedelta(minutes=30)
HEARTBEAT_STALE = timedelta(minutes=3)
FAIL_RATE = 0.20
MIN_SAMPLE = 5  # a single failure out of two sends is noise, not a spike
WORKER = "worker"
LINE_WATCH_EVERY = timedelta(seconds=10)


class Alerts:
    def __init__(self, store: Store, cfg: Any, outbox: Any = None):
        self.store, self.cfg, self.outbox = store, cfg, outbox

    def conditions(self, now: datetime) -> dict[str, str]:
        """Currently-true alert conditions -> human detail."""
        start, end = parse_ts(self.cfg.get("window_start")), parse_ts(self.cfg.get("window_end"))
        if not (start <= now < end):
            return {}
        health = self.store.rpc("ch_jobs_health", {"p_now": now})
        found: dict[str, str] = {}
        thr = timedelta(seconds=int(self.cfg.get("call_count_s")) + int(self.cfg.get("call_reveal_s"))
                        + int(self.cfg.get("in_call_timeout_extra_s")) + int(self.cfg.get("line_offline_gap_s")) + 300)
        if health["queue_len"] > 0:
            for ln in health["lines"]:
                age = now - parse_ts(ln["updated_at"])
                if age > thr:
                    found["line_stuck"] = (f"{ln['line_id']} in '{ln['state']}' for {int(age.total_seconds() // 60)} min "
                                           f"with {health['queue_len']} waiting")
                    break
        sent, failed = int(health["out_sent"]), int(health["out_failed"])
        total = sent + failed
        if total >= MIN_SAMPLE and failed / total > FAIL_RATE:
            found["outbound_failures"] = f"{failed}/{total} outbound texts failed in the last 15 min"
        beat = health["heartbeats"].get(WORKER)
        if beat is None:
            found["worker_heartbeat"] = "no worker heartbeat recorded"
        elif now - parse_ts(beat) > HEARTBEAT_STALE:
            found["worker_heartbeat"] = f"worker heartbeat {int((now - parse_ts(beat)).total_seconds())}s old"
        return found

    def fire(self, cond: str, detail: str, now: datetime) -> bool:
        """Alert `cond` unless it was alerted in the last 30 minutes; True if sent."""
        key = f"alert_last:{cond}"
        # atomic per-condition claim in the DB: concurrent dispatchers cannot both alert
        if not self.store.rpc("ch_job_claim", {"p_key": key, "p_now": now, "p_gap_s": int(DEDUPE.total_seconds())}):
            return False
        logger.error("ALERT %s: %s", cond, detail)
        handles = self.cfg.get("team_alert_handles") or []
        stamp = int(now.timestamp())
        try:
            for h in handles:
                self.outbox.enqueue(handle=h, template="alert", ctx={"condition": cond, "detail": detail},
                                    dedupe_key=f"alert:{cond}:{stamp // 600}:{h}", proactive=False)
        except Exception:
            self.store.rpc("ch_job_delete", {"p_key": key})  # release the claim so the next run retries
            raise
        return True

    # ------------------------------------------------------------ live line watch (D-42)
    def _display_name(self, user_id: str | None, now: datetime) -> str:
        if not user_id:
            return "someone"
        try:
            return (self.store.rpc("ch_user_status", {"p_user_id": user_id, "p_now": now}) or {}).get(
                "display_name") or "someone"
        except Exception:         # a name is never worth losing the notification over
            logger.warning("line watch: no name for %s", user_id)
            return "someone"

    def watch_lines(self, now: datetime) -> list[str]:
        """Text the team when a line picks up and when it hangs up; returns the events sent.

        State lives in job_state (`line_watch:<line_id>`) and is written only on a transition, so a restart
        re-announces nothing and a quiet line costs one read. Turned off by config `team_line_alerts`.
        """
        on = self.cfg.get("team_line_alerts")
        handles = alert_handles(self.cfg)
        view = self.store.rpc("ch_queue_view", {"p_now": now}) or {}
        waiting = len(view.get("queue") or [])
        sent: list[str] = []
        for line in view.get("lines") or []:
            key = f"line_watch:{line['line_id']}"
            prev = self.store.rpc("ch_job_get", {"p_key": key}) or {}
            live = line["state"] == "in_call"
            if live is bool(prev.get("in_call")):
                continue
            if live:
                who = self._display_name(line.get("user_id"), now)
                since = line.get("in_call_since") or now.isoformat()
                state = {"in_call": True, "call_id": line.get("call_id"), "who": who, "since": since}
                template = "line_live"
                ctx = {"who": who, "line_id": line["line_id"], "queue_len": waiting}
            else:
                who = prev.get("who") or "someone"
                started = prev.get("since")
                state = {"in_call": False, "call_id": None, "who": who, "since": None}
                template = "line_done"
                ctx = {"who": who, "duration": _age(now - parse_ts(started)) if started else "a call",
                       "queue_len": waiting}
            # The state row is written first: a failing send must not leave the watcher announcing the same
            # transition on every pass afterwards.
            self.store.rpc("ch_job_set", {"p_key": key, "p_value": Json(state), "p_now": now})
            stamp = prev.get("call_id") or line.get("call_id") or str(int(now.timestamp()))
            if on:
                for handle in handles:
                    self.outbox.enqueue(handle=handle, template=template, ctx=ctx,
                                        dedupe_key=f"{template}:{stamp}:{handle}", proactive=False)
            sent.append(f"{template}:{line['line_id']}")
        return sent

    def check(self, now: datetime) -> list[str]:
        """Send alerts for conditions not alerted in the last 30 minutes; returns the conditions sent."""
        return [cond for cond, detail in self.conditions(now).items() if self.fire(cond, detail, now)]


# ------------------------------------------------------------------ LIFE health report (D-40)


def _age(delta: timedelta) -> str:
    seconds = int(delta.total_seconds())
    if seconds < 90:
        return f"{max(seconds, 0)}s"
    if seconds < 5400:
        return f"{seconds // 60}m"
    return f"{seconds // 3600}h"


def health_report(store: Store, cfg: Any, now: datetime) -> dict[str, Any]:
    """Plain-language snapshot for the LIFE command: is Brodie up and taking calls?

    Built from the same ch_jobs_health row and the same conditions() the alert texts use, so a LIFE reply and an
    alert never disagree. It is the database-side view only: the Chert agent journal, the systemd units and the
    token expiry live on the host and belong to infra/monitor.py, which texts about them separately.
    """
    health = store.rpc("ch_jobs_health", {"p_now": now})
    start, end = parse_ts(cfg.get("window_start")), parse_ts(cfg.get("window_end"))
    stamp = "%b %-d %-I:%M%p"
    if now < start:
        window = "opens " + start.astimezone(ET).strftime(stamp) + " ET"
    elif now >= end:
        window = "ended " + end.astimezone(ET).strftime(stamp) + " ET"
    else:
        window = "open to " + end.astimezone(ET).strftime(stamp) + " ET"
    lines = "; ".join(f"{ln['line_id']} {ln['state']} {_age(now - parse_ts(ln['updated_at']))}"
                      for ln in health["lines"]) or "no active line"
    beat = health["heartbeats"].get(WORKER)
    worker = _age(now - parse_ts(beat)) if beat else "never"
    issues = Alerts(store, cfg).conditions(now)
    sent, failed = int(health["out_sent"]), int(health["out_failed"])
    if not (start <= now < end):
        verdict = "is off the clock"
    elif issues or not health["lines"] or beat is None:
        verdict = "needs a look"
    else:
        verdict = "looks up and working"
    return {"verdict": verdict, "lines": lines, "worker": worker, "window": window,
            "queue_len": health["queue_len"], "out_failed": failed, "out_total": sent + failed,
            "issues": "; ".join(f"{cond}: {detail}" for cond, detail in issues.items()) or "no alerts firing"}
